from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from football_agents.db import Database
from football_agents.named_book_gap_research import (
    CLV_RIDGE_HALF_KELLY_POLICY_CONFIG,
    CLV_RIDGE_POLICY_CONFIG,
    NamedBookGapResearchService,
    _market_residual_probabilities,
    _net_execution_odds,
    _slippage_adjusted_odds,
    _settlement_day_bootstrap_roi,
)
from football_agents.repository import Repository


def _seed(tmp_path: Path, stale_keys: set[str] | None = None):
    database = Database(tmp_path / "named-gap.db")
    database.initialize()
    repository = Repository(database)
    now = datetime.now(timezone.utc)
    match_id = repository.create_match({
        "official_match_id": "sporttery-named-gap-1", "league": "Test",
        "home_team": "Home", "away_team": "Away",
        "kickoff_time": (now + timedelta(minutes=90)).isoformat(), "status": "scheduled",
    })
    with database.connect() as connection:
        connection.execute("UPDATE matches SET source_url=? WHERE id=?", ("https://example.test/official", match_id))
    stale_keys = stale_keys or set()
    prices = [
        ("Bet365", "bet365", 2.40, 3.10, 3.90),
        ("Book A", "book_a", 2.00, 3.20, 4.00),
        ("Book B", "book_b", 2.02, 3.15, 3.95),
        ("Book C", "book_c", 1.98, 3.25, 4.05),
        ("Book D", "book_d", 2.01, 3.18, 4.02),
        ("Book E", "book_e", 1.99, 3.22, 3.98),
    ]
    books = [
        {"bookmaker": name, "bookmaker_key": key, "market": "H2H",
         "odds": {"home": home, "draw": draw, "away": away},
         "last_update": (now - timedelta(minutes=20) if key in stale_keys else now).isoformat()}
        for name, key, home, draw, away in prices
    ]
    repository.archive_prospective_external_odds(
        repository.get_match(match_id),
        {"id": "event-named-gap", "sport_key": "soccer_test", "bookmakers": prices},
        books, now.isoformat(), "T_MINUS_1H",
    )
    return database, repository, match_id, now


def test_named_book_gap_freezes_timestamp_aligned_candidate_and_reports_settlement(tmp_path: Path) -> None:
    database, repository, match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)

    capture = service.capture(10, as_of=now + timedelta(seconds=2))
    repeat = service.capture(10, as_of=now + timedelta(seconds=3))

    assert capture["decisions"] == 1
    assert capture["predictions"] == 1
    assert repeat["decisions"] == 0
    assert capture["report"]["candidate_decisions"] == 1
    assert capture["report"]["paper_portfolio"]["pending_bets"] == 1
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM named_book_gap_decisions").fetchone()
        assert row["action"] == "CANDIDATE"
        assert row["selected_outcome"] == "home"
        assert row["expected_ev"] > 0
        assert row["execution_bookmaker_key"] == "bet365"
        assert len(__import__("json").loads(row["reference_bookmakers_json"])) == 5
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE named_book_gap_decisions SET action='NO_BET'")
    repository.upsert_result(match_id, 2, 0, (now + timedelta(hours=3)).isoformat())
    report = service.report(capture["report"]["policy"]["policy_id"])
    assert report["settled_selections"] == 1
    assert report["profit"] == pytest.approx(round(float(row["bet365_odds"]) - 1.0, 2))
    assert report["paper_portfolio"]["bets"] == 1
    assert report["paper_portfolio"]["same_day_results_hidden"] is True
    assert "real orders" in report["guardrail"]


