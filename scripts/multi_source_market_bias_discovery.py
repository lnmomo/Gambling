from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import DEFAULT_SEASONS  # noqa: E402
from market_bias_diagnostics import ODDS_SOURCE_COLUMNS, build_market_frame, run_diagnostics  # noqa: E402


DEFAULT_DISCOVERY_SOURCES = (
    "B365_OPEN",
    "AVG_OPEN",
    "MAX_OPEN",
    "B365_CLOSE",
    "AVG_CLOSE",
    "MAX_CLOSE",
)


def _rule_id(row: pd.Series) -> str:
    return f"{row['columns']}={row['key']}"


def aggregate_source_diagnostics(
    diagnostics: pd.DataFrame,
    *,
    min_sources: int,
    min_source_roi_pct: float,
    require_positive_latest: bool,
) -> pd.DataFrame:
    if diagnostics.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    frame = diagnostics.copy()
    frame["rule"] = frame.apply(_rule_id, axis=1)
    for rule, group in frame.groupby("rule"):
        source_count = int(group["odds_source"].nunique())
        passing = group[
            (group["profit"].astype(float) > 0)
            & (group["roi_pct"].astype(float) >= min_source_roi_pct)
            & (group["positive_months"].astype(int) > group["negative_months"].astype(int))
        ]
        if require_positive_latest:
            passing = passing[passing["latest_profit"].astype(float) >= 0]
        passing_sources = int(passing["odds_source"].nunique())
        if passing_sources < min_sources:
            continue

        total_bets = int(group["bets"].sum())
        total_profit = float(group["profit"].sum())
        total_roi = total_profit / total_bets * 100 if total_bets else 0.0
        worst_roi = float(group["roi_pct"].min())
        min_latest_profit = float(group["latest_profit"].min())
        min_active_months = int(group["active_months"].min())
        positive_source_month_edge = int((group["positive_months"] - group["negative_months"]).min())
        first = group.iloc[0]
        source_results = group.sort_values("odds_source")[
            [
                "odds_source",
                "bets",
                "profit",
                "roi_pct",
                "active_months",
                "positive_months",
                "negative_months",
                "latest_month",
                "latest_profit",
            ]
        ].to_dict(orient="records")
        rows.append({
            "columns": first["columns"],
            "key": first["key"],
            "rule": rule,
            "source_count": source_count,
            "passing_sources": passing_sources,
            "bets": total_bets,
            "profit": round(total_profit, 2),
            "roi_pct": round(total_roi, 2),
            "worst_source_roi_pct": round(worst_roi, 2),
            "min_latest_profit": round(min_latest_profit, 2),
            "active_months": min_active_months,
            "positive_months": int(group["positive_months"].sum()),
            "negative_months": int(group["negative_months"].sum()),
            "latest_month": str(group["latest_month"].max()),
            "latest_profit": round(min_latest_profit, 2),
            "score": round(
                passing_sources * 100
                + source_count * 10
                + total_roi
                + max(positive_source_month_edge, 0) * 2
                + total_profit / max(total_bets, 1),
                4,
            ),
            "source_results": source_results,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        [
            "passing_sources",
            "source_count",
            "worst_source_roi_pct",
            "roi_pct",
            "profit",
            "bets",
        ],
        ascending=[False, False, False, False, False, False],
    ).reset_index(drop=True)


def discover_multi_source_bias(
    *,
    seasons: tuple[str, ...],
    odds_sources: tuple[str, ...],
    min_samples: int,
    min_active_months: int,
    max_combo_size: int,
    min_sources: int,
    min_source_roi_pct: float,
    require_positive_latest: bool,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    source_frames: list[pd.DataFrame] = []
    diagnostic_frames: list[pd.DataFrame] = []
    source_summaries: list[dict[str, Any]] = []
    for odds_source in odds_sources:
        frame = build_market_frame(seasons, odds_source)
        source_frames.append(frame)
        diagnostics = run_diagnostics(frame, min_samples, min_active_months, max_combo_size)
        if not diagnostics.empty:
            diagnostics = diagnostics.assign(odds_source=odds_source)
            diagnostic_frames.append(diagnostics)
        source_summaries.append({
            "odds_source": odds_source,
            "candidate_count": int(len(frame)),
            "diagnostic_rows": int(len(diagnostics)),
        })

    all_diagnostics = (
        pd.concat(diagnostic_frames, ignore_index=True)
        if diagnostic_frames
        else pd.DataFrame()
    )
    robust = aggregate_source_diagnostics(
        all_diagnostics,
        min_sources=min_sources,
        min_source_roi_pct=min_source_roi_pct,
        require_positive_latest=require_positive_latest,
    )
    market_candidates = (
        pd.concat(source_frames, ignore_index=True)
        if source_frames
        else pd.DataFrame()
    )
    summary = {
        "method": "multi-source market-bias discovery",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seasons": seasons,
        "odds_sources": odds_sources,
        "min_samples": min_samples,
        "min_active_months": min_active_months,
        "max_combo_size": max_combo_size,
        "min_sources": min_sources,
        "min_source_roi_pct": min_source_roi_pct,
        "require_positive_latest": require_positive_latest,
        "source_summaries": source_summaries,
        "raw_diagnostic_rows": int(len(all_diagnostics)),
        "robust_diagnostic_rows": int(len(robust)),
        "top": robust.head(30).drop(columns=["source_results"], errors="ignore").to_dict(orient="records")
        if not robust.empty
        else [],
        "interpretation": (
            "Rules found here are still discovery candidates. They must pass no-lookahead walk-forward, "
            "cross-source settlement-aware portfolio simulation, and official-SP prospective validation before allocation."
        ),
    }
    return summary, market_candidates, robust


def main() -> None:
    parser = argparse.ArgumentParser(description="Find market-bias rules that appear across multiple odds sources.")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--odds-source", action="append", choices=tuple(ODDS_SOURCE_COLUMNS))
    parser.add_argument("--min-samples", type=int, default=150)
    parser.add_argument("--min-active-months", type=int, default=18)
    parser.add_argument("--max-combo-size", type=int, default=3)
    parser.add_argument("--min-sources", type=int, default=3)
    parser.add_argument("--min-source-roi-pct", type=float, default=3.0)
    parser.add_argument("--allow-negative-latest", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/multi_source_market_bias_discovery"))
    args = parser.parse_args()

    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    odds_sources = tuple(args.odds_source or DEFAULT_DISCOVERY_SOURCES)
    summary, market_candidates, robust = discover_multi_source_bias(
        seasons=seasons,
        odds_sources=odds_sources,
        min_samples=args.min_samples,
        min_active_months=args.min_active_months,
        max_combo_size=args.max_combo_size,
        min_sources=args.min_sources,
        min_source_roi_pct=args.min_source_roi_pct,
        require_positive_latest=not args.allow_negative_latest,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    market_candidates.to_csv(args.output_dir / "market_candidates.csv", index=False, encoding="utf-8-sig")
    robust.drop(columns=["source_results"], errors="ignore").to_csv(
        args.output_dir / "market_bias.csv",
        index=False,
        encoding="utf-8-sig",
    )
    robust.to_json(
        args.output_dir / "market_bias_with_sources.json",
        orient="records",
        force_ascii=False,
        indent=2,
    )
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
