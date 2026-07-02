from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import (  # noqa: E402
    DEFAULT_SEASONS,
    ResidualProbabilityModel,
    build_feature_history,
    load_seasons,
    metrics,
    month_candidates,
    monthly_summary,
    parse_odds_bucket_scope,
    portfolio_gate,
    rule_pool,
    select_rules,
    simulate_selected_rules,
    summarize_rule_month,
)


def parse_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in raw.split(",") if item.strip())


def run_consensus(first_month: str, last_month: str, seasons: tuple[str, ...],
                  training_windows: tuple[int, ...], primary_training_months: int,
                  min_consensus_windows: int, lookback_months: int,
                  min_active_months: int, min_bets: int, min_roi: float,
                  max_rules: int, min_league_matches: int, daily_limit: float,
                  ev_thresholds: tuple[float, ...], recent_active_months: int,
                  min_recent_roi: float, portfolio_gate_mode: str,
                  cooldown_months: int, lcb_z: float,
                  structure_modes: tuple[str, ...], outcome_scope: tuple[str, ...],
                  odds_bucket_scope: tuple[str, ...],
                  league_group_scope: tuple[str, ...]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    matches = load_seasons(seasons)
    features = build_feature_history(matches)
    rules = rule_pool(features, min_league_matches, ev_thresholds, structure_modes, outcome_scope, odds_bucket_scope, league_group_scope)
    rule_by_label = {rule.label: rule for rule in rules}
    min_ev = min(rule.min_lower_ev for rule in rules)
    max_odds = max(rule.max_odds for rule in rules)
    histories: dict[int, list[dict]] = {window: [] for window in training_windows}
    monthly: list[dict] = []
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []

    if primary_training_months not in training_windows:
        raise ValueError("primary_training_months must be included in training_windows")
    if min_consensus_windows > len(training_windows):
        raise ValueError("min_consensus_windows cannot exceed number of training windows")

    for period in pd.period_range(first_month, last_month, freq="M"):
        start, end = period.start_time.normalize(), period.end_time.normalize()
        test = features[(features.match_date >= start) & (features.match_date <= end)]
        if test.empty:
            monthly.append({"month": str(period), "decision": "ABSTAIN", "reason": "empty_test", "bets": 0, "total_staked": 0.0, "profit": 0.0, "roi_pct": 0.0})
            continue

        per_window: dict[int, dict] = {}
        selected_counter: Counter[str] = Counter()
        primary_predicted = pd.DataFrame()
        primary_candidates = pd.DataFrame()

        for window in training_windows:
            train = features[(features.match_date >= start - pd.DateOffset(months=window)) & (features.match_date < start)]
            if len(train) < 300:
                per_window[window] = {"decision": "ABSTAIN", "reason": "insufficient_train", "selected": []}
                continue
            predicted = ResidualProbabilityModel(uncertainty_scale=0.85).fit(train).predict(test.reset_index(drop=True))
            candidates = month_candidates(predicted, min_ev, max_odds)
            rule_results = {rule.label: summarize_rule_month(candidates, rule) for rule in rules}
            selected_rules, selection = select_rules(
                histories[window],
                rules,
                lookback_months,
                min_active_months,
                min_bets,
                min_roi,
                max_rules,
                recent_active_months,
                min_recent_roi,
                lcb_z,
            )
            selected_labels = [rule.label for rule in selected_rules]
            selected_counter.update(selected_labels)
            per_window[window] = {
                "decision": selection.get("decision"),
                "selected_labels": selected_labels,
                "selection": selection,
            }
            histories[window].append({"month": str(period), "rule_results": rule_results})
            if window == primary_training_months:
                primary_predicted = predicted
                primary_candidates = candidates

        consensus_labels = [
            label
            for label, count in selected_counter.most_common()
            if count >= min_consensus_windows
        ][:max_rules]
        consensus_rules = [rule_by_label[label] for label in consensus_labels]
        gate_enabled, gate_reason = portfolio_gate(monthly, portfolio_gate_mode, str(period), cooldown_months)
        if consensus_rules and gate_enabled and not primary_predicted.empty:
            days, bets = simulate_selected_rules(primary_predicted, primary_candidates, consensus_rules, daily_limit)
            decision = "INVEST"
        else:
            predicted_for_days = primary_predicted if not primary_predicted.empty else test.reset_index(drop=True)
            empty_candidates = primary_candidates.iloc[0:0] if not primary_candidates.empty else pd.DataFrame()
            days, bets = simulate_selected_rules(predicted_for_days, empty_candidates, [], daily_limit)
            decision = "ABSTAIN"
        result = metrics(days, bets)
        row = {
            "month": str(period),
            "decision": decision,
            "consensus_labels": consensus_labels,
            "selected_counts": dict(selected_counter),
            "per_window": per_window,
            **result,
        }
        if consensus_rules and not gate_enabled:
            row["portfolio_gate"] = gate_reason
        monthly.append(row)
        if not days.empty:
            all_days.append(days.assign(month=str(period)))
        if not bets.empty:
            all_bets.append(bets.assign(month=str(period)))

    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit", "month"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    overall = metrics(days, bets)
    extra = monthly_summary(monthly, overall)
    summary = {
        "method": "multi-training-window consensus rule search",
        "description": "A rule must be selected by multiple model training windows before it can enter the next-month portfolio.",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "same_day_results_hidden_until_settlement": True,
        "odds_timing": "pre_closing_without_exact_snapshot_timestamp",
        "config": {
            "training_windows": training_windows,
            "primary_training_months": primary_training_months,
            "min_consensus_windows": min_consensus_windows,
            "lookback_months": lookback_months,
            "min_active_months": min_active_months,
            "min_bets": min_bets,
            "min_roi": min_roi,
            "max_rules": max_rules,
            "min_league_matches": min_league_matches,
            "daily_limit": daily_limit,
            "ev_thresholds": ev_thresholds,
            "recent_active_months": recent_active_months,
            "min_recent_roi": min_recent_roi,
            "portfolio_gate_mode": portfolio_gate_mode,
            "cooldown_months": cooldown_months,
            "lcb_z": lcb_z,
            "structure_modes": structure_modes,
            "outcome_scope": outcome_scope,
            "odds_bucket_scope": odds_bucket_scope,
            "league_group_scope": league_group_scope,
            "stake_mode": "fixed_1_unit_per_bet",
            "rules_tested": len(rules),
        },
        "overall": overall,
        **extra,
        "monthly": monthly,
    }
    return summary, days, bets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--training-windows", default="12,18,24,30")
    parser.add_argument("--primary-training-months", type=int, default=18)
    parser.add_argument("--min-consensus-windows", type=int, default=2)
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=5)
    parser.add_argument("--min-bets", type=int, default=25)
    parser.add_argument("--min-roi", type=float, default=0.03)
    parser.add_argument("--max-rules", type=int, default=5)
    parser.add_argument("--min-league-matches", type=int, default=1000)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--ev-thresholds", default="-0.02,-0.01,0.0")
    parser.add_argument("--recent-active-months", type=int, default=3)
    parser.add_argument("--min-recent-roi", type=float, default=0.0)
    parser.add_argument("--portfolio-gate", choices=("off", "balanced", "conservative"), default="balanced")
    parser.add_argument("--cooldown-months", type=int, default=3)
    parser.add_argument("--lcb-z", type=float, default=0.0)
    parser.add_argument("--structure-modes", default="any,fav_relation,goal_env")
    parser.add_argument("--outcome-scope", default="draw")
    parser.add_argument("--odds-bucket-scope", default="2.8-3.5")
    parser.add_argument("--league-group-scope", default="ALL_GROUPS")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/multi_window_consensus_search"))
    args = parser.parse_args()

    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    training_windows = parse_ints(args.training_windows)
    ev_thresholds = tuple(float(item.strip()) for item in args.ev_thresholds.split(",") if item.strip())
    structure_modes = tuple(item.strip() for item in args.structure_modes.split(",") if item.strip())
    outcome_scope = tuple(item.strip() for item in args.outcome_scope.split(",") if item.strip())
    odds_bucket_scope = parse_odds_bucket_scope(args.odds_bucket_scope)
    league_group_scope = tuple(item.strip() for item in args.league_group_scope.split(",") if item.strip())
    summary, days, bets = run_consensus(
        args.first_month,
        args.last_month,
        seasons,
        training_windows,
        args.primary_training_months,
        args.min_consensus_windows,
        args.lookback_months,
        args.min_active_months,
        args.min_bets,
        args.min_roi,
        args.max_rules,
        args.min_league_matches,
        args.daily_limit,
        ev_thresholds,
        args.recent_active_months,
        args.min_recent_roi,
        args.portfolio_gate,
        args.cooldown_months,
        args.lcb_z,
        structure_modes,
        outcome_scope,
        odds_bucket_scope,
        league_group_scope,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
