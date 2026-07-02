from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from market_bias_candidate_screen import load_candidate_rules
from market_bias_walk_forward import _parse_rule


def _matches_rule(frame: pd.DataFrame, rule: str) -> pd.Series:
    columns_raw, key_raw = rule.split("=", 1)
    columns = _parse_rule(columns_raw)
    key = _parse_rule(key_raw)
    if len(columns) != len(key):
        raise ValueError(f"rule key length mismatch: {rule}")
    mask = pd.Series(True, index=frame.index)
    for column, value in zip(columns, key):
        if column not in frame.columns:
            raise ValueError(f"market candidate frame missing column {column!r}")
        mask &= frame[column].astype(str).eq(str(value))
    return mask


def build_unit_bets(
    market_candidate_paths: list[Path],
    diagnostic_paths: list[Path],
    *,
    top_n: int,
    min_diagnostic_sources: int,
) -> tuple[pd.DataFrame, list[str], list[dict[str, Any]]]:
    rules = load_candidate_rules(
        diagnostic_paths,
        top_n=top_n,
        include_rule=None,
        min_source_count=min_diagnostic_sources,
    )
    frames = []
    summaries: list[dict[str, Any]] = []
    for path in market_candidate_paths:
        frame = pd.read_csv(path)
        for rule in rules:
            selected = frame[_matches_rule(frame, rule)].copy()
            if selected.empty:
                continue
            selected["rule_label"] = rule
            selected["stake"] = 1.0
            selected["profit"] = selected["unit_profit"].astype(float)
            selected["candidate_id"] = "direct-diagnostic-rule-pool"
            frames.append(selected[[
                "date",
                "league",
                "home_team",
                "away_team",
                "outcome",
                "actual_result",
                "odds",
                "odds_bucket",
                "market_prob_bucket",
                "favorite_relation",
                "stake",
                "won",
                "profit",
                "rule_label",
                "month",
                "candidate_id",
                "odds_source",
            ]])
            staked = float(len(selected))
            profit = float(selected["unit_profit"].sum())
            summaries.append({
                "market_candidates": str(path),
                "rule": rule,
                "odds_source": str(selected["odds_source"].iloc[0]),
                "bets": int(len(selected)),
                "profit": round(profit, 2),
                "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
                "active_months": int(selected["month"].nunique()),
            })
    unit_bets = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not unit_bets.empty:
        unit_bets = unit_bets.drop_duplicates([
            "date",
            "league",
            "home_team",
            "away_team",
            "outcome",
            "odds_source",
            "rule_label",
        ]).sort_values(["date", "odds_source", "rule_label"]).reset_index(drop=True)
    return unit_bets, rules, summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-candidates", type=Path, action="append", required=True)
    parser.add_argument("--diagnostics-csv", type=Path, action="append", required=True)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--min-diagnostic-sources", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/direct_rule_unit_bets"))
    args = parser.parse_args()
    unit_bets, rules, summaries = build_unit_bets(
        args.market_candidates,
        args.diagnostics_csv,
        top_n=args.top_n,
        min_diagnostic_sources=args.min_diagnostic_sources,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    unit_bets.to_csv(args.output_dir / "unit_bets.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summaries).to_csv(args.output_dir / "rule_summaries.csv", index=False, encoding="utf-8-sig")
    summary = {
        "method": "direct diagnostic rule unit bet builder",
        "rules": rules,
        "rule_count": len(rules),
        "unit_bets": int(len(unit_bets)),
        "notes": [
            "This builds a research rule pool from diagnostic CSVs. Use downstream walk-forward windows for validation.",
        ],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
