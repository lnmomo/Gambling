"""Validate timestamp-unverified, named B365-versus-Pinnacle opening gaps.

The CSV provides named opening columns but not an intra-day quote timestamp.
This is therefore a research-only bridge hypothesis, never a promotion input.
All decisions use B365 as the executable price and a complete Pinnacle triplet
only for de-vigging; the model probability is not used for EV.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from football_agents.portfolio_backtest import BacktestConfig, load_football_data_rows, run_daily_portfolio
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, PROJECT_ROOT, _risk_adjusted_score
from scripts.portfolio_algorithm_rolling_validation import _aggregate, _fold


FOLDS = (
    (2022, 3), (2022, 9), (2023, 3), (2023, 9),
    (2024, 3), (2024, 9), (2025, 3), (2025, 9),
)
CANDIDATES = tuple(
    BacktestConfig(
        name=f"B365-vs-Pinnacle-edge{ratio:.2f}",
        execution_price_source="bet365_opening",
        bet_region="named_book_edge",
        named_book_edge_ratio=ratio,
        min_ev=0.0,
        minimum_odds=1.5,
        maximum_odds=6.0,
        drawdown_control=True,
        residual_retention=0.0,
    )
    for ratio in (1.02, 1.04, 1.06)
)


def _parse_fold(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", maxsplit=1))
        datetime(year, month, 1)
        return year, month
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM") from exc


def _summary_row(report: dict) -> dict:
    return {key: report[key] for key in (
        "config_name", "matches_in_window", "bets", "staked", "profit", "roi_pct",
        "win_rate", "max_drawdown", "execution_price_source", "named_book_edge_ratio",
    )}


def _eligible_train_candidates(rows: list[dict], segments: dict[str, list[dict]] | None = None) -> list[dict]:
    """Reject sparse or losing configurations before ranking them.

    Thresholds are intentionally fixed and modest. They prevent a single
    lucky price gap in a six-month train window from forcing a later bet.
    """
    eligible = [
        row for row in rows
        if int(row["bets"]) >= 30
        and float(row["staked"]) >= 10.0
        and float(row["profit"]) > 0
    ]
    if segments is None:
        return eligible
    return [
        row for row in eligible
        if all(
            int(segment["bets"]) >= 15
            and float(segment["staked"]) >= 5.0
            and float(segment["profit"]) > 0
            for segment in segments.get(str(row["config_name"]), [])
        )
    ]


def _three_month_boundary(start: datetime) -> datetime:
    month_index = start.month - 1 + 3
    return datetime(start.year + month_index // 12, month_index % 12 + 1, 1, tzinfo=start.tzinfo)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold-start", action="append", type=_parse_fold)
    parser.add_argument(
        "--nested-selection", action="store_true",
        help="Select a gap threshold from the prior six-month train window before each holdout.",
    )
    parser.add_argument(
        "--persistent-train", action="store_true",
        help="Require both adjacent three-month training segments to have positive, material results.",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "reports" / "named_book_edge_rolling_validation",
    )
    args = parser.parse_args()
    if args.persistent_train and not args.nested_selection:
        parser.error("--persistent-train requires --nested-selection")
    folds = tuple(args.fold_start) if args.fold_start else FOLDS
    records = load_football_data_rows(
        [str(DATA_BASE / season) for season in ALL_SEASONS], primary_price_source="bet365"
    )
    rows = {candidate.name: [] for candidate in CANDIDATES}
    fold_rows: list[dict] = []
    selected_holdouts: list[dict] = []
    for year, month in folds:
        fold = _fold(year, month)
        candidates = {}
        train_rows: list[dict] = []
        segment_rows: dict[str, list[dict]] = {}
        if args.nested_selection:
            for candidate in CANDIDATES:
                train_rows.append(_summary_row(run_daily_portfolio(
                    records, candidate, fold["train_start"], fold["train_end"]
                )))
                if args.persistent_train:
                    boundary = _three_month_boundary(fold["train_start"])
                    segment_rows[candidate.name] = [
                        _summary_row(run_daily_portfolio(
                            records, candidate, fold["train_start"], boundary - timedelta(days=1)
                        )),
                        _summary_row(run_daily_portfolio(
                            records, candidate, boundary, fold["train_end"]
                        )),
                    ]
        for candidate in CANDIDATES:
            row = _summary_row(run_daily_portfolio(
                records, candidate, fold["holdout_start"], fold["holdout_end"]
            ))
            rows[candidate.name].append(row)
            candidates[candidate.name] = row
        fold_row = {
            "holdout_window": f"{fold['holdout_start'].date()}..{fold['holdout_end'].date()}",
            "candidates": candidates,
        }
        if args.nested_selection:
            eligible = _eligible_train_candidates(train_rows, segment_rows if args.persistent_train else None)
            selected = max(eligible, key=_risk_adjusted_score) if eligible else None
            fold_row["train_window"] = f"{fold['train_start'].date()}..{fold['train_end'].date()}"
            fold_row["train_candidates"] = {row["config_name"]: row for row in train_rows}
            if args.persistent_train:
                fold_row["train_segments"] = segment_rows
            fold_row["selected_on_train"] = selected["config_name"] if selected else "ABSTAIN"
            fold_row["selection_reason"] = (
                "positive_profit_min30_bets_min10_staked"
                + ("_and_two_positive_3month_segments" if args.persistent_train else "")
                + "_risk_adjusted_score"
                if selected else "no_train_candidate_passed_fixed_eligibility"
            )
            if selected:
                selected_holdouts.append(candidates[selected["config_name"]])
        fold_rows.append(fold_row)
    observed = {name: [row for row in values if row["matches_in_window"] > 0] for name, values in rows.items()}
    payload = {
        "method": {
            "execution_price": "bet365_opening",
            "reference_probability": "pinnacle_opening multiplicative de-vig",
            "timing": "opening fields only; source alignment timestamp unavailable",
            "same_day_rule": "all decisions freeze before any result on that date is revealed",
            "research_only": True,
        },
        "folds": fold_rows,
        "aggregate": {name: _aggregate(values) for name, values in observed.items()},
        "nested_selection": {
            "enabled": args.nested_selection,
            "train_months": 6 if args.nested_selection else None,
            "persistent_train": args.persistent_train,
            "selection_rule": (
                "positive profit, at least 30 bets, at least 10 stake units"
                + (", plus two adjacent positive 3-month segments (at least 15 bets and 5 stake units each)" if args.persistent_train else "")
                + ", then maximum training profit/drawdown"
                if args.nested_selection else None
            ),
            "selected_holdout_aggregate": _aggregate(selected_holdouts) if args.nested_selection else None,
            "abstained_folds": sum(row.get("selected_on_train") == "ABSTAIN" for row in fold_rows),
        },
        "promotion_rule": "RESEARCH_ONLY: a timestamp-aligned prospective study is required even if the historical aggregate is positive.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "rolling_validation_summary.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
