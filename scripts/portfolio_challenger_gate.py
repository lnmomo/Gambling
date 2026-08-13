"""Compare frozen portfolio challengers using outcome-independent evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _metric(report: dict[str, Any], *path: str) -> float:
    value: Any = report
    for key in path:
        value = value[key]
    return float(value)


def _position_count(report: dict[str, Any]) -> int:
    for key in ("positions", "agreement_positions"):
        if key in report:
            return int(report[key])
    raise KeyError("report must contain positions or agreement_positions")


def evaluate_challenger(
    baseline: dict[str, Any], challenger: dict[str, Any],
    minimum_relative_expected_profit_improvement: float = 0.02,
    minimum_incremental_positions: int = 30,
    maximum_drawdown_increase: float = 0.05,
) -> dict[str, Any]:
    baseline_expected = _metric(
        baseline, "closing_value", "all", "closing_expected_profit"
    )
    challenger_expected = _metric(
        challenger, "closing_value", "all", "closing_expected_profit"
    )
    expected_delta = challenger_expected - baseline_expected
    relative_expected_delta = (
        expected_delta / baseline_expected if baseline_expected > 0 else None
    )
    baseline_positions = _position_count(baseline)
    challenger_positions = _position_count(challenger)
    incremental_positions = challenger_positions - baseline_positions
    baseline_drawdown = float(baseline["maximum_drawdown"])
    challenger_drawdown = float(challenger["maximum_drawdown"])
    drawdown_increase = (
        challenger_drawdown / baseline_drawdown - 1.0
        if baseline_drawdown > 0 else None
    )
    baseline_late = _metric(
        baseline, "closing_value", "late", "closing_expected_profit"
    )
    challenger_late = _metric(
        challenger, "closing_value", "late", "closing_expected_profit"
    )
    iid_lower = _metric(
        challenger, "closing_expected_monthly_stability",
        "monthly_bootstrap_roi", "lower_95_pct",
    )
    block_lower = _metric(
        challenger, "closing_expected_monthly_stability",
        "moving_block_bootstrap_roi", "lower_95_pct",
    )
    checks = {
        "historical_research_survivor": (
            challenger.get("decision") == "ROLLING_RESEARCH_SURVIVOR"
        ),
        "absolute_closing_expected_profit_improved": expected_delta > 0,
        "relative_closing_expected_profit_improvement_material": (
            relative_expected_delta is not None
            and relative_expected_delta
            >= minimum_relative_expected_profit_improvement
        ),
        "incremental_positions_material": (
            incremental_positions >= minimum_incremental_positions
        ),
        "maximum_drawdown_increase_within_limit": (
            drawdown_increase is not None
            and drawdown_increase <= maximum_drawdown_increase + 1e-12
        ),
        "late_closing_expected_profit_not_reduced": (
            challenger_late >= baseline_late
        ),
        "closing_expected_iid_lower_95_positive": iid_lower > 0,
        "closing_expected_block_lower_95_positive": block_lower > 0,
    }
    return {
        "decision": "CHALLENGER_ACCEPTED" if all(checks.values()) else "CHALLENGER_REJECTED",
        "checks": checks,
        "metrics": {
            "baseline_positions": baseline_positions,
            "challenger_positions": challenger_positions,
            "incremental_positions": incremental_positions,
            "baseline_closing_expected_profit": round(baseline_expected, 4),
            "challenger_closing_expected_profit": round(challenger_expected, 4),
            "closing_expected_profit_delta": round(expected_delta, 4),
            "relative_closing_expected_profit_improvement_pct": (
                round(relative_expected_delta * 100.0, 4)
                if relative_expected_delta is not None else None
            ),
            "baseline_late_closing_expected_profit": round(baseline_late, 4),
            "challenger_late_closing_expected_profit": round(challenger_late, 4),
            "baseline_maximum_drawdown": round(baseline_drawdown, 4),
            "challenger_maximum_drawdown": round(challenger_drawdown, 4),
            "drawdown_increase_pct": (
                round(drawdown_increase * 100.0, 4)
                if drawdown_increase is not None else None
            ),
            "closing_expected_iid_lower_95_pct": round(iid_lower, 4),
            "closing_expected_block_lower_95_pct": round(block_lower, 4),
        },
        "thresholds": {
            "minimum_relative_expected_profit_improvement_pct": round(
                minimum_relative_expected_profit_improvement * 100.0, 4
            ),
            "minimum_incremental_positions": minimum_incremental_positions,
            "maximum_drawdown_increase_pct": round(
                maximum_drawdown_increase * 100.0, 4
            ),
        },
        "guardrail": (
            "Realized match profit is reported nowhere in this gate and cannot select "
            "a challenger. Historical acceptance still requires prospective evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--challenger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-relative-improvement", type=float, default=0.02)
    parser.add_argument("--minimum-incremental-positions", type=int, default=30)
    parser.add_argument("--maximum-drawdown-increase", type=float, default=0.05)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    challenger = json.loads(args.challenger.read_text(encoding="utf-8-sig"))
    report = evaluate_challenger(
        baseline, challenger, args.minimum_relative_improvement,
        args.minimum_incremental_positions, args.maximum_drawdown_increase,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
