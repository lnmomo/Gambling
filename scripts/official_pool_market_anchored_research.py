from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import load_seasons  # noqa: E402
from feature_enriched_candidate_filter import (  # noqa: E402
    FeatureFilterConfig,
    _prepare_candidate_features,
    assess_feature_filter_row,
    season_summary_from_bets,
    walk_forward_feature_filter,
)
from market_bias_diagnostics import ODDS_SOURCE_COLUMNS, build_market_frame  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402
from walk_forward_residual_strategy import build_feature_history  # noqa: E402


@dataclass(frozen=True)
class AnchoredRuleSpec:
    league: str
    outcome: str | None = None
    odds_bucket: str | None = None
    market_prob_bucket: str | None = None
    favorite_relation: str | None = None

    @property
    def label(self) -> str:
        parts = [self.league]
        if self.outcome:
            parts.append(self.outcome)
        if self.odds_bucket:
            parts.append("odds" + self.odds_bucket.replace("[", "").replace(")", "").replace(",", "_").replace(".", "p"))
        if self.market_prob_bucket:
            parts.append("prob" + self.market_prob_bucket.replace("[", "").replace("]", "").replace(")", "").replace(",", "_").replace(".", "p"))
        if self.favorite_relation:
            parts.append(self.favorite_relation)
        return "_".join(parts).replace("inf", "max")


def _matches_spec(row: pd.Series, spec: AnchoredRuleSpec) -> bool:
    if str(row.get("league")) != spec.league:
        return False
    for column in ("outcome", "odds_bucket", "market_prob_bucket", "favorite_relation"):
        expected = getattr(spec, column)
        if expected is not None and str(row.get(column)) != expected:
            return False
    return True


