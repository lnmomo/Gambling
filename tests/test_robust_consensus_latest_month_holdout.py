from __future__ import annotations

from dataclasses import replace
from datetime import date
import calendar
import csv

import scripts.robust_consensus_latest_month_holdout as holdout

from scripts.robust_consensus_latest_month_holdout import (
    HistoricalMatch,
    STRATEGIES,
    _candidate,
    _candidate_buckets,
    _monthly_bootstrap,
    _priced_books,
    audit,
    latest_complete_month,
    replay,
    rolling_nested,
)


def test_monthly_bootstrap_handles_zero_staked_positions() -> None:
    report = _monthly_bootstrap([
        {"month": f"2025-{month:02d}", "staked": 0.0, "profit": 0.0}
        for month in range(1, 13)
    ])
    assert report["status"] == "NO_STAKED_POSITIONS"
    assert report["lower_95_pct"] is None


def _books() -> tuple[dict, ...]:
    values = [
        ("best", 2.40, 3.10, 3.90),
        ("a", 2.00, 3.20, 4.00),
        ("b", 2.02, 3.15, 3.95),
        ("c", 1.98, 3.25, 4.05),
        ("d", 2.01, 3.18, 4.02),
        ("e", 1.99, 3.22, 3.98),
    ]
    return tuple({
        "bookmaker_key": key, "home_odds": home, "draw_odds": draw, "away_odds": away,
    } for key, home, draw, away in values)


def _closing_books(home_odds: float = 1.80) -> tuple[dict, ...]:
    return tuple({
        "bookmaker_key": f"close-{index}",
        "home_odds": home_odds,
        "draw_odds": 3.60,
        "away_odds": 5.00,
    } for index in range(6))


def test_load_matches_accepts_older_iw_and_vc_named_book_columns(tmp_path, monkeypatch) -> None:
    season_dir = tmp_path / "2122"
    season_dir.mkdir()
    path = season_dir / "E0.csv"
    fieldnames = [
        "Date", "Div", "HomeTeam", "AwayTeam", "FTR",
        "B365H", "B365D", "B365A", "BWH", "BWD", "BWA",
        "IWH", "IWD", "IWA", "VCH", "VCD", "VCA",
        "WHH", "WHD", "WHA",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "Date": "01/08/2021", "Div": "E0", "HomeTeam": "Home",
            "AwayTeam": "Away", "FTR": "H",
            "B365H": 2.0, "B365D": 3.2, "B365A": 4.0,
            "BWH": 2.02, "BWD": 3.18, "BWA": 3.95,
            "IWH": 1.99, "IWD": 3.22, "IWA": 4.05,
            "VCH": 2.01, "VCD": 3.19, "VCA": 4.02,
            "WHH": 1.98, "WHD": 3.21, "WHA": 4.01,
        })
    monkeypatch.setattr(holdout, "PROJECT_ROOT", tmp_path)

    matches = holdout.load_matches(tmp_path, ("2122",))

    assert len(matches) == 1
    assert {book["bookmaker_key"] for book in matches[0].books} == {
        "B365", "BW", "IW", "VC", "WH",
    }


def _match(index: int, actual: str = "home") -> HistoricalMatch:
    return HistoricalMatch(
        date(2026, 5, 10), "E0", f"Home {index}", f"Away {index}", actual,
        _books(), "fixture.csv", index + 2,
    )


def test_candidate_uses_best_named_book_and_excludes_it_from_reference() -> None:
    strategy = replace(STRATEGIES[0], minimum_conservative_ev=0.0)

    candidate = _candidate(_match(1), strategy)

    assert candidate is not None
    assert candidate["outcome"] == "home"
    assert candidate["execution_bookmaker"] == "best"
    assert "best" not in candidate["reference_bookmakers"]
    assert len(candidate["reference_bookmakers"]) == 5


def test_exchange_cost_defaults_to_bfe_and_can_be_stress_tested_with_bf() -> None:
    books = (
        {"bookmaker_key": "BF", "home_odds": 3.0, "draw_odds": 3.0, "away_odds": 3.0},
        {"bookmaker_key": "BFE", "home_odds": 3.0, "draw_odds": 3.0, "away_odds": 3.0},
    )
    official = replace(STRATEGIES[0], exchange_commission_rate=0.05)
    stressed = replace(official, exchange_bookmaker_keys=("BFE", "BF"))

    official_prices = {row["bookmaker_key"]: row for row in _priced_books(books, official)}
    stressed_prices = {row["bookmaker_key"]: row for row in _priced_books(books, stressed)}

    assert official_prices["BF"]["home_odds"] == 3.0
    assert official_prices["BFE"]["home_odds"] == 2.9
    assert stressed_prices["BF"]["home_odds"] == 2.9
    assert _candidate_buckets({
        "outcome": "home", "odds": 2.9, "execution_bookmaker": "BF",
        "execution_cost_rate": 0.05,
    })[-1] == "source:exchange"


def test_candidate_rejects_execution_quote_far_above_reference_consensus() -> None:
    anomalous = list(_books())
    anomalous[0] = {
        "bookmaker_key": "best", "home_odds": 3.25, "draw_odds": 3.10, "away_odds": 3.90,
    }
    match = replace(_match(1), books=tuple(anomalous))
    unrestricted = replace(STRATEGIES[0], minimum_conservative_ev=0.0)
    sanity_checked = replace(unrestricted, maximum_price_ratio=1.15)

    unrestricted_candidate = _candidate(match, unrestricted)
    checked_candidate = _candidate(match, sanity_checked)

    assert unrestricted_candidate is not None
    assert unrestricted_candidate["execution_bookmaker"] == "best"
    assert unrestricted_candidate["price_ratio"] > 1.15
    assert checked_candidate is None or checked_candidate["price_ratio"] <= 1.15


