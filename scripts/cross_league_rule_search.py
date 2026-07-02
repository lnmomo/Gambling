from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from walk_forward_residual_strategy import (  # noqa: E402
    OUTCOMES,
    PortfolioConfig,
    ResidualProbabilityModel,
    build_feature_history,
    choose_candidates,
    load_matches,
    metrics,
)
from fixed_sp2_edge_strategy import _stability_assessment  # noqa: E402


DEFAULT_SEASONS = ("2122", "2223", "2324", "2425", "2526")
ODDS_BUCKETS = ("[1.5,1.8)", "[1.8,2.2)", "[2.2,2.8)", "[2.8,3.5)", "[3.5,4.0)", "[4.0,5.0)", "[5.0,7.0)")
ODDS_BUCKET_ALIASES = {
    "1.5-1.8": "[1.5,1.8)",
    "1.8-2.2": "[1.8,2.2)",
    "2.2-2.8": "[2.2,2.8)",
    "2.8-3.5": "[2.8,3.5)",
    "3.5-4.0": "[3.5,4.0)",
    "4.0-5.0": "[4.0,5.0)",
    "5.0-7.0": "[5.0,7.0)",
}


@dataclass(frozen=True)
class SearchRule:
    label: str
    league_group: str
    leagues: tuple[str, ...]
    outcome: str
    odds_bucket: str
    min_lower_ev: float
    max_odds: float
    structure_key: str = "any"
    structure_value: str = "any"


