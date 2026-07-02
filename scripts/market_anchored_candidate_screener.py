from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import DEFAULT_SEASONS, load_seasons  # noqa: E402
from feature_enriched_candidate_filter import (  # noqa: E402
    FeatureFilterConfig,
    _prepare_candidate_features,
    walk_forward_feature_filter,
)
from market_bias_diagnostics import ODDS_SOURCE_COLUMNS, build_market_frame  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402
from walk_forward_residual_strategy import build_feature_history  # noqa: E402


def _parse_rule(columns: str, key: str) -> dict[str, str]:
    names = [item.strip() for item in str(columns).split("|") if item.strip()]
    values = [item.strip() for item in str(key).split("|")]
    return dict(zip(names, values, strict=False)) if len(names) == len(values) else {}


def _rule_label(rule: dict[str, str]) -> str:
    parts = [f"{key}={value}" for key, value in sorted(rule.items())]
    return "rule_" + "_".join(parts).replace("[", "").replace("]", "").replace(")", "").replace(",", "_").replace(".", "p").replace("|", "_").replace("=", "_").replace(" ", "")


def _matches_rule(frame: pd.DataFrame, rule: dict[str, str]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, value in rule.items():
        if column not in frame.columns:
            return pd.Series(False, index=frame.index)
        mask &= frame[column].astype(str) == str(value)
    return mask


def load_candidate_rules(paths: list[Path], top_n: int, min_bets: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        for _, row in frame.iterrows():
            key = (str(row.get("columns")), str(row.get("key")))
            if key in seen:
                continue
            seen.add(key)
            if int(row.get("bets") or 0) < min_bets:
                continue
            rule = _parse_rule(str(row.get("columns")), str(row.get("key")))
            if not rule:
                continue
            rows.append({
                "source": str(path),
                "columns": str(row.get("columns")),
                "key": str(row.get("key")),
                "rule": rule,
                "discovery_bets": int(row.get("bets") or 0),
                "discovery_profit": float(row.get("profit") or 0),
                "discovery_roi_pct": float(row.get("roi_pct") or 0),
                "discovery_score": float(row.get("score") or 0),
            })
    rows.sort(key=lambda item: (item["discovery_score"], item["discovery_profit"], item["discovery_bets"]), reverse=True)
    return rows[:top_n]


def build_rule_candidates(seasons: tuple[str, ...], odds_source: str,
                          rule_info: dict[str, Any],
                          feature_history: pd.DataFrame | None = None) -> pd.DataFrame:
    market = build_market_frame(seasons, odds_source)
    if market.empty:
        return pd.DataFrame()
    features = feature_history.copy() if feature_history is not None else build_feature_history(load_seasons(seasons))
    features = features.rename(columns={"match_date": "feature_date"}).copy()
    features["date"] = pd.to_datetime(features["feature_date"]).dt.strftime("%Y-%m-%d")
    join_columns = ["date", "league", "home_team", "away_team"]
    feature_columns = [
        "league_prior_matches",
        "league_draw_rate",
        "form_points_diff",
        "form_goal_diff_delta",
        "season_points_per_match_delta",
        "season_goal_diff_per_match_delta",
        "rest_days_delta",
        "lambda_total",
        "lambda_diff",
    ]
    selected = market[_matches_rule(market, rule_info["rule"])].copy()
    if selected.empty:
        return selected
    selected["rule_label"] = _rule_label(rule_info["rule"])
    selected = selected.merge(
        features[join_columns + feature_columns],
        on=join_columns,
        how="inner",
        validate="many_to_one",
    )
    selected["bet_date"] = pd.to_datetime(selected["date"])
    selected["month"] = selected["bet_date"].dt.to_period("M").astype(str)
    selected["season"] = selected["bet_date"].dt.year.astype(str)
    selected["unit_profit"] = selected["odds"].astype(float).where(selected["won"], 0.0) - 1.0
    return _prepare_candidate_features(selected).sort_values(["bet_date", "rule_label"]).reset_index(drop=True)


def _decision_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row["bets"] < 150:
        reasons.append("bets<150")
    if row["profit"] <= 0 or row["roi_pct"] <= 0:
        reasons.append("profit_or_roi<=0")
    if row["positive_months"] <= row["negative_months"]:
        reasons.append("positive_months<=negative_months")
    if row["max_drawdown"] > row["profit"]:
        reasons.append("max_drawdown>profit")
    if row["active_pass_rate"] < 0.6:
        reasons.append("active_pass_rate<0.6")
    return reasons


def run_market_anchored_candidate_screen(
    diagnostics_csv: list[Path],
    seasons: tuple[str, ...] = DEFAULT_SEASONS,
    odds_source: str = "AVG_OPEN",
    first_month: str = "2022-08",
    last_month: str = "2026-05",
    top_n: int = 20,
    min_discovery_bets: int = 150,
) -> dict[str, Any]:
    if odds_source not in ODDS_SOURCE_COLUMNS:
        raise ValueError(f"Unknown odds source: {odds_source}")
    rules = load_candidate_rules(diagnostics_csv, top_n, min_discovery_bets)
    feature_history = build_feature_history(load_seasons(seasons))
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, pd.DataFrame]] = {}
    for rule in rules:
        candidates = build_rule_candidates(seasons, odds_source, rule, feature_history)
        label = _rule_label(rule["rule"])
        if candidates.empty:
            rows.append({**rule, "label": label, "decision": "REJECT_NO_CANDIDATES", "candidate_count": 0})
            continue
        configs = [
            FeatureFilterConfig(odds_source, train_months, min_rows, min_ev, 1, ridge, 0.08, (label,))
            for train_months in (18, 30)
            for min_rows in (80, 120)
            for min_ev in (0.0, 0.02)
            for ridge in (10.0, 35.0)
        ]
        for config in configs:
            wf_summary, selected = walk_forward_feature_filter(candidates, config, first_month, last_month)
            portfolio, daily, bets = simulate_settlement_portfolio(selected, daily_limit=100.0, max_single_stake=10.0)
            windows = _window_rows(bets, first_month, last_month)
            window_summary = _summarize_windows(windows)
            overall = portfolio["overall"]
            result = {
                "source": rule["source"],
                "columns": rule["columns"],
                "key": rule["key"],
                "label": config.label,
                "rule_label": label,
                "odds_source": odds_source,
                "candidate_count": int(len(candidates)),
                "selected_candidates": int(len(selected)),
                "train_months": config.train_months,
                "min_train_rows": config.min_train_rows,
                "min_predicted_ev": config.min_predicted_ev,
                "ridge": config.ridge,
                "discovery_bets": rule["discovery_bets"],
                "discovery_profit": rule["discovery_profit"],
                "discovery_roi_pct": rule["discovery_roi_pct"],
                "bets": int(overall["bets"]),
                "profit": float(overall["profit"]),
                "roi_pct": float(overall["roi_pct"]),
                "max_drawdown": float(overall["max_drawdown"]),
                "positive_months": int(portfolio.get("positive_months") or 0),
                "negative_months": int(portfolio.get("negative_months") or 0),
                **window_summary,
            }
            result["decision_reasons"] = _decision_reasons(result)
            result["decision"] = "RESEARCH_CANDIDATE_NEEDS_AUDIT" if not result["decision_reasons"] else "REJECT_RESEARCH_GATES"
            rows.append(result)
            artifacts[config.label] = {
                "selected": selected,
                "daily": daily,
                "bets": bets,
                "windows": pd.DataFrame(windows),
                "month_reports": pd.DataFrame(wf_summary["months"]),
            }
    rows.sort(key=lambda row: (
        row.get("decision") == "RESEARCH_CANDIDATE_NEEDS_AUDIT",
        row.get("active_pass_rate", 0),
        row.get("roi_pct", -999),
        row.get("profit", -999),
        row.get("bets", 0),
    ), reverse=True)
    return {
        "method": "market-bias candidates screened by market-anchored residual model",
        "diagnostics_csv": [str(path) for path in diagnostics_csv],
        "seasons": seasons,
        "odds_source": odds_source,
        "first_month": first_month,
        "last_month": last_month,
        "rules_loaded": len(rules),
        "configs_tested": len(rows),
        "passed_configs": sum(1 for row in rows if row.get("decision") == "RESEARCH_CANDIDATE_NEEDS_AUDIT"),
        "results": rows,
        "top": rows[:20],
        "best_label": rows[0].get("label") if rows else None,
        "artifacts": artifacts,
        "guardrail": "Passing here is research-only; run statistical audit, edge calibration, and official-SP validation before promotion.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen market-bias discovery candidates with a no-leak market-anchored residual model.")
    parser.add_argument("--diagnostics-csv", action="append", type=Path, default=[Path("reports/market_bias_diagnostics_v1/market_bias.csv")])
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--odds-source", default="AVG_OPEN")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--min-discovery-bets", type=int, default=150)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_anchored_candidate_screener"))
    args = parser.parse_args()
    report = run_market_anchored_candidate_screen(
        args.diagnostics_csv,
        tuple(item.strip() for item in args.seasons.split(",") if item.strip()),
        args.odds_source,
        args.first_month,
        args.last_month,
        args.top_n,
        args.min_discovery_bets,
    )
    artifacts = report.pop("artifacts")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report["results"]).to_csv(args.output_dir / "grid_results.csv", index=False, encoding="utf-8-sig")
    if report.get("best_label") and report["best_label"] in artifacts:
        for name, frame in artifacts[report["best_label"]].items():
            frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
