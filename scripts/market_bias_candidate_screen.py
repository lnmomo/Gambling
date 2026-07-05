from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from market_bias_robustness_gate import DEFAULT_RULE, GateProfile  # noqa: E402
from market_bias_walk_forward import _parse_rule, run_walk_forward_frame  # noqa: E402


def _rule_label(columns: str, key: str) -> str:
    return f"{columns}={key}"


def _is_specific_enough(columns: str) -> bool:
    parts = set(columns.split("|"))
    return "league" in parts and ("outcome" in parts or "odds_bucket" in parts or "market_prob_bucket" in parts)


def _diagnostic_paths(path: Path | list[Path] | tuple[Path, ...]) -> list[Path]:
    if isinstance(path, Path):
        return [path]
    return list(path)


def load_candidate_rules(path: Path | list[Path] | tuple[Path, ...], top_n: int,
                         include_rule: str | None = DEFAULT_RULE,
                         min_source_count: int = 1) -> list[str]:
    rules: list[str] = []
    if include_rule:
        rules.append(include_rule)
    rows: list[dict[str, Any]] = []
    for diagnostic_path in _diagnostic_paths(path):
        try:
            frame = pd.read_csv(diagnostic_path)
        except EmptyDataError:
            continue
        for _, row in frame.iterrows():
            columns = str(row["columns"])
            key = str(row["key"])
            if not _is_specific_enough(columns):
                continue
            if float(row.get("latest_profit", 0) or 0) < 0:
                continue
            rows.append({
                "source": str(diagnostic_path),
                "rule": _rule_label(columns, key),
                "score": float(row.get("score", 0) or 0),
                "profit": float(row.get("profit", 0) or 0),
                "bets": int(row.get("bets", 0) or 0),
                "latest_profit": float(row.get("latest_profit", 0) or 0),
            })
    if not rows:
        return rules[:top_n]
    grouped_rows: list[dict[str, Any]] = []
    for rule, group in pd.DataFrame(rows).groupby("rule"):
        source_count = int(group["source"].nunique())
        if source_count < min_source_count:
            continue
        grouped_rows.append({
            "rule": rule,
            "source_count": source_count,
            "score": float(group["score"].mean()),
            "profit": float(group["profit"].sum()),
            "bets": int(group["bets"].sum()),
            "min_latest_profit": float(group["latest_profit"].min()),
        })
    grouped_rows.sort(key=lambda row: (
        row["source_count"],
        row["score"],
        row["profit"],
        row["bets"],
        row["min_latest_profit"],
    ), reverse=True)
    for row in grouped_rows:
        rule = row["rule"]
        if rule not in rules:
            rules.append(rule)
        if len(rules) >= top_n:
            break
    return rules


def _parse_rules(raw_rule: str) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    columns_raw, key_raw = raw_rule.split("=", 1)
    return [(_parse_rule(columns_raw), _parse_rule(key_raw))]