def load_seasons(seasons: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    root = Path("data/historical_csv/football-data")
    for season in seasons:
        path = root / season
        if path.exists():
            frames.append(load_matches(path))
            continue
        normalized = season.removesuffix(".csv")
        worldwide_path = root / "new" / f"{Path(normalized).name}.csv"
        if worldwide_path.exists():
            frames.append(load_matches(worldwide_path))
    if not frames:
        raise ValueError("No requested seasons are available")
    return pd.concat(frames, ignore_index=True).sort_values("match_date").reset_index(drop=True)


def rule_pool(features: pd.DataFrame, min_league_matches: int, ev_thresholds: tuple[float, ...],
              structure_modes: tuple[str, ...],
              outcome_scope: tuple[str, ...],
              odds_bucket_scope: tuple[str, ...],
              league_group_scope: tuple[str, ...] = ("ALL_GROUPS",)) -> list[SearchRule]:
    league_counts = features.groupby("league").size()
    leagues = sorted(str(league) for league, count in league_counts.items() if count >= min_league_matches)
    predefined_groups = {
        "ALL": tuple(leagues),
        "MAJOR_TOP": tuple(league for league in ("E0", "SP1", "I1", "D1", "F1") if league in leagues),
        "SECOND_DIV": tuple(league for league in ("E1", "SP2", "I2", "D2", "F2") if league in leagues),
        "EN_LOWER": tuple(league for league in ("E1", "E2", "E3") if league in leagues),
        "DRAW_HEAVY_EU": tuple(league for league in ("SP2", "I2", "F2", "D2") if league in leagues),
    }
    league_groups = {label: group for label, group in predefined_groups.items() if group}
    league_groups.update({league: (league,) for league in leagues})
    if league_group_scope != ("ALL_GROUPS",):
        requested = set(league_group_scope)
        league_groups = {label: group for label, group in league_groups.items() if label in requested}
    rules: list[SearchRule] = []
    structure_values = {
        "any": ("any",),
        "fav_relation": ("market_favorite", "market_non_favorite"),
        "market_shape": ("balanced", "clear_favorite", "heavy_favorite"),
        "model_delta": ("weak_model_edge", "medium_model_edge", "strong_model_edge"),
        "pure_delta": ("pure_disagrees", "pure_small_edge", "pure_large_edge"),
        "strength_gap": ("even_strength", "moderate_gap", "large_gap"),
        "goal_env": ("low_goal", "normal_goal", "high_goal"),
        "league_draw_rate": ("low_draw_league", "normal_draw_league", "high_draw_league"),
        "draw_market_prob": ("low_draw_prob", "mid_draw_prob", "high_draw_prob"),
    }
    structures = [
        (mode, value)
        for mode in structure_modes
        for value in structure_values.get(mode, ())
    ]
    for league_group, group_leagues in league_groups.items():
        for outcome in outcome_scope:
            for odds_bucket in odds_bucket_scope:
                for min_ev in ev_thresholds:
                    for structure_key, structure_value in structures:
                        suffix = "" if structure_key == "any" else f"|{structure_key}={structure_value}"
                        label = f"{league_group}|{outcome}|{odds_bucket}|ev>={min_ev:.2f}{suffix}"
                        rules.append(SearchRule(
                            label,
                            league_group,
                            group_leagues,
                            outcome,
                            odds_bucket,
                            min_ev,
                            7.0,
                            structure_key,
                            structure_value,
                        ))
    return rules


def _market_shape(row: pd.Series) -> str:
    values = sorted((float(row[f"market_{outcome}"]) for outcome in OUTCOMES), reverse=True)
    gap = values[0] - values[1]
    if gap < 0.08:
        return "balanced"
    if values[0] >= 0.52 or gap >= 0.20:
        return "heavy_favorite"
    return "clear_favorite"


def _edge_bucket(value: float, weak_label: str, medium_label: str, strong_label: str) -> str:
    if value < 0.015:
        return weak_label
    if value < 0.04:
        return medium_label
    return strong_label


def _strength_gap_bucket(elo_delta: float) -> str:
    gap = abs(float(elo_delta))
    if gap < 55:
        return "even_strength"
    if gap < 140:
        return "moderate_gap"
    return "large_gap"


def _goal_env_bucket(lambda_total: float) -> str:
    total = float(lambda_total)
    if total < 2.25:
        return "low_goal"
    if total < 2.85:
        return "normal_goal"
    return "high_goal"


def _league_draw_rate_bucket(rate: float) -> str:
    value = float(rate)
    if value < 0.245:
        return "low_draw_league"
    if value < 0.295:
        return "normal_draw_league"
    return "high_draw_league"


def _draw_market_prob_bucket(probability: float) -> str:
    value = float(probability)
    if value < 0.285:
        return "low_draw_prob"
    if value < 0.335:
        return "mid_draw_prob"
    return "high_draw_prob"


def parse_odds_bucket_scope(raw: str) -> tuple[str, ...]:
    if raw.strip().upper() == "ALL":
        return ODDS_BUCKETS
    delimiter = ";" if ";" in raw else ","
    values = []
    for item in raw.split(delimiter):
        key = item.strip()
        if not key:
            continue
        values.append(ODDS_BUCKET_ALIASES.get(key, key))
    return tuple(values)


def month_candidates(predicted: pd.DataFrame, min_lower_ev: float, max_odds: float) -> pd.DataFrame:
    base = PortfolioConfig(min_lower_ev=min_lower_ev, max_odds=max_odds, kelly_fraction=0.0, min_stake=1.0, max_stake=1.0)
    candidates = choose_candidates(predicted, base)
    if candidates.empty:
        return candidates
    candidates = candidates.copy()
    actual = predicted.loc[candidates["row_index"].astype(int), "actual_result"].reset_index(drop=True)
    candidates = candidates.reset_index(drop=True)
    candidates["actual_result"] = actual
    candidates["won"] = candidates["outcome"] == candidates["actual_result"]
    candidates["unit_profit"] = candidates.apply(lambda row: float(row["odds"]) - 1.0 if row["won"] else -1.0, axis=1)
    candidates["bet_key"] = candidates["row_index"].astype(str) + "|" + candidates["outcome"].astype(str)
    source = predicted.loc[candidates["row_index"].astype(int)].reset_index(drop=True)
    market_favorites = source[[f"market_{outcome}" for outcome in OUTCOMES]].idxmax(axis=1).str.replace("market_", "", regex=False)
    candidates["fav_relation"] = [
        "market_favorite" if outcome == favorite else "market_non_favorite"
        for outcome, favorite in zip(candidates["outcome"], market_favorites)
    ]
    candidates["market_shape"] = source.apply(_market_shape, axis=1)
    model_delta = []
    pure_delta = []
    for i, outcome in enumerate(candidates["outcome"]):
        model_delta.append(float(source.loc[i, f"probability_{outcome}"]) - float(source.loc[i, f"market_{outcome}"]))
        pure_delta.append(float(source.loc[i, f"pure_{outcome}"]) - float(source.loc[i, f"market_{outcome}"]))
    candidates["model_delta"] = model_delta
    candidates["pure_delta"] = pure_delta
    candidates["model_delta_bucket"] = [
        _edge_bucket(value, "weak_model_edge", "medium_model_edge", "strong_model_edge")
        for value in model_delta
    ]
    candidates["pure_delta_bucket"] = [
        "pure_disagrees" if value < 0 else _edge_bucket(value, "pure_small_edge", "pure_small_edge", "pure_large_edge")
        for value in pure_delta
    ]
    candidates["strength_gap"] = source["elo_delta"].map(_strength_gap_bucket).to_list()
    candidates["goal_env"] = source["lambda_total"].map(_goal_env_bucket).to_list()
    candidates["league_draw_rate_bucket"] = source["league_draw_rate"].map(_league_draw_rate_bucket).to_list()
    candidates["draw_market_prob_bucket"] = source["market_draw"].map(_draw_market_prob_bucket).to_list()
    return candidates


def filter_rule(candidates: pd.DataFrame, rule: SearchRule) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    selected = candidates[
        (candidates["league"].isin(rule.leagues))
        & (candidates["outcome"] == rule.outcome)
        & (candidates["odds_bucket"] == rule.odds_bucket)
        & (candidates["lower_ev"] >= rule.min_lower_ev)
        & (candidates["odds"] <= rule.max_odds)
    ]
    if rule.structure_key == "fav_relation":
        selected = selected[selected["fav_relation"] == rule.structure_value]
    elif rule.structure_key == "market_shape":
        selected = selected[selected["market_shape"] == rule.structure_value]
    elif rule.structure_key == "model_delta":
        selected = selected[selected["model_delta_bucket"] == rule.structure_value]
    elif rule.structure_key == "pure_delta":
        selected = selected[selected["pure_delta_bucket"] == rule.structure_value]
    elif rule.structure_key == "strength_gap":
        selected = selected[selected["strength_gap"] == rule.structure_value]
    elif rule.structure_key == "goal_env":
        selected = selected[selected["goal_env"] == rule.structure_value]
    elif rule.structure_key == "league_draw_rate":
        selected = selected[selected["league_draw_rate_bucket"] == rule.structure_value]
    elif rule.structure_key == "draw_market_prob":
        selected = selected[selected["draw_market_prob_bucket"] == rule.structure_value]
    return selected


def summarize_rule_month(candidates: pd.DataFrame, rule: SearchRule) -> dict:
    selected = filter_rule(candidates, rule)
    if selected.empty:
        return {"bets": 0, "total_staked": 0.0, "profit": 0.0, "roi_pct": 0.0}
    profit = float(selected["unit_profit"].sum())
    bets = int(len(selected))
    return {
        "bets": bets,
        "total_staked": float(bets),
        "profit": round(profit, 2),
        "roi_pct": round(profit / bets * 100, 2),
    }


def select_rules(history: list[dict], rules: list[SearchRule], lookback_months: int,
                 min_active_months: int, min_bets: int, min_roi: float,
                 max_rules: int, recent_active_months: int,
                 min_recent_roi: float, lcb_z: float) -> tuple[list[SearchRule], dict]:
    active_history = [
        row for row in history
        if any(result.get("bets", 0) > 0 for result in row["rule_results"].values())
    ][-lookback_months:]
    if len(active_history) < min_active_months:
        return [], {"decision": "ABSTAIN", "reason": f"fewer_than_{min_active_months}_active_history_months"}

    rows = []
    rule_by_label = {rule.label: rule for rule in rules}
    for rule in rules:
        sample = [
            row["rule_results"][rule.label]
            for row in active_history
            if row["rule_results"].get(rule.label, {}).get("bets", 0) > 0
        ]
        if len(sample) < min_active_months:
            continue
        bets = sum(item["bets"] for item in sample)
        staked = sum(item["total_staked"] for item in sample)
        profit = sum(item["profit"] for item in sample)
        positive = sum(item["profit"] > 0 for item in sample)
        negative = sum(item["profit"] < 0 for item in sample)
        recent_sample = sample[-recent_active_months:]
        recent_bets = sum(item["bets"] for item in recent_sample)
        recent_staked = sum(item["total_staked"] for item in recent_sample)
        recent_profit = sum(item["profit"] for item in recent_sample)
        recent_positive = sum(item["profit"] > 0 for item in recent_sample)
        recent_negative = sum(item["profit"] < 0 for item in recent_sample)
        monthly_rois = [
            item["profit"] / item["total_staked"]
            for item in sample
            if item["total_staked"] > 0
        ]
        if bets < min_bets or staked <= 0:
            continue
        roi = profit / staked
        recent_roi = recent_profit / recent_staked if recent_staked else -1.0
        roi_std = pd.Series(monthly_rois).std(ddof=0) if monthly_rois else 999.0
        edge_lcb = roi - lcb_z * float(roi_std)
        if profit <= 0 or roi < min_roi or positive <= negative:
            continue
        if recent_bets < max(5, min_bets // 4) or recent_roi < min_recent_roi or recent_positive < recent_negative:
            continue
        if edge_lcb <= 0:
            continue
        rows.append({
            "label": rule.label,
            "bets": bets,
            "profit": round(profit, 2),
            "roi": round(roi, 4),
            "edge_lcb": round(edge_lcb, 4),
            "recent_bets": recent_bets,
            "recent_profit": round(recent_profit, 2),
            "recent_roi": round(recent_roi, 4),
            "positive_months": positive,
            "negative_months": negative,
            "recent_positive_months": recent_positive,
            "recent_negative_months": recent_negative,
            "active_months": len(sample),
            "score": (positive - negative) * 2 + edge_lcb * 20 + recent_roi * 8 + profit / max(bets, 1),
        })

    rows.sort(key=lambda row: (row["score"], row["positive_months"] - row["negative_months"], row["profit"]), reverse=True)
    selected_rows = rows[:max_rules]
    selected = [rule_by_label[row["label"]] for row in selected_rows]
    return selected, {"decision": "INVEST" if selected else "ABSTAIN", "selected": selected_rows, "eligible_rules": len(rows)}


def simulate_selected_rules(predicted: pd.DataFrame, candidates: pd.DataFrame,
                            selected_rules: list[SearchRule], daily_limit: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not selected_rules or candidates.empty:
        days = pd.DataFrame([
            {"date": date.strftime("%Y-%m-%d"), "bets": 0, "staked": 0.0, "profit": 0.0}
            for date in pd.date_range(predicted["match_date"].min(), predicted["match_date"].max(), freq="D")
        ])
        return days, pd.DataFrame()

    frames = []
    for rule in selected_rules:
        frame = filter_rule(candidates, rule).copy()
        if frame.empty:
            continue
        frame["rule_label"] = rule.label
        frames.append(frame)
    if not frames:
        return simulate_selected_rules(predicted, candidates.iloc[0:0], [], daily_limit)

    selected = pd.concat(frames, ignore_index=True)
    selected = selected.sort_values(["lower_ev", "unit_profit"], ascending=[False, False]).drop_duplicates("bet_key")
    bets: list[dict] = []
    days: list[dict] = []
    for date in pd.date_range(predicted["match_date"].min(), predicted["match_date"].max(), freq="D"):
        day = selected[selected["date"] == date].sort_values("lower_ev", ascending=False)
        used = 0.0
        profit = 0.0
        count = 0
        for _, candidate in day.iterrows():
            if used >= daily_limit - 0.01:
                break
            stake = min(1.0, daily_limit - used)
            bet_profit = stake * (float(candidate["odds"]) - 1.0) if bool(candidate["won"]) else -stake
            source = predicted.loc[int(candidate["row_index"])]
            bets.append({
                "date": date.strftime("%Y-%m-%d"),
                "league": candidate["league"],
                "home_team": source["home_team"],
                "away_team": source["away_team"],
                "outcome": candidate["outcome"],
                "actual_result": candidate["actual_result"],
                "odds_bucket": candidate["odds_bucket"],
                "fav_relation": candidate.get("fav_relation"),
                "market_shape": candidate.get("market_shape"),
                "model_delta_bucket": candidate.get("model_delta_bucket"),
                "pure_delta_bucket": candidate.get("pure_delta_bucket"),
                "strength_gap": candidate.get("strength_gap"),
                "goal_env": candidate.get("goal_env"),
                "league_draw_rate_bucket": candidate.get("league_draw_rate_bucket"),
                "draw_market_prob_bucket": candidate.get("draw_market_prob_bucket"),
                "probability": round(float(candidate["probability"]), 6),
                "lower_ev": round(float(candidate["lower_ev"]), 6),
                "odds": round(float(candidate["odds"]), 3),
                "stake": round(stake, 2),
                "won": bool(candidate["won"]),
                "profit": round(bet_profit, 2),
                "rule_label": candidate["rule_label"],
            })
            used += stake
            profit += bet_profit
            count += 1
        days.append({"date": date.strftime("%Y-%m-%d"), "bets": count, "staked": round(used, 2), "profit": round(profit, 2)})
    return pd.DataFrame(days), pd.DataFrame(bets)


def _month_gap(left: str, right: str) -> int:
    return (pd.Period(right, freq="M") - pd.Period(left, freq="M")).n


def portfolio_gate(monthly: list[dict], mode: str, current_month: str, cooldown_months: int) -> tuple[bool, str]:
    if mode == "off":
        return True, "gate_off"
    active = [row for row in monthly if row.get("bets", 0) > 0]
    if len(active) < 3:
        return True, "warmup_gate_open_until_3_active_months"
    last3 = active[-3:]
    last6 = active[-6:]
    last3_profit = sum(float(row["profit"]) for row in last3)
    last6_profit = sum(float(row["profit"]) for row in last6)
    last3_positive = sum(float(row["profit"]) > 0 for row in last3)
    if mode == "balanced":
        enabled = last3_profit > 0 and last3_positive >= 2
    elif mode == "conservative":
        enabled = last3_profit > 0 and last3_positive >= 2 and last6_profit >= 0
    else:
        raise ValueError(f"Unknown portfolio gate mode: {mode}")
    reason = f"last3_profit={last3_profit:.2f},last3_positive={last3_positive},last6_profit={last6_profit:.2f}"
    if not enabled and cooldown_months > 0:
        gap = _month_gap(str(active[-1]["month"]), current_month)
        if gap >= cooldown_months:
            return True, f"cooldown_probe_after_{gap}_months|{reason}"
    return enabled, reason


def monthly_summary(monthly: list[dict], overall: dict) -> dict:
    active = [row for row in monthly if row["bets"] > 0]
    assessment_rows = [
        {
            "month": row["month"],
            "bets": row["bets"],
            "profit": row["profit"],
            "roi_pct": row["roi_pct"],
            "staked": row["total_staked"],
        }
        for row in active
    ]
    return {
        "active_months": len(active),
        "positive_months": sum(row["profit"] > 0 for row in active),
        "negative_months": sum(row["profit"] < 0 for row in active),
        "stability_assessment": _stability_assessment(overall, assessment_rows),
    }


def run_search(first_month: str, last_month: str, seasons: tuple[str, ...],
               lookback_months: int, min_active_months: int, min_bets: int,
               min_roi: float, max_rules: int, min_league_matches: int,
               daily_limit: float, ev_thresholds: tuple[float, ...],
               recent_active_months: int, min_recent_roi: float,
               portfolio_gate_mode: str, cooldown_months: int,
               lcb_z: float, structure_modes: tuple[str, ...],
               outcome_scope: tuple[str, ...],
               odds_bucket_scope: tuple[str, ...],
               training_months: int,
               league_group_scope: tuple[str, ...] = ("ALL_GROUPS",)) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    matches = load_seasons(seasons)
    features = build_feature_history(matches)
    rules = rule_pool(features, min_league_matches, ev_thresholds, structure_modes, outcome_scope, odds_bucket_scope, league_group_scope)
    if not rules:
        raise ValueError("No rules were generated; check league/outcome/odds scopes")
    min_ev = min(rule.min_lower_ev for rule in rules)
    max_odds = max(rule.max_odds for rule in rules)

    history: list[dict] = []
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []
    monthly: list[dict] = []

    for period in pd.period_range(first_month, last_month, freq="M"):
        start, end = period.start_time.normalize(), period.end_time.normalize()
        train = features[(features.match_date >= start - pd.DateOffset(months=training_months)) & (features.match_date < start)]
        test = features[(features.match_date >= start) & (features.match_date <= end)]
        if len(train) < 300 or test.empty:
            monthly.append({"month": str(period), "decision": "ABSTAIN", "reason": "insufficient_train_or_test", "bets": 0, "total_staked": 0.0, "profit": 0.0, "roi_pct": 0.0})
            continue

        predicted = ResidualProbabilityModel(uncertainty_scale=0.85).fit(train).predict(test.reset_index(drop=True))
        candidates = month_candidates(predicted, min_ev, max_odds)
        rule_results = {rule.label: summarize_rule_month(candidates, rule) for rule in rules}
        selected_rules, selection = select_rules(
            history,
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
        gate_enabled, gate_reason = portfolio_gate(monthly, portfolio_gate_mode, str(period), cooldown_months)
        if selected_rules and not gate_enabled:
            days, bets = simulate_selected_rules(predicted, candidates, [], daily_limit)
            selection = {**selection, "decision": "ABSTAIN", "portfolio_gate": gate_reason}
        else:
            days, bets = simulate_selected_rules(predicted, candidates, selected_rules, daily_limit)
        result = metrics(days, bets)
        row = {
            "month": str(period),
            "decision": selection["decision"],
            "selection": selection,
            **result,
        }
        monthly.append(row)
        history.append({"month": str(period), "rule_results": rule_results})
        if not days.empty:
            all_days.append(days.assign(month=str(period)))
        if not bets.empty:
            all_bets.append(bets.assign(month=str(period)))

    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit", "month"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    overall = metrics(days, bets)
    extra = monthly_summary(monthly, overall)
    summary = {
        "method": "cross-league monthly no-lookahead rule search",
        "description": "Searches league/outcome/odds-bucket residual-edge rules using only prior months, then validates on the next month.",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "same_day_results_hidden_until_settlement": True,
        "odds_timing": "pre_closing_without_exact_snapshot_timestamp",
        "config": {
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
            "training_months": training_months,
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
    parser.add_argument("--portfolio-gate", choices=("off", "balanced", "conservative"), default="off")
    parser.add_argument("--cooldown-months", type=int, default=3)
    parser.add_argument("--lcb-z", type=float, default=0.5)
    parser.add_argument("--structure-modes", default="any,fav_relation,goal_env")
    parser.add_argument("--outcome-scope", default="draw")
    parser.add_argument("--odds-bucket-scope", default="2.8-3.5")
    parser.add_argument("--training-months", type=int, default=18)
    parser.add_argument("--league-group-scope", default="ALL_GROUPS")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cross_league_rule_search"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    ev_thresholds = tuple(float(item.strip()) for item in args.ev_thresholds.split(",") if item.strip())
    structure_modes = tuple(item.strip() for item in args.structure_modes.split(",") if item.strip())
    outcome_scope = tuple(item.strip() for item in args.outcome_scope.split(",") if item.strip())
    odds_bucket_scope = parse_odds_bucket_scope(args.odds_bucket_scope)
    league_group_scope = tuple(item.strip() for item in args.league_group_scope.split(",") if item.strip())
    summary, days, bets = run_search(
        args.first_month,
        args.last_month,
        seasons,
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
        args.training_months,
        league_group_scope,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
