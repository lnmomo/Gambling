from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import football_agents.named_book_gap_research as named_gap
from football_agents.db import Database
from football_agents.named_book_gap_research import (
    CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG,
    CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG,
    CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG,
    CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG,
    CLV_RIDGE_HALF_KELLY_POLICY_CONFIG,
    CLV_RIDGE_POLICY_CONFIG,
    CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG,
    CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG,
    CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG,
    CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG,
    CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG,
    CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG,
    CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG,
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
    report = service.report(
        capture["report"]["policy"]["policy_id"], now + timedelta(hours=3, seconds=1)
    )
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


def test_depth_discount_scales_live_paper_stake_using_opening_references(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path, {"book_e"})
    service = NamedBookGapResearchService(database, repository)
    assert CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG is not None
    assert CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG is not None

    baseline = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG,
    )["report"]["paper_portfolio"]
    discounted = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG,
    )["report"]["paper_portfolio"]

    assert baseline["pending_bets"] == discounted["pending_bets"] == 1
    assert discounted["positions"][0]["reference_depth"] == 4
    assert discounted["positions"][0]["stake_multiplier"] == 0.5
    assert discounted["staked"] == round(baseline["staked"] * 0.5, 2)


def test_minimum_staking_probability_blocks_low_probability_candidate(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    assert CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG is not None
    strict = {
        **CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG,
        "version": "test-minimum-staking-probability",
        "minimum_staking_probability": 0.99,
    }

    capture = service.capture(
        10, as_of=now + timedelta(seconds=2), policy_config=strict,
    )

    assert capture["decisions"] == 1
    assert capture["predictions"] == 0
    with database.connect() as connection:
        row = connection.execute("SELECT action,blockers_json FROM named_book_gap_decisions").fetchone()
    assert row["action"] == "NO_BET"
    assert "conservative_probability_below_policy_minimum" in row["blockers_json"]


def test_five_eighths_kelly_increases_only_paper_stake(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    assert CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG is not None
    assert CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG is not None

    half = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG,
    )["report"]["paper_portfolio"]
    five_eighths = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG,
    )["report"]["paper_portfolio"]

    assert half["pending_bets"] == five_eighths["pending_bets"] == 1
    assert five_eighths["staked"] == pytest.approx(half["staked"] * 1.25, abs=0.01)
    assert five_eighths["daily_budget_limit"] == 100.0


def test_paper_portfolio_caps_same_day_same_league_proportionally() -> None:
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    candidates = [
        {
            "decision_id": f"decision-{index}", "decided_at": now.isoformat(),
            "match_id": index, "selected_outcome": "home", "bet365_odds": 2.5,
            "conservative_probability": 0.8, "reference_probability": 0.4,
            "reference_bookmakers_json": '["a","b","c","d","e"]',
            "execution_bookmaker": "Book", "league": "E0",
            "result_settled_at": None, "actual_outcome": None,
        }
        for index in range(2)
    ]
    config = {
        "daily_budget": 100.0, "maximum_single_stake": 15.0,
        "kelly_fraction": 0.75, "minimum_reference_depth": 4,
        "minimum_depth_stake_multiplier": 0.5,
        "maximum_daily_league_stake": 15.0,
    }

    portfolio = NamedBookGapResearchService._paper_portfolio(
        candidates, config, as_of=now
    )

    assert portfolio["staked"] == 15.0
    assert [row["stake"] for row in portfolio["positions"]] == [7.5, 7.5]
    assert portfolio["maximum_daily_league_stake"] == 15.0


def test_v827_freezes_dual_cost_market_consensus_shadow_position(tmp_path: Path) -> None:
    database, repository, match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    assert CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG is not None

    capture = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG,
    )

    assert capture["decisions"] == 1
    assert capture["predictions"] == 1
    report = capture["report"]
    assert report["paper_portfolio"]["pending_bets"] == 1
    assert report["paper_portfolio"]["daily_budget_limit"] == 100.0
    assert report["paper_portfolio"]["maximum_daily_league_stake"] == 15.0
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM named_book_gap_decisions WHERE policy_id=?",
            (report["policy"]["policy_id"],),
        ).fetchone()
    assert row["conservative_probability"] == pytest.approx(
        row["reference_probability"]
    )
    repository.upsert_result(match_id, 2, 0, (now + timedelta(hours=3)).isoformat())
    premature = service.report(
        report["policy"]["policy_id"], now + timedelta(seconds=3)
    )
    assert premature["settled_selections"] == 0
    assert premature["paper_portfolio"]["profit"] == 0
    assert "real orders" in premature["guardrail"]
    mature = service.report(
        report["policy"]["policy_id"], now + timedelta(hours=3, seconds=1)
    )
    assert mature["settled_selections"] == 1


