from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from walk_forward_residual_strategy import (
    PortfolioConfig,
    ResidualProbabilityModel,
    build_feature_history,
    choose_candidates,
    load_matches,
    metrics,
)


DEFAULT_SEASONS = ("2122", "2223", "2324", "2425")
ODDS_BUCKETS = (
    "[1.0,1.8)", "[1.8,2.2)", "[2.2,2.8)", "[2.8,3.5)",
    "[3.5,4.0)", "[4.0,5.0)", "[5.0,7.0)", "[7.0,inf)",
)
ADAPTIVE_GRID = (
    (-0.02, 4.0, 0.05),
    (-0.02, 5.0, 0.05),
    (-0.01, 4.0, 0.05),
    (-0.01, 5.0, 0.05),
    (0.00, 4.0, 0.05),
    (0.00, 5.0, 0.05),
    (-0.01, 4.0, 0.10),
    (-0.01, 5.0, 0.10),
    (0.00, 4.0, 0.10),
    (0.00, 5.0, 0.10),
)


RULE_ADAPTIVE_GRID = (
    ("sp2_draw_all", "draw", None, -0.01, 5.0, 0.10, 1.0),
    ("sp2_draw_all_min025", "draw", None, -0.01, 5.0, 0.10, 0.25),
    ("sp2_draw_22_28", "draw", "[2.2,2.8)", -0.01, 5.0, 0.10, 1.0),
    ("sp2_draw_28_35", "draw", "[2.8,3.5)", -0.01, 5.0, 0.10, 1.0),
    ("sp2_all_min025", None, None, -0.01, 5.0, 0.10, 0.25),
    ("sp2_all", None, None, -0.01, 5.0, 0.10, 1.0),
)


