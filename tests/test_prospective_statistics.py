from __future__ import annotations

from football_agents.prospective_statistics import build_prospective_statistical_evidence


def _row(day: str, won: bool = True, clv: float = 0.03,
         model_probability: float = 0.75, market_probability: float = 0.60) -> dict:
    return {
        "settlement_day": day,
        "profit": 0.8 if won else -1.0,
        "clv": clv,
        "selected_outcome": "HOME",
        "actual_outcome": "HOME" if won else "AWAY",
        "predicted_probability": model_probability,
        "market_probability": market_probability,
    }


def test_settlement_day_bootstrap_is_deterministic_and_keeps_day_cohorts() -> None:
    rows = []
    for day in range(1, 11):
        won = day != 10
        rows.extend([_row(f"2026-01-{day:02d}", won=won) for _ in range(3)])

    first = build_prospective_statistical_evidence(rows, iterations=500, seed=9)
    second = build_prospective_statistical_evidence(rows, iterations=500, seed=9)

    assert first == second
    assert first["bootstrap"]["resampling_unit"] == "settlement_day"
    assert first["bootstrap"]["settlement_days"] == 10
    assert first["point_estimates"]["bets"] == 30
    assert first["bootstrap"]["roi_ci_pct"]["p05"] > 0
    assert first["bootstrap"]["average_clv_ci"]["p05"] > 0


def test_paired_calibration_reports_model_improvement_over_market() -> None:
    rows = [
        _row(f"2026-02-{index + 1:02d}", won=index < 8)
        for index in range(10)
    ]

    report = build_prospective_statistical_evidence(rows, iterations=500)
    point = report["point_estimates"]

    assert point["model_brier"] < point["market_brier"]
    assert point["model_log_loss"] < point["market_log_loss"]
    assert point["brier_improvement"] > 0
    assert point["log_loss_improvement"] > 0


def test_paired_calibration_detects_model_worse_than_market() -> None:
    rows = [
        _row(
            f"2026-03-{index + 1:02d}",
            won=index < 6,
            model_probability=0.90,
            market_probability=0.60,
        )
        for index in range(10)
    ]

    point = build_prospective_statistical_evidence(rows, iterations=200)["point_estimates"]

    assert point["brier_improvement"] < 0
    assert point["log_loss_improvement"] < 0


def test_empty_evidence_does_not_turn_missing_statistics_into_zero_edge() -> None:
    report = build_prospective_statistical_evidence([], iterations=100)

    assert report["point_estimates"]["roi_pct"] is None
    assert report["bootstrap"]["roi_ci_pct"]["p05"] is None
    assert report["bootstrap"]["probability_roi_positive"] is None