def test_paper_portfolio_carries_equity_into_rolling_window() -> None:
    observed = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    candidates = [
        {
            "decision_id": "old", "decided_at": "2026-06-01T01:00:00+00:00",
            "match_id": 1, "selected_outcome": "home", "actual_outcome": "home",
            "bet365_odds": 2.0, "conservative_probability": 0.6,
            "reference_probability": 0.55,
            "reference_bookmakers_json": '["a","b","c","d","e"]',
            "execution_bookmaker": "Book", "league": "E0",
            "result_settled_at": "2026-06-02T01:00:00+00:00",
        },
        {
            "decision_id": "current", "decided_at": "2026-07-20T01:00:00+00:00",
            "match_id": 2, "selected_outcome": "home", "actual_outcome": "home",
            "bet365_odds": 2.0, "conservative_probability": 0.6,
            "reference_probability": 0.55,
            "reference_bookmakers_json": '["a","b","c","d","e"]',
            "execution_bookmaker": "Book", "league": "E0",
            "result_settled_at": "2026-07-21T01:00:00+00:00",
        },
    ]
    config = {
        "daily_budget": 100.0, "maximum_single_stake": 15.0,
        "kelly_fraction": 0.25, "minimum_reference_depth": 4,
        "minimum_depth_stake_multiplier": 0.5,
        "maximum_daily_league_stake": 15.0,
    }

    portfolio = NamedBookGapResearchService._paper_portfolio(
        candidates, config, as_of=observed
    )

    assert portfolio["opening_equity"] > 0
    assert portfolio["ending_equity"] == portfolio["profit"]
    assert portfolio["daily"][-1]["equity"] == portfolio["ending_equity"]


def test_named_book_gap_ignores_result_recorded_before_kickoff(tmp_path: Path) -> None:
    database, repository, match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    capture = service.capture(10, as_of=now + timedelta(seconds=2))
    repository.upsert_result(match_id, 2, 0, (now + timedelta(minutes=30)).isoformat())

    report = service.report(
        capture["report"]["policy"]["policy_id"], now + timedelta(minutes=31)
    )

    assert report["settled_selections"] == 0
    assert report["paper_portfolio"]["pending_bets"] == 1
    assert report["paper_portfolio"]["profit"] == 0