def test_named_book_gap_requires_five_fresh_aligned_bookmakers(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(
        tmp_path, {"book_b", "book_c", "book_d", "book_e"}
    )
    service = NamedBookGapResearchService(database, repository)

    capture = service.capture(10, as_of=now + timedelta(seconds=2))

    assert capture["decisions"] == 0
    assert capture["blocker_counts"][0]["reason"] == "fresh_bookmakers<5"


def test_named_book_gap_ignores_result_recorded_before_kickoff(tmp_path: Path) -> None:
    database, repository, match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    capture = service.capture(10, as_of=now + timedelta(seconds=2))
    repository.upsert_result(match_id, 2, 0, (now + timedelta(minutes=30)).isoformat())

    report = service.report(capture["report"]["policy"]["policy_id"])

    assert report["settled_selections"] == 0
    assert report["paper_portfolio"]["pending_bets"] == 1
    assert report["paper_portfolio"]["profit"] == 0


def test_control_and_challenger_freeze_same_timestamp_snapshot(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)

    result = service.capture_experiment(10, as_of=now + timedelta(seconds=2))
    comparison = service.experiment_report()

    assert result["decisions"] == 4
    assert len(result["policies"]) == 4
    assert {row["report"]["policy"]["config"]["version"] for row in result["policies"]} == {
        "robust-leave-one-book-out-market-residual-prospective-v3.1-cost-aware",
        "robust-consensus-no-longshot-prospective-v4.1-cost-aware",
        "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
        "clv-ridge-v6.3-fixed-cap5-half-kelly-prospective-shadow",
    }
    with database.connect() as connection:
        decided_at = {row[0] for row in connection.execute(
            "SELECT decided_at FROM named_book_gap_decisions"
        ).fetchall()}
        ridge = connection.execute("""SELECT * FROM named_book_gap_decisions
            WHERE policy_id=?""", (
            service.ensure_policy(CLV_RIDGE_POLICY_CONFIG)["policy_id"],
        )).fetchone()
        ridge_half = connection.execute("""SELECT * FROM named_book_gap_decisions
            WHERE policy_id=?""", (
            service.ensure_policy(CLV_RIDGE_HALF_KELLY_POLICY_CONFIG)["policy_id"],
        )).fetchone()
    assert len(decided_at) == 1
    assert ridge["ranker_model_sha256"] == CLV_RIDGE_POLICY_CONFIG["ranker_model_sha256"]
    assert ridge["predicted_closing_edge_pct"] is not None
    assert ridge["selected_outcome"] == ridge_half["selected_outcome"]
    assert ridge["action"] == ridge_half["action"]
    assert ridge["predicted_closing_edge_pct"] == ridge_half["predicted_closing_edge_pct"]
    ridge_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"] == CLV_RIDGE_POLICY_CONFIG["version"]
    )
    assert ridge_report["prospective_warnings"]
    assert comparison["selection_locked_before_future_results"] is True


def test_market_residual_probabilities_are_normalized_and_shift_limited() -> None:
    reference = {"home": 0.50, "draw": 0.30, "away": 0.20}
    model = {"home": 0.80, "draw": 0.10, "away": 0.10}

    result = _market_residual_probabilities(reference, model, reliability=0.25, maximum_shift=0.03)

    assert sum(result.values()) == pytest.approx(1.0)
    assert result["home"] - reference["home"] <= 0.031


def test_execution_costs_apply_only_to_profit_component() -> None:
    commission_net = _net_execution_odds(3.0, 0.05)
    executable = _slippage_adjusted_odds(commission_net, 0.02)

    assert commission_net == pytest.approx(2.9)
    assert executable == pytest.approx(2.862)


def test_settlement_day_bootstrap_is_deterministic_and_clustered() -> None:
    positions = [
        {"status": "SETTLED", "settlement_date": f"2026-07-{day:02d}",
         "stake": 5.0, "profit": 1.0 if index % 3 else -1.0}
        for day in range(1, 11)
        for index in range(3)
    ]

    first = _settlement_day_bootstrap_roi(positions, iterations=200, seed=42)
    second = _settlement_day_bootstrap_roi(positions, iterations=200, seed=42)

    assert first == second
    assert first["status"] == "READY"
    assert first["settlement_days"] == 10