def load_seasons(seasons: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        path = Path(f"data/historical_csv/football-data/{season}")
        if path.exists():
            frames.append(load_matches(path))
    if not frames:
        raise ValueError("No requested football-data seasons are available")
    return pd.concat(frames, ignore_index=True).sort_values("match_date").reset_index(drop=True)


def simulate_fixed_sp2_edge(predictions: pd.DataFrame, config: PortfolioConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = choose_candidates(predictions, config)
    if not candidates.empty:
        candidates = candidates[candidates["league"] == "SP2"]
    bets: list[dict] = []
    days: list[dict] = []
    for date in pd.date_range(predictions["match_date"].min(), predictions["match_date"].max(), freq="D"):
        day = candidates[candidates["date"] == date].sort_values("lower_ev", ascending=False) if not candidates.empty else candidates
        used = 0.0
        day_profit = 0.0
        day_bets = 0
        for _, candidate in day.iterrows():
            if used >= config.daily_limit - 0.01:
                break
            probability = float(candidate["probability"])
            odds = float(candidate["odds"])
            full_kelly = max(0.0, (probability * odds - 1) / (odds - 1))
            stake = max(config.min_stake, config.daily_limit * full_kelly * config.kelly_fraction)
            stake = min(stake, config.max_stake, config.daily_limit - used)
            if stake < config.min_stake:
                continue
            source = predictions.loc[int(candidate["row_index"])]
            won = candidate["outcome"] == source["actual_result"]
            profit = stake * (odds - 1) if won else -stake
            used += stake
            day_profit += profit
            day_bets += 1
            bets.append({
                "date": date.strftime("%Y-%m-%d"),
                "league": candidate["league"],
                "home_team": source["home_team"],
                "away_team": source["away_team"],
                "outcome": candidate["outcome"],
                "actual_result": source["actual_result"],
                "probability": round(probability, 6),
                "uncertainty": round(float(candidate["uncertainty"]), 6),
                "lower_ev": round(float(candidate["lower_ev"]), 6),
                "odds": odds,
                "stake": round(stake, 2),
                "won": won,
                "profit": round(profit, 2),
            })
        days.append({
            "date": date.strftime("%Y-%m-%d"),
            "bets": day_bets,
            "staked": round(used, 2),
            "profit": round(day_profit, 2),
        })
    return pd.DataFrame(days), pd.DataFrame(bets)


def _select_adaptive_config(candidate_history: list[dict]) -> tuple[PortfolioConfig | None, dict]:
    recent = [
        row for row in candidate_history
        if any(result.get("bets", 0) > 0 for result in row["grid_results"].values())
    ][-6:]
    if len(recent) < 3:
        return None, {"decision": "ABSTAIN", "reason": "fewer_than_3_recent_active_months"}
    rows = []
    for ev, max_odds, kelly in ADAPTIVE_GRID:
        key = _grid_key(ev, max_odds, kelly)
        sample = [row["grid_results"].get(key) for row in recent if row["grid_results"].get(key, {}).get("bets", 0) > 0]
        bets = sum(item["bets"] for item in sample)
        profit = sum(item["profit"] for item in sample)
        staked = sum(item["total_staked"] for item in sample)
        positive_months = sum(item["profit"] > 0 for item in sample)
        negative_months = sum(item["profit"] < 0 for item in sample)
        if bets < 12 or len(sample) < 3 or staked <= 0:
            continue
        roi = profit / staked
        if profit <= 0 or roi <= 0.03 or positive_months <= negative_months:
            continue
        rows.append({
            "config": PortfolioConfig(ev, max_odds, kelly),
            "bets": bets,
            "profit": profit,
            "roi": roi,
            "positive_months": positive_months,
            "negative_months": negative_months,
        })
    if not rows:
        return None, {"decision": "ABSTAIN", "reason": "no_recent_profitable_grid_config"}
    best = max(rows, key=lambda item: (item["profit"] - item["negative_months"], item["roi"]))
    return best["config"], {key: value for key, value in best.items() if key != "config"}


def _grid_key(min_ev: float, max_odds: float, kelly: float) -> str:
    return f"ev={min_ev:.3f}|max={max_odds:.1f}|kelly={kelly:.2f}"


def _month_grid_results(predictions: pd.DataFrame) -> dict[str, dict]:
    output = {}
    for min_ev, max_odds, kelly in ADAPTIVE_GRID:
        config = PortfolioConfig(min_ev, max_odds, kelly)
        days, bets = simulate_fixed_sp2_edge(predictions, config)
        output[_grid_key(min_ev, max_odds, kelly)] = metrics(days, bets)
    return output


def _rule_config(outcome_filter: str | None, odds_bucket_filter: str | None,
                 min_lower_ev: float, max_odds: float,
                 kelly_fraction: float, min_stake: float) -> PortfolioConfig:
    return PortfolioConfig(
        min_lower_ev=min_lower_ev,
        max_odds=max_odds,
        kelly_fraction=kelly_fraction,
        min_stake=min_stake,
        bucket_key=("outcome", "odds_bucket") if outcome_filter or odds_bucket_filter else (),
        allowed_buckets=_allowed_buckets(outcome_filter, odds_bucket_filter),
    )


def _rule_configs() -> dict[str, PortfolioConfig]:
    return {
        label: _rule_config(outcome, bucket, min_ev, max_odds, kelly, min_stake)
        for label, outcome, bucket, min_ev, max_odds, kelly, min_stake in RULE_ADAPTIVE_GRID
    }


def _month_rule_results(predictions: pd.DataFrame) -> dict[str, dict]:
    output = {}
    for label, config in _rule_configs().items():
        days, bets = simulate_fixed_sp2_edge(predictions, config)
        output[label] = metrics(days, bets)
    return output


def _select_rule_config(candidate_history: list[dict], lookback_months: int,
                        min_active_months: int, min_bets: int,
                        min_roi: float) -> tuple[str | None, PortfolioConfig | None, dict]:
    recent = [
        row for row in candidate_history
        if any(result.get("bets", 0) > 0 for result in row["rule_results"].values())
    ][-lookback_months:]
    if len(recent) < min_active_months:
        return None, None, {
            "decision": "ABSTAIN",
            "reason": f"fewer_than_{min_active_months}_recent_active_months",
        }
    rows = []
    configs = _rule_configs()
    for label, config in configs.items():
        sample = [
            row["rule_results"].get(label)
            for row in recent
            if row["rule_results"].get(label, {}).get("bets", 0) > 0
        ]
        if len(sample) < min_active_months:
            continue
        bets = sum(item["bets"] for item in sample)
        profit = sum(item["profit"] for item in sample)
        staked = sum(item["total_staked"] for item in sample)
        positive_months = sum(item["profit"] > 0 for item in sample)
        negative_months = sum(item["profit"] < 0 for item in sample)
        if bets < min_bets or staked <= 0:
            continue
        roi = profit / staked
        if profit <= 0 or roi <= min_roi or positive_months <= negative_months:
            continue
        rows.append({
            "label": label,
            "config": config,
            "bets": bets,
            "profit": round(profit, 2),
            "roi": roi,
            "positive_months": positive_months,
            "negative_months": negative_months,
            "active_months": len(sample),
        })
    if not rows:
        return None, None, {"decision": "ABSTAIN", "reason": "no_recent_rule_passed_gate"}
    best = max(rows, key=lambda item: (item["positive_months"] - item["negative_months"], item["profit"], item["roi"]))
    report = {key: value for key, value in best.items() if key != "config"}
    report["roi"] = round(report["roi"], 4)
    return best["label"], best["config"], report


def _gate_decision(history: list[dict], mode: str) -> tuple[bool, str]:
    if mode == "off":
        return True, "gate_off"
    active_history = [row for row in history if row["candidate_bets"] > 0]
    if len(active_history) < 3:
        return False, "warmup_until_3_active_months"
    last3 = active_history[-3:]
    last6 = active_history[-6:]
    last3_profit = sum(row["candidate_profit"] for row in last3)
    last6_profit = sum(row["candidate_profit"] for row in last6)
    last3_positive = sum(row["candidate_profit"] > 0 for row in last3)
    if mode == "conservative":
        enabled = last3_profit > 0 and last3_positive >= 2 and last6_profit >= -2
    elif mode == "balanced":
        enabled = last3_profit > 0 and last3_positive >= 2
    else:
        raise ValueError(f"Unknown gate mode: {mode}")
    reason = f"last3_profit={last3_profit:.2f},last3_positive={last3_positive},last6_profit={last6_profit:.2f}"
    return enabled, reason


def _allowed_buckets(outcome_filter: str | None, odds_bucket_filter: str | None) -> tuple[tuple[str, ...], ...]:
    if not outcome_filter and not odds_bucket_filter:
        return ()
    outcomes = [outcome_filter] if outcome_filter else ["home", "draw", "away"]
    buckets = [odds_bucket_filter] if odds_bucket_filter else (
        "[1.0,1.8)", "[1.8,2.2)", "[2.2,2.8)", "[2.8,3.5)",
        "[3.5,4.0)", "[4.0,5.0)", "[5.0,7.0)", "[7.0,inf)",
    )
    return tuple((outcome, bucket) for outcome in outcomes for bucket in buckets)


def run_validation(first_month: str, last_month: str, seasons: tuple[str, ...],
                   gate_mode: str = "off", strategy_mode: str = "fixed",
                   min_lower_ev: float = -0.01, max_odds: float = 5.0,
                   kelly_fraction: float = 0.10, min_stake: float = 1.0,
                   outcome_filter: str | None = None,
                   odds_bucket_filter: str | None = None,
                   rule_lookback_months: int = 12,
                   rule_min_active_months: int = 6,
                   rule_min_bets: int = 40,
                   rule_min_roi: float = 0.02) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    matches = load_seasons(seasons)
    features = build_feature_history(matches)
    config = PortfolioConfig(
        min_lower_ev=min_lower_ev,
        max_odds=max_odds,
        kelly_fraction=kelly_fraction,
        min_stake=min_stake,
        bucket_key=("outcome", "odds_bucket") if outcome_filter or odds_bucket_filter else (),
        allowed_buckets=_allowed_buckets(outcome_filter, odds_bucket_filter),
    )
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []
    monthly: list[dict] = []
    gate_history: list[dict] = []
    candidate_history: list[dict] = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        start = period.start_time.normalize()
        end = period.end_time.normalize()
        train = features[(features["match_date"] >= start - pd.DateOffset(months=18)) & (features["match_date"] < start)]
        test = features[(features["match_date"] >= start) & (features["match_date"] <= end)]
        if len(train) < 300 or test.empty:
            continue
        predictions = ResidualProbabilityModel(uncertainty_scale=0.75).fit(train).predict(test)
        grid_results = _month_grid_results(predictions) if strategy_mode == "adaptive" else {}
        rule_results = _month_rule_results(predictions) if strategy_mode == "rule-adaptive" else {}
        if strategy_mode == "adaptive":
            selected_config, selection_report = _select_adaptive_config(candidate_history)
            selected_rule = None
            if selected_config is None:
                candidate_days = pd.DataFrame({
                    "date": pd.date_range(start, end, freq="D").strftime("%Y-%m-%d"),
                    "bets": 0, "staked": 0.0, "profit": 0.0,
                })
                candidate_bets = pd.DataFrame()
            else:
                candidate_days, candidate_bets = simulate_fixed_sp2_edge(predictions, selected_config)
        elif strategy_mode == "rule-adaptive":
            selected_rule, selected_config, selection_report = _select_rule_config(
                candidate_history,
                rule_lookback_months,
                rule_min_active_months,
                rule_min_bets,
                rule_min_roi,
            )
            if selected_config is None:
                candidate_days = pd.DataFrame({
                    "date": pd.date_range(start, end, freq="D").strftime("%Y-%m-%d"),
                    "bets": 0, "staked": 0.0, "profit": 0.0,
                })
                candidate_bets = pd.DataFrame()
            else:
                candidate_days, candidate_bets = simulate_fixed_sp2_edge(predictions, selected_config)
        elif strategy_mode == "fixed":
            selected_config = config
            selected_rule = "fixed_cli_config"
            selection_report = {"decision": "FIXED", "config": config.__dict__}
            candidate_days, candidate_bets = simulate_fixed_sp2_edge(predictions, config)
        else:
            raise ValueError(f"Unknown strategy mode: {strategy_mode}")
        enabled, gate_reason = _gate_decision(gate_history, gate_mode)
        if enabled and selected_config is not None:
            days, bets = candidate_days, candidate_bets
        else:
            days = candidate_days.copy()
            days[["bets", "staked", "profit"]] = 0
            bets = candidate_bets.iloc[0:0].copy()
        if not days.empty:
            all_days.append(days.assign(month=str(period)))
        if not bets.empty:
            all_bets.append(bets.assign(month=str(period)))
        monthly_row = metrics(days, bets)
        monthly_row["month"] = str(period)
        candidate_row = metrics(candidate_days, candidate_bets)
        monthly_row["gate_enabled"] = enabled
        monthly_row["gate_reason"] = gate_reason
        monthly_row["strategy_mode"] = strategy_mode
        monthly_row["selected_rule"] = selected_rule
        monthly_row["selected_config"] = selected_config.__dict__ if selected_config else None
        monthly_row["selection_report"] = selection_report
        monthly_row["candidate_bets"] = candidate_row["bets"]
        monthly_row["candidate_profit"] = candidate_row["profit"]
        monthly_row["candidate_roi_pct"] = candidate_row["roi_pct"]
        monthly.append(monthly_row)
        gate_history.append({
            "month": str(period),
            "candidate_bets": candidate_row["bets"],
            "candidate_profit": candidate_row["profit"],
        })
        candidate_history.append({
            "month": str(period),
            "candidate_bets": candidate_row["bets"],
            "candidate_profit": candidate_row["profit"],
            "grid_results": grid_results,
            "rule_results": rule_results,
        })

    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    active = [row for row in monthly if row["bets"] > 0]
    summary = {
        "method": "fixed SP2 market-residual edge strategy",
        "description": "Rolling 18-month residual probability model; bet only Spanish Segunda (SP2) candidates passing fixed pre-declared filters.",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "same_day_results_hidden_until_settlement": True,
        "odds_timing": "pre_closing_without_exact_snapshot_timestamp",
        "config": {
            "uncertainty_scale": 0.75,
            **config.__dict__,
            "league_filter": "SP2",
            "gate_mode": gate_mode,
            "strategy_mode": strategy_mode,
            "outcome_filter": outcome_filter,
            "odds_bucket_filter": odds_bucket_filter,
            "rule_adaptive_grid": RULE_ADAPTIVE_GRID if strategy_mode == "rule-adaptive" else None,
            "rule_lookback_months": rule_lookback_months if strategy_mode == "rule-adaptive" else None,
            "rule_min_active_months": rule_min_active_months if strategy_mode == "rule-adaptive" else None,
            "rule_min_bets": rule_min_bets if strategy_mode == "rule-adaptive" else None,
            "rule_min_roi": rule_min_roi if strategy_mode == "rule-adaptive" else None,
        },
        "overall": metrics(days, bets),
        "active_months": len(active),
        "positive_months": sum(row["profit"] > 0 for row in active),
        "negative_months": sum(row["profit"] < 0 for row in active),
        "stability_assessment": _stability_assessment(metrics(days, bets), active),
        "monthly": monthly,
    }
    return summary, days, bets


def _season_label(month: str) -> str:
    year, month_number = (int(part) for part in month.split("-"))
    start_year = year if month_number >= 8 else year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _season_summary(active_months: list[dict]) -> list[dict]:
    seasons: dict[str, dict] = {}
    for row in active_months:
        season = _season_label(str(row["month"]))
        item = seasons.setdefault(season, {"season": season, "bets": 0, "staked": 0.0, "profit": 0.0, "active_months": 0})
        staked = row.get("staked")
        if staked is None and row.get("roi_pct"):
            staked = float(row["profit"]) / (float(row["roi_pct"]) / 100)
        item["bets"] += int(row["bets"])
        item["staked"] += float(staked or 0.0)
        item["profit"] += float(row["profit"])
        item["active_months"] += 1

    summary = []
    for item in seasons.values():
        staked = item["staked"]
        summary.append({
            "season": item["season"],
            "bets": item["bets"],
            "staked": round(staked, 2),
            "profit": round(item["profit"], 2),
            "roi_pct": round(item["profit"] / staked * 100, 2) if staked else 0.0,
            "active_months": item["active_months"],
        })
    return sorted(summary, key=lambda item: item["season"])


def _stability_assessment(overall: dict, active_months: list[dict]) -> dict:
    positive = sum(row["profit"] > 0 for row in active_months)
    negative = sum(row["profit"] < 0 for row in active_months)
    seasons = _season_summary(active_months)
    positive_seasons = sum(row["profit"] > 0 for row in seasons)
    negative_seasons = sum(row["profit"] < 0 for row in seasons)
    latest_season = seasons[-1] if seasons else None
    drawdown_to_profit = round(overall["max_drawdown"] / overall["profit"], 3) if overall["profit"] > 0 else None
    profitable = overall["profit"] > 0 and overall["roi_pct"] > 0
    sample_size_ok = overall["bets"] >= 100
    month_balance_ok = positive > negative
    season_balance_ok = positive_seasons > negative_seasons
    drawdown_ok = drawdown_to_profit is not None and drawdown_to_profit <= 1.0
    latest_season_ok = bool(latest_season and latest_season["bets"] >= 10 and latest_season["profit"] >= 0)
    enough_active_months = len(active_months) >= 24

    if not profitable:
        verdict = "rejected_negative_edge"
    elif not sample_size_ok:
        verdict = "not_enough_sample"
    elif not latest_season_ok:
        verdict = "not_enough_recent_evidence"
    elif not (month_balance_ok and season_balance_ok and drawdown_ok and enough_active_months):
        verdict = "candidate_positive_but_unstable"
    else:
        verdict = "research_candidate_requires_live_shadow"

    return {
        "profitable": profitable,
        "sample_size_ok": sample_size_ok,
        "enough_active_months": enough_active_months,
        "month_balance_ok": month_balance_ok,
        "season_balance_ok": season_balance_ok,
        "drawdown_ok": drawdown_ok,
        "latest_season_ok": latest_season_ok,
        "positive_months": positive,
        "negative_months": negative,
        "positive_seasons": positive_seasons,
        "negative_seasons": negative_seasons,
        "latest_season": latest_season,
        "season_summary": seasons,
        "drawdown_to_profit": drawdown_to_profit,
        "verdict": verdict,
        "notes": [
            "Positive multi-season walk-forward ROI is necessary but not sufficient for production.",
            "A production candidate must keep a positive recent season without using future results.",
            "Monthly and season positive/negative balance plus drawdown control are required before real-money use.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2025-05")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--gate-mode", choices=("off", "balanced", "conservative"), default="off")
    parser.add_argument("--strategy-mode", choices=("fixed", "adaptive", "rule-adaptive"), default="fixed")
    parser.add_argument("--min-lower-ev", type=float, default=-0.01)
    parser.add_argument("--max-odds", type=float, default=5.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.10)
    parser.add_argument("--min-stake", type=float, default=1.0)
    parser.add_argument("--outcome-filter", choices=("home", "draw", "away"))
    parser.add_argument("--odds-bucket-filter")
    parser.add_argument("--rule-lookback-months", type=int, default=12)
    parser.add_argument("--rule-min-active-months", type=int, default=6)
    parser.add_argument("--rule-min-bets", type=int, default=40)
    parser.add_argument("--rule-min-roi", type=float, default=0.02)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/fixed_sp2_edge_strategy"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    summary, days, bets = run_validation(
        args.first_month,
        args.last_month,
        seasons,
        args.gate_mode,
        args.strategy_mode,
        args.min_lower_ev,
        args.max_odds,
        args.kelly_fraction,
        args.min_stake,
        args.outcome_filter,
        args.odds_bucket_filter,
        args.rule_lookback_months,
        args.rule_min_active_months,
        args.rule_min_bets,
        args.rule_min_roi,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