def _portfolio_passes(summary: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    overall = summary["overall"]
    if overall["bets"] < 100:
        reasons.append("bets<100")
    if overall["profit"] <= 0:
        reasons.append("profit<=0")
    if overall["roi_pct"] < 3.0:
        reasons.append("roi<3%")
    if summary.get("positive_months", 0) <= summary.get("negative_months", 0):
        reasons.append("positive_months<=negative_months")
    if summary.get("positive_seasons", 0) <= summary.get("negative_seasons", 0):
        reasons.append("positive_seasons<=negative_seasons")
    if overall["max_drawdown"] > max(overall["profit"], 1.0):
        reasons.append("drawdown>profit")
    return not reasons, reasons


def _summarize_rules(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    if not rows:
        return summaries
    for rule, group in pd.DataFrame(rows).groupby("rule"):
        source_count = int(group["odds_source"].nunique())
        pass_count = int(group["passes_screen"].sum())
        total_profit = float(group["portfolio_profit"].sum())
        total_staked = float(group["portfolio_staked"].sum())
        summaries.append({
            "rule": rule,
            "validation_source_count": source_count,
            "passed_validation_sources": pass_count,
            "failed_validation_sources": source_count - pass_count,
            "total_portfolio_bets": int(group["portfolio_bets"].sum()),
            "total_portfolio_staked": round(total_staked, 2),
            "total_portfolio_profit": round(total_profit, 2),
            "combined_roi_pct": round(total_profit / total_staked * 100, 2) if total_staked else 0.0,
            "worst_source_roi_pct": float(group["portfolio_roi_pct"].min()),
            "worst_source_drawdown": float(group["portfolio_max_drawdown"].max()),
            "source_results": group[[
                "odds_source", "passes_screen", "portfolio_bets", "portfolio_profit",
                "portfolio_roi_pct", "portfolio_max_drawdown", "fail_reasons",
            ]].to_dict(orient="records"),
            "passes_all_validation_sources": pass_count == source_count and source_count > 0,
        })
    summaries.sort(key=lambda row: (
        row["passes_all_validation_sources"],
        row["passed_validation_sources"],
        row["combined_roi_pct"],
        row["total_portfolio_profit"] - row["worst_source_drawdown"],
    ), reverse=True)
    return summaries


def screen_candidates(
    diagnostics_csv: Path | list[Path] | tuple[Path, ...],
    seasons: tuple[str, ...],
    first_month: str,
    last_month: str,
    odds_source: str | list[str] | tuple[str, ...],
    top_n: int,
    daily_limit: float,
    max_single_stake: float,
    min_diagnostic_sources: int = 1,
    include_rule: str | None = DEFAULT_RULE,
) -> dict[str, Any]:
    diagnostic_paths = _diagnostic_paths(diagnostics_csv)
    rules = load_candidate_rules(
        diagnostic_paths,
        top_n,
        include_rule=include_rule,
        min_source_count=min_diagnostic_sources,
    )
    profile = GateProfile("screen_default", 12, 6, 50, 0.02)
    validation_sources = (odds_source,) if isinstance(odds_source, str) else tuple(odds_source)
    rows: list[dict[str, Any]] = []
    for validation_source in validation_sources:
        frame = build_market_frame(seasons, validation_source)
        for rule in rules:
            wf_summary, _, unit_bets = run_walk_forward_frame(
                frame,
                seasons,
                first_month,
                last_month,
                _parse_rules(rule),
                profile.lookback_months,
                profile.min_active_months,
                profile.min_bets,
                profile.min_roi,
                profile.max_rules,
                daily_limit,
                validation_source,
            )
            portfolio, _, _ = simulate_settlement_portfolio(
                unit_bets,
                daily_limit=daily_limit,
                max_single_stake=max_single_stake,
                settlement_delay_days=1,
                stop_after_losing_settlement_days=999,
                cooldown_days=0,
            )
            passed, fail_reasons = _portfolio_passes(portfolio)
            overall = portfolio["overall"]
            rows.append({
                "rule": rule,
                "odds_source": validation_source,
                "walk_forward_bets": wf_summary["overall"]["bets"],
                "walk_forward_profit": wf_summary["overall"]["profit"],
                "walk_forward_roi_pct": wf_summary["overall"]["roi_pct"],
                "portfolio_bets": overall["bets"],
                "portfolio_staked": overall["total_staked"],
                "portfolio_profit": overall["profit"],
                "portfolio_roi_pct": overall["roi_pct"],
                "portfolio_max_drawdown": overall["max_drawdown"],
                "positive_months": portfolio.get("positive_months", 0),
                "negative_months": portfolio.get("negative_months", 0),
                "positive_seasons": portfolio.get("positive_seasons", 0),
                "negative_seasons": portfolio.get("negative_seasons", 0),
                "passes_screen": passed,
                "fail_reasons": fail_reasons,
            })
    rows.sort(key=lambda row: (
        row["passes_screen"],
        row["portfolio_roi_pct"],
        row["portfolio_profit"] - row["portfolio_max_drawdown"],
    ), reverse=True)
    return {
        "method": "market-bias candidate screen",
        "diagnostics_csv": [str(path) for path in diagnostic_paths],
        "min_diagnostic_sources": min_diagnostic_sources,
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "odds_source": validation_sources[0] if len(validation_sources) == 1 else ",".join(validation_sources),
        "validation_odds_sources": validation_sources,
        "top_n": top_n,
        "daily_limit": daily_limit,
        "max_single_stake": max_single_stake,
        "included_default_rule": include_rule == DEFAULT_RULE,
        "candidate_count": len(rows),
        "passed_count": sum(row["passes_screen"] for row in rows),
        "rule_summary": _summarize_rules(rows),
        "rows": rows,
        "next_step": "Run full multi-source robustness and official-SP shadow validation for passed candidates only.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics-csv", type=Path, action="append")
    parser.add_argument("--min-diagnostic-sources", type=int, default=1)
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-source", default="AVG_OPEN")
    parser.add_argument("--validation-odds-source", action="append")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--no-include-default-rule", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_candidate_screen"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    diagnostics_csv = args.diagnostics_csv or [Path("reports/market_bias_diagnostics_v1/market_bias.csv")]
    validation_sources = tuple(args.validation_odds_source or [args.odds_source])
    summary = screen_candidates(
        diagnostics_csv,
        seasons,
        args.first_month,
        args.last_month,
        validation_sources,
        args.top_n,
        args.daily_limit,
        args.max_single_stake,
        args.min_diagnostic_sources,
        None if args.no_include_default_rule else DEFAULT_RULE,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(summary["rows"]).to_csv(args.output_dir / "candidates.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
