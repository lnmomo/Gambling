from __future__ import annotations

from copy import deepcopy

from scripts.portfolio_challenger_gate import evaluate_challenger


def _report() -> dict:
    return {
        "positions": 100,
        "maximum_drawdown": 10.0,
        "decision": "ROLLING_RESEARCH_SURVIVOR",
        "closing_value": {
            "all": {"closing_expected_profit": 20.0},
            "late": {"closing_expected_profit": 5.0},
        },
        "closing_expected_monthly_stability": {
            "monthly_bootstrap_roi": {"lower_95_pct": 2.0},
            "moving_block_bootstrap_roi": {"lower_95_pct": 1.5},
        },
    }


def test_challenger_gate_accepts_material_outcome_independent_improvement() -> None:
    baseline = _report()
    challenger = deepcopy(baseline)
    challenger["positions"] = 130
    challenger["maximum_drawdown"] = 10.5
    challenger["closing_value"]["all"]["closing_expected_profit"] = 20.5
    challenger["closing_value"]["late"]["closing_expected_profit"] = 5.1

    report = evaluate_challenger(baseline, challenger)

    assert report["decision"] == "CHALLENGER_ACCEPTED"


def test_challenger_gate_rejects_immaterial_gain_without_reading_realized_profit() -> None:
    baseline = _report()
    challenger = deepcopy(baseline)
    baseline["profit"] = -1000.0
    challenger["profit"] = 1000.0
    challenger["positions"] = 109
    challenger["closing_value"]["all"]["closing_expected_profit"] = 20.1

    report = evaluate_challenger(baseline, challenger)

    assert report["decision"] == "CHALLENGER_REJECTED"
    assert not report["checks"]["relative_closing_expected_profit_improvement_material"]
    assert not report["checks"]["incremental_positions_material"]


def test_challenger_gate_accepts_agreement_report_position_field() -> None:
    baseline = _report()
    challenger = deepcopy(baseline)
    baseline["agreement_positions"] = baseline.pop("positions")
    challenger["agreement_positions"] = challenger.pop("positions") + 30
    challenger["closing_value"]["all"]["closing_expected_profit"] = 21.0
    challenger["closing_value"]["late"]["closing_expected_profit"] = 5.1

    report = evaluate_challenger(baseline, challenger)

    assert report["metrics"]["baseline_positions"] == 100
    assert report["metrics"]["challenger_positions"] == 130
    assert report["decision"] == "CHALLENGER_ACCEPTED"