def test_control_and_challenger_freeze_same_timestamp_snapshot(tmp_path: Path) -> None:
    database, repository, _match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)

    result = service.capture_experiment(10, as_of=now + timedelta(seconds=2))
    comparison = service.experiment_report()

    assert result["decisions"] == 17
    assert len(result["policies"]) == 17
    assert {row["report"]["policy"]["config"]["version"] for row in result["policies"]} == {
        "robust-leave-one-book-out-market-residual-prospective-v3.1-cost-aware",
        "robust-consensus-no-longshot-prospective-v4.1-cost-aware",
        "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
        "clv-ridge-v6.3-fixed-cap5-half-kelly-prospective-shadow",
        "clv-ridge-v6.6-market-structure-half-kelly-prospective-shadow",
        "clv-ridge-v7.6-dual-target-agreement-half-kelly-prospective-shadow",
        "clv-ridge-v8.1-9m3m-dual-target-agreement-half-kelly-prospective-shadow",
        "clv-ridge-v8.5-month-stable-depth-discount-prospective-shadow",
        "clv-ridge-v8.7-min25pct-probability-prospective-shadow",
        "clv-ridge-v8.8-five-eighths-kelly-prospective-shadow",
        "clv-ridge-v8.11-quote-sanity-min2pct-clv-prospective-shadow",
        "clv-ridge-v8.13-quote-sanity-three-quarter-kelly-prospective-shadow",
        "clv-ridge-v8.18-training-market-calibrated-kelly-prospective-shadow",
        "clv-ridge-v8.21-daily-league-cap15-prospective-shadow",
        "clv-ridge-v8.27-dual-cost-calibrated-governance-prospective-shadow",
        "clv-ridge-v8.28-restored-calibrated-governance-prospective-shadow",
        "clv-ridge-v8.33-multi-horizon-core-satellite-prospective-shadow",
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
    v66_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v6.6")
    )
    assert "5% cost stress" in v66_report["prospective_warnings"][0]
    v76_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v7.6")
    )
    assert "5% cost bootstrap" in v76_report["prospective_warnings"][0]
    assert CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG is not None
    v81_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.1")
    )
    assert "paper-only" in v81_report["prospective_warnings"][0]
    assert v81_report["policy"]["config"]["latest_retraining_gate"].startswith("PASSED")
    assert CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG is not None
    v85_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.5")
    )
    assert v85_report["policy"]["config"]["minimum_depth_stake_multiplier"] == 0.5
    assert v85_report["policy"]["config"]["minimum_inner_positive_month_rate"] == 0.6
    assert CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG is not None
    v87_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.7")
    )
    assert v87_report["policy"]["config"]["minimum_staking_probability"] == 0.25
    assert CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG is not None
    v88_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.8")
    )
    assert v88_report["policy"]["config"]["kelly_fraction"] == 0.625
    assert v88_report["policy"]["config"]["maximum_price_ratio"] == 1.15
    assert "v8.10" in v88_report["policy"]["config"]["quote_sanity_audit"]
    assert "inflated" in v88_report["prospective_warnings"][0]
    assert CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG is not None
    v811_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.11")
    )
    assert v811_report["policy"]["config"]["minimum_lower_clv_pct"] == 2.0
    assert v811_report["policy"]["config"]["latest_retraining_gate"].startswith("FAILED")
    assert CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG is not None
    v813_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.13")
    )
    assert v813_report["policy"]["config"]["kelly_fraction"] == 0.75
    assert "12.84" in v813_report["policy"]["config"]["historical_risk_gate"]
    assert CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG is not None
    v818_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.18")
    )
    assert v818_report["policy"]["config"]["staking_probability_profile"] == "training_market_platt"
    assert "22.29" in v818_report["policy"]["config"]["historical_risk_gate"]
    assert CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG is not None
    v821_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.21")
    )
    assert v821_report["policy"]["config"]["maximum_daily_league_stake"] == 15.0
    assert v821_report["policy"]["config"]["research_evidence_status"] == (
        "LEGACY_SURVIVOR_REJECTED_BY_NEW_CONCENTRATION_GATE"
    )
    assert v821_report["policy"]["config"]["profit_concentration_gate"].startswith(
        "FAILED_"
    )
    assert CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG is not None
    v827_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.27")
    )
    assert v827_report["policy"]["config"]["staking_probability_profile"] == (
        "opening_market_consensus"
    )
    assert v827_report["policy"]["config"]["stress_exchange_commission_rate"] == 0.05
    assert v827_report["paper_portfolio"]["daily_budget_limit"] == 100.0
    assert CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG is not None
    v828_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.28")
    )
    assert v828_report["policy"]["config"]["staking_probability_profile"] == (
        "training_market_platt"
    )
    assert "stress_exchange_commission_rate" not in v828_report["policy"]["config"]
    assert v828_report["policy"]["config"]["governance_gate_profile"] == (
        "closing_probability_calibrated"
    )
    assert v828_report["policy"]["config"]["profit_concentration_gate"].startswith(
        "PASSED_2.5pct"
    )
    assert v828_report["paper_portfolio"]["daily_budget_limit"] == 100.0
    assert v828_report["paper_portfolio"]["maximum_daily_league_stake"] == 15.0
    assert CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG is not None
    v833_report = next(
        row["report"] for row in result["policies"]
        if row["report"]["policy"]["config"]["version"].startswith("clv-ridge-v8.33")
    )
    assert v833_report["policy"]["config"]["satellite_kelly_fraction"] == 0.3125
    assert v833_report["paper_portfolio"]["daily_budget_limit"] == 100.0
    assert v833_report["paper_portfolio"]["maximum_daily_league_stake"] == 15.0
    assert set(v833_report["selection_diagnostics"]["horizon_role_counts"]) <= {
        "9m3m_core", "18m9m_satellite",
    }
    assert comparison["selection_locked_before_future_results"] is True


def test_multi_horizon_uses_long_satellite_when_core_is_ineligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG is not None
    database, repository, _match_id, now = _seed(tmp_path)
    service = NamedBookGapResearchService(database, repository)
    monkeypatch.setattr(named_gap, "_score_clv_agreement", lambda *_: {
        "predicted_clv": 0.0,
        "lower_predicted_clv": -1.0,
        "market_staking_probabilities": [0.40],
        "model_sha256": "core",
    })
    monkeypatch.setattr(named_gap, "_score_long_horizon_agreement", lambda *_: {
        "predicted_clv": 6.0,
        "lower_predicted_clv": 5.0,
        "market_staking_probabilities": [],
        "model_sha256": "long",
    })

    result = service.capture(
        10, as_of=now + timedelta(seconds=2),
        policy_config=CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG,
    )

    assert result["decisions"] == 1
    with database.connect() as connection:
        row = dict(connection.execute(
            "SELECT * FROM named_book_gap_decisions WHERE policy_id=?",
            (result["report"]["policy"]["policy_id"],),
        ).fetchone())
    assert row["action"] == "CANDIDATE"
    assert row["horizon_role"] == "18m9m_satellite"
    assert row["effective_kelly_fraction"] == pytest.approx(0.3125)
    assert row["ranker_model_sha256"] == "long"
    position = result["report"]["paper_portfolio"]["positions"][0]
    assert position["horizon_role"] == "18m9m_satellite"
    assert position["effective_kelly_fraction"] == pytest.approx(0.3125)


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