def test_daily_replay_freezes_stakes_before_results_and_caps_100() -> None:
    strategy = replace(STRATEGIES[0], minimum_conservative_ev=0.0)
    winners = [_match(index, "home") for index in range(50)]
    losers = [_match(index, "away") for index in range(50)]

    winning_report = replay(winners, strategy, date(2026, 5, 10), date(2026, 5, 10))
    losing_report = replay(losers, strategy, date(2026, 5, 10), date(2026, 5, 10))

    assert winning_report["staked"] <= 100.0
    assert winning_report["bets"] == losing_report["bets"]
    assert winning_report["staked"] == losing_report["staked"]
    assert [row["stake"] for row in winning_report["positions"]] == [
        row["stake"] for row in losing_report["positions"]
    ]
    assert winning_report["profit"] > losing_report["profit"]


def test_closing_snapshot_cannot_change_frozen_bet_or_stake() -> None:
    strategy = replace(STRATEGIES[0], minimum_conservative_ev=0.0)
    base = _match(1)
    positive_close = replace(base, closing_books=_closing_books(1.80))
    negative_close = replace(base, closing_books=_closing_books(2.80))

    positive = replay([positive_close], strategy, date(2026, 5, 10), date(2026, 5, 10))
    negative = replay([negative_close], strategy, date(2026, 5, 10), date(2026, 5, 10))

    assert positive["bets"] == negative["bets"] == 1
    assert positive["staked"] == negative["staked"]
    assert positive["positions"][0]["outcome"] == negative["positions"][0]["outcome"]
    assert positive["positions"][0]["closing_edge_pct"] > negative["positions"][0]["closing_edge_pct"]


def test_latest_complete_month_is_selected_by_coverage_not_profit() -> None:
    matches = [
        HistoricalMatch(date(2026, 4, 30), "E0", "A", "B", "home", _books(), "a.csv", 2),
        HistoricalMatch(date(2026, 5, 30), "E0", "C", "D", "away", _books(), "a.csv", 3),
        HistoricalMatch(date(2026, 3, 31), "E0", "E", "F", "draw", _books(), "a.csv", 4),
    ]

    start, end = latest_complete_month(matches, minimum_rows=1)

    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_audit_rejects_tiny_profitable_direction_concentrated_month(tmp_path) -> None:
    output = tmp_path / "experiment"
    output.mkdir()
    (output / "holdout_summary.json").write_text(__import__("json").dumps({
        "sealed_test_window": "2026-05-01..2026-05-31",
        "selected_strategy": "test", "unlimited_principal_daily_investment_cap": 100.0,
        "staked": 2.0, "profit": 1.0, "roi_pct": 50.0,
        "daily": [{"bets": 4}] + [{"bets": 0}] * 30,
        "positions": [{"outcome": "away"}] * 4,
    }), encoding="utf-8")

    result = audit(output)

    assert result["nominal_result"] == "POSITIVE"
    assert result["evidence_decision"] == "INSUFFICIENT_SAMPLE"
    assert result["profitability_claim_allowed"] is False
    assert result["maximum_outcome_concentration_pct"] == 100.0


def test_nested_month_selects_before_holdout_result_is_revealed(tmp_path) -> None:
    winners = []
    losers = []
    for month in range(1, 9):
        day = calendar.monthrange(2026, month)[1]
        for index in range(10):
            base = HistoricalMatch(
                date(2026, month, day), "E0", f"H-{month}-{index}", f"A-{month}-{index}",
                "home", _books(), f"month-{month}.csv", index + 2,
            )
            winners.append(base)
            losers.append(replace(base, actual_outcome="away") if month == 7 else base)

    positive = rolling_nested(tmp_path / "positive", 1, winners, minimum_month_rows=1)
    negative = rolling_nested(tmp_path / "negative", 1, losers, minimum_month_rows=1)

    assert positive["latest_sealed_month_excluded"] == "2026-08"
    assert positive["monthly"][0]["month"] == "2026-07"
    assert positive["monthly"][0]["selected_strategy"] == negative["monthly"][0]["selected_strategy"]
    assert positive["monthly"][0]["staked"] == negative["monthly"][0]["staked"]
    assert positive["monthly"][0]["profit"] > negative["monthly"][0]["profit"]


def test_clv_selection_uses_training_close_only_and_not_holdout_result(tmp_path) -> None:
    winners = []
    losers = []
    for month in range(1, 9):
        day = calendar.monthrange(2026, month)[1]
        for index in range(10):
            base = HistoricalMatch(
                date(2026, month, day), "E0", f"H-{month}-{index}", f"A-{month}-{index}",
                "home", _books(), f"clv-month-{month}.csv", index + 2, _closing_books(),
            )
            winners.append(base)
            losers.append(replace(base, actual_outcome="away") if month == 7 else base)

    positive = rolling_nested(
        tmp_path / "clv-positive", 1, winners, minimum_month_rows=1,
        selection_mode="clv_bucket_stability",
    )
    negative = rolling_nested(
        tmp_path / "clv-negative", 1, losers, minimum_month_rows=1,
        selection_mode="clv_bucket_stability",
    )

    assert positive["monthly"][0]["selected_strategy"] != "ABSTAIN"
    assert positive["monthly"][0]["selected_strategy"] == negative["monthly"][0]["selected_strategy"]
    assert positive["monthly"][0]["staked"] == negative["monthly"][0]["staked"]
    assert positive["monthly"][0]["clv_bucket_gate"] == negative["monthly"][0]["clv_bucket_gate"]
    assert positive["monthly"][0]["profit"] > negative["monthly"][0]["profit"]
