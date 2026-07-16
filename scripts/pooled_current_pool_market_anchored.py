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

from cross_league_rule_search import load_seasons  # noqa: E402
from feature_enriched_candidate_filter import (  # noqa: E402
    FeatureFilterConfig,
    assess_feature_filter_row,
    season_summary_from_bets,
    walk_forward_feature_filter,
)
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from official_pool_market_anchored_research import (  # noqa: E402
    AnchoredRuleSpec,
    build_anchored_spec_candidates,
)
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402
from walk_forward_residual_strategy import build_feature_history  # noqa: E402


def pooled_config(odds_source: str, leagues: tuple[str, ...]) -> FeatureFilterConfig:
    return FeatureFilterConfig(
        odds_source=odds_source,
        train_months=30,
        min_train_rows=360,
        min_predicted_ev=0.02,
        max_bets_per_day=1,
        ridge=10.0,
        residual_cap=0.03,
        selected_rules=leagues,
        validation_months=6,
        min_validation_rows=360,
        require_probability_improvement=True,
        min_odds=1.8,
        max_odds=4.0,
        min_validation_selections=30,
        require_validation_tail_edge=True,
    )


def run_pooled_research(
    leagues: tuple[str, ...],
    odds_source: str,
    first_month: str,
    last_month: str,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    matches = load_seasons(leagues)
    features = build_feature_history(matches)
    specs = tuple(AnchoredRuleSpec(league) for league in leagues)
    candidates = build_anchored_spec_candidates(leagues, odds_source, specs, features)
    config = pooled_config(odds_source, leagues)
    wf_summary, selected = walk_forward_feature_filter(candidates, config, first_month, last_month)
    portfolio, daily, bets = simulate_settlement_portfolio(
        selected,
        daily_limit=100.0,
        max_single_stake=10.0,
    )
    windows = _window_rows(bets, first_month, last_month)
    window_summary = _summarize_windows(windows)
    seasons = season_summary_from_bets(bets)
    latest = seasons[-1] if seasons else {}
    overall = portfolio["overall"]
    row = {
        "leagues": list(leagues),
        "odds_source": odds_source,
        "label": config.label,
        "candidate_count": int(len(candidates)),
        "selected_candidates": int(len(selected)),
        "bets": int(overall["bets"]),
        "profit": float(overall["profit"]),
        "roi_pct": float(overall["roi_pct"]),
        "max_drawdown": float(overall["max_drawdown"]),
        "positive_months": int(portfolio.get("positive_months") or 0),
        "negative_months": int(portfolio.get("negative_months") or 0),
        "positive_seasons": sum(float(item["profit"]) > 0 for item in seasons),
        "negative_seasons": sum(float(item["profit"]) < 0 for item in seasons),
        "latest_season": latest.get("season"),
        "latest_season_bets": int(latest.get("bets") or 0),
        "latest_season_profit": float(latest.get("profit") or 0.0),
        **window_summary,
    }
    verdict, reasons = assess_feature_filter_row(row, min_bets=200, min_active_pass_rate=0.60)
    row["decision"] = verdict
    row["decision_reasons"] = reasons
    report = {
        "method": "pooled current-pool market-anchored residual no-lookahead research",
        "first_month": first_month,
        "last_month": last_month,
        "config": config.__dict__,
        "result": row,
        "guardrail": (
            "This is representative historical market evidence. Promotion still requires an independent price "
            "source, statistical audit, calibration, and prospective official-SP validation."
        ),
    }
    artifacts = {
        "selected": selected,
        "daily": daily,
        "bets": bets,
        "windows": pd.DataFrame(windows),
        "month_reports": pd.DataFrame(wf_summary["months"]),
    }
    return report, artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a pooled no-lookahead residual model for current-pool leagues.")
    parser.add_argument("--leagues", default="USA,NOR,BRA")
    parser.add_argument("--odds-source", choices=("AVG_CLOSE", "PS_CLOSE"), required=True)
    parser.add_argument("--first-month", default="2017-01")
    parser.add_argument("--last-month", default="2025-12")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    leagues = tuple(item.strip().upper() for item in args.leagues.split(",") if item.strip())
    report, artifacts = run_pooled_research(leagues, args.odds_source, args.first_month, args.last_month)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in artifacts.items():
        frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