def build_anchored_spec_candidates(
    seasons: tuple[str, ...],
    odds_source: str,
    specs: tuple[AnchoredRuleSpec, ...],
    feature_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
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
    candidates = market.copy()
    labels: list[str | None] = []
    for _, row in candidates.iterrows():
        matched = next((spec for spec in specs if _matches_spec(row, spec)), None)
        labels.append(matched.label if matched else None)
    candidates["rule_label"] = labels
    candidates = candidates[candidates["rule_label"].notna()].copy()
    if candidates.empty:
        return candidates
    candidates = candidates.merge(
        features[join_columns + feature_columns],
        on=join_columns,
        how="inner",
        validate="many_to_one",
    )
    candidates["bet_date"] = pd.to_datetime(candidates["date"])
    candidates["month"] = candidates["bet_date"].dt.to_period("M").astype(str)
    candidates["season"] = candidates["bet_date"].dt.year.astype(str)
    candidates["unit_profit"] = candidates["odds"].astype(float).where(candidates["won"], 0.0) - 1.0
    return _prepare_candidate_features(candidates).sort_values(["bet_date", "rule_label"]).reset_index(drop=True)


def _default_specs_for_league(league: str) -> tuple[AnchoredRuleSpec, ...]:
    if league == "FIN":
        return (
            AnchoredRuleSpec("FIN", "away", market_prob_bucket="[0.28,0.34)"),
            AnchoredRuleSpec("FIN", "away", odds_bucket="[2.8,3.5)"),
            AnchoredRuleSpec("FIN", "draw", odds_bucket="[2.8,3.5)"),
            AnchoredRuleSpec("FIN", "home", market_prob_bucket="[0.55,1.00]"),
        )
    if league == "SWE":
        return (
            AnchoredRuleSpec("SWE", "away", odds_bucket="[2.2,2.8)"),
            AnchoredRuleSpec("SWE", "away", market_prob_bucket="[0.28,0.34)"),
            AnchoredRuleSpec("SWE", "draw", odds_bucket="[2.8,3.5)"),
            AnchoredRuleSpec("SWE", "home", market_prob_bucket="[0.55,1.00]"),
        )
    if league == "WORLD_CUP":
        return (
            AnchoredRuleSpec("WORLD_CUP", None, odds_bucket="[4.0,5.0)"),
            AnchoredRuleSpec("WORLD_CUP", "home", market_prob_bucket="[0.00,0.20)"),
            AnchoredRuleSpec("WORLD_CUP", "draw", odds_bucket="[4.0,5.0)"),
        )
    if league == "RUS":
        return (
            AnchoredRuleSpec("RUS", "home", odds_bucket="[2.2,2.8)"),
            AnchoredRuleSpec("RUS", "home", odds_bucket="[2.2,2.8)", favorite_relation="market_favorite"),
            AnchoredRuleSpec("RUS", "away", odds_bucket="[1.0,1.8)"),
            AnchoredRuleSpec("RUS", None, odds_bucket="[1.0,1.8)", market_prob_bucket="[0.42,0.55)"),
        )
    if league == "DNK":
        return (
            AnchoredRuleSpec("DNK", "draw", odds_bucket="[2.8,3.5)"),
            AnchoredRuleSpec("DNK", None, odds_bucket="[2.8,3.5)", market_prob_bucket="[0.20,0.28)"),
            AnchoredRuleSpec("DNK", "away", odds_bucket="[2.2,2.8)", favorite_relation="market_favorite"),
        )
    if league == "CHN":
        return (
            AnchoredRuleSpec("CHN", "draw", market_prob_bucket="[0.28,0.34)"),
            AnchoredRuleSpec("CHN", "draw", odds_bucket="[2.8,3.5)", market_prob_bucket="[0.28,0.34)"),
            AnchoredRuleSpec("CHN", "draw", odds_bucket="[2.8,3.5)"),
        )
    return ()


def _config_grid(odds_source: str, labels: tuple[str, ...], fast: bool = False) -> list[FeatureFilterConfig]:
    configs: list[FeatureFilterConfig] = []
    train_month_values = (30,) if fast else (18, 30)
    min_row_values = (120,) if fast else (80, 120)
    min_ev_values = (0.02,) if fast else (0.0, 0.02)
    ridge_values = (10.0,) if fast else (10.0, 35.0)
    for label, train_months, min_rows, min_ev, ridge in itertools.product(
        labels,
        train_month_values,
        min_row_values,
        min_ev_values,
        ridge_values,
    ):
        configs.append(FeatureFilterConfig(
            odds_source=odds_source,
            train_months=train_months,
            min_train_rows=min_rows,
            min_predicted_ev=min_ev,
            max_bets_per_day=1,
            ridge=ridge,
            residual_cap=0.08,
            selected_rules=(label,),
        ))
    return configs


def _decision_reasons(row: dict[str, Any]) -> list[str]:
    _, reasons = assess_feature_filter_row(row, min_bets=150, min_active_pass_rate=0.60)
    return reasons


def _decision(row: dict[str, Any]) -> str:
    return "SHADOW_READY_RESEARCH_CANDIDATE" if not _decision_reasons(row) else "REJECT_RESEARCH_GATES"


def run_official_pool_market_anchored_research(
    leagues: tuple[str, ...] = ("FIN", "SWE", "WORLD_CUP"),
    odds_sources: tuple[str, ...] = ("AVG_OPEN", "AVG_CLOSE"),
    first_month: str = "2020-01",
    last_month: str = "2025-12",
    fast: bool = False,
    rule_labels: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    artifact_frames: dict[str, dict[str, pd.DataFrame]] = {}
    allowed_labels = set(rule_labels or ())
    for league in leagues:
        specs = _default_specs_for_league(league)
        if not specs:
            results.append({
                "league": league,
                "decision": "SKIP_NO_PREDECLARED_RULE_SPECS",
                "reason": "No official-pool-driven anchored specs are defined for this league.",
            })
            continue
        try:
            feature_history = build_feature_history(load_seasons((league,)))
        except Exception as exc:
            results.append({"league": league, "decision": "SKIP_DATA_LOAD_FAILED", "error": str(exc)})
            continue
        for odds_source in odds_sources:
            if odds_source not in ODDS_SOURCE_COLUMNS:
                results.append({"league": league, "odds_source": odds_source, "decision": "SKIP_UNKNOWN_ODDS_SOURCE"})
                continue
            candidates = build_anchored_spec_candidates((league,), odds_source, specs, feature_history)
            if candidates.empty:
                results.append({
                    "league": league,
                    "odds_source": odds_source,
                    "decision": "REJECT_NO_CANDIDATES",
                    "candidate_count": 0,
                })
                continue
            labels = tuple(sorted(candidates["rule_label"].astype(str).unique()))
            if allowed_labels:
                labels = tuple(label for label in labels if label in allowed_labels)
                candidates = candidates[candidates["rule_label"].isin(labels)].copy()
            if not labels:
                results.append({
                    "league": league,
                    "odds_source": odds_source,
                    "decision": "SKIP_NO_MATCHING_RULE_LABELS",
                    "candidate_count": 0,
                    "requested_rule_labels": sorted(allowed_labels),
                })
                continue
            for config in _config_grid(odds_source, labels, fast=fast):
                wf_summary, selected = walk_forward_feature_filter(candidates, config, first_month, last_month)
                portfolio, daily, bets = simulate_settlement_portfolio(selected, daily_limit=100.0, max_single_stake=10.0)
                windows = _window_rows(bets, first_month, last_month)
                window_summary = _summarize_windows(windows)
                overall = portfolio["overall"]
                season_rows = season_summary_from_bets(bets)
                latest_season = season_rows[-1] if season_rows else {}
                row = {
                    "league": league,
                    "odds_source": odds_source,
                    "rule_spec": config.selected_rules[0],
                    "label": config.label,
                    "candidate_count": int(len(candidates[candidates["rule_label"] == config.selected_rules[0]])),
                    "selected_candidates": int(len(selected)),
                    "train_months": config.train_months,
                    "min_train_rows": config.min_train_rows,
                    "min_predicted_ev": config.min_predicted_ev,
                    "ridge": config.ridge,
                    "bets": int(overall["bets"]),
                    "profit": float(overall["profit"]),
                    "roi_pct": float(overall["roi_pct"]),
                    "max_drawdown": float(overall["max_drawdown"]),
                    "positive_months": int(portfolio.get("positive_months") or 0),
                    "negative_months": int(portfolio.get("negative_months") or 0),
                    "positive_seasons": sum(float(item["profit"]) > 0 for item in season_rows),
                    "negative_seasons": sum(float(item["profit"]) < 0 for item in season_rows),
                    "latest_season": latest_season.get("season"),
                    "latest_season_bets": int(latest_season.get("bets") or 0),
                    "latest_season_profit": float(latest_season.get("profit") or 0.0),
                    **window_summary,
                }
                row["decision_reasons"] = _decision_reasons(row)
                row["decision"] = _decision(row)
                results.append(row)
                artifact_frames[row["label"]] = {
                    "selected": selected,
                    "daily": daily,
                    "bets": bets,
                    "month_reports": pd.DataFrame(wf_summary["months"]),
                    "windows": pd.DataFrame(windows),
                }
    ranked = sorted(
        results,
        key=lambda row: (
            row.get("decision") == "SHADOW_READY_RESEARCH_CANDIDATE",
            row.get("active_pass_rate", 0),
            row.get("roi_pct", -999),
            row.get("profit", -999),
            row.get("bets", 0),
        ),
        reverse=True,
    )
    return {
        "method": "official-pool-driven market-anchored residual research",
        "leagues": leagues,
        "odds_sources": odds_sources,
        "first_month": first_month,
        "last_month": last_month,
        "fast": fast,
        "rule_labels": list(rule_labels or ()),
        "results": ranked,
        "top": ranked[:20],
        "best_label": ranked[0].get("label") if ranked and "label" in ranked[0] else None,
        "artifacts": artifact_frames,
        "guardrail": "A candidate marked SHADOW_READY_RESEARCH_CANDIDATE still needs statistical audit, edge calibration, and official-SP prospective validation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Research market-anchored residual candidates for leagues present in the official pool.")
    parser.add_argument("--leagues", default="FIN,SWE,WORLD_CUP")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--first-month", default="2020-01")
    parser.add_argument("--last-month", default="2025-12")
    parser.add_argument("--fast", action="store_true", help="Run one representative formal config per rule.")
    parser.add_argument("--rule-labels", default="", help="Optional comma-separated rule labels to evaluate.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/official_pool_market_anchored_research"))
    args = parser.parse_args()
    rule_labels = tuple(item.strip() for item in args.rule_labels.split(",") if item.strip())
    report = run_official_pool_market_anchored_research(
        tuple(item.strip().upper() for item in args.leagues.split(",") if item.strip()),
        tuple(item.strip().upper() for item in args.odds_sources.split(",") if item.strip()),
        args.first_month,
        args.last_month,
        args.fast,
        rule_labels or None,
    )
    artifacts = report.pop("artifacts")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report["results"]).to_csv(args.output_dir / "grid_results.csv", index=False, encoding="utf-8-sig")
    if report.get("best_label"):
        for name, frame in artifacts[report["best_label"]].items():
            frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
