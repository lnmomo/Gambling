"""No-lookahead monthly walk-forward experiment for a train-only CLV ranker.

The model learns closing-line value from opening information in the prior six
months. It never uses match results as a feature or model-selection target. The
immediate next month is scored with a frozen model, all daily stakes are frozen,
and only then are closing prices and results attached for evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scripts.robust_consensus_latest_month_holdout import (
    HistoricalMatch,
    Strategy,
    _candidate_buckets,
    _closing_price_quality,
    _monthly_bootstrap,
    _months_before,
    build_candidate_cache,
    complete_months,
    latest_complete_month,
    load_matches,
)
from scripts.portfolio_algorithm_optimization import PROJECT_ROOT


NUMERIC_FEATURES = (
    "probability",
    "conservative_probability",
    "odds",
    "raw_odds",
    "conservative_ev_pct",
    "reference_dispersion",
    "reference_bookmakers",
    "execution_cost_rate",
)
MARKET_STRUCTURE_NUMERIC_FEATURES = NUMERIC_FEATURES + (
    "implied_probability",
    "price_ratio",
    "probability_uncertainty",
    "relative_dispersion",
    "log_odds",
    "probability_squared",
    "odds_probability_interaction",
    "reference_depth_inverse",
    "raw_net_odds_gap_pct",
)
CATEGORICAL_FEATURES = (
    "outcome",
    "odds_band",
    "source_type",
    "execution_bookmaker",
    "league",
)
CATEGORICAL_FEATURES_PORTABLE = tuple(
    field for field in CATEGORICAL_FEATURES if field != "league"
)
MARKET_STRUCTURE_CATEGORICAL_FEATURES = CATEGORICAL_FEATURES_PORTABLE + (
    "outcome_odds_band",
    "outcome_source_type",
    "source_odds_band",
)
ALPHAS = (1.0, 10.0, 100.0)
SAFETY_MARGINS = (0.0, 0.25, 0.5)
MAXIMUM_ODDS_CAPS = (4.0, 5.0, 6.0, 8.0)
MINIMUM_LOWER_CLV_PCT = 1.0


@dataclass(frozen=True)
class RankerPolicy:
    daily_budget: float = 100.0
    maximum_single_stake: float = 5.0
    kelly_fraction: float = 0.10
    minimum_inner_validation_positions: int = 30
    minimum_inner_positive_clv_rate: float = 0.55


@dataclass
class FittedRanker:
    model: Pipeline
    alpha: float
    safety_margin: float
    maximum_odds: float
    validation_rmse_pct: float
    validation_diagnostics: list[dict[str, Any]]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


def _feature_contract(feature_profile: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if feature_profile == "full":
        return NUMERIC_FEATURES, CATEGORICAL_FEATURES
    if feature_profile == "portable":
        return NUMERIC_FEATURES, CATEGORICAL_FEATURES_PORTABLE
    if feature_profile == "market_structure":
        return MARKET_STRUCTURE_NUMERIC_FEATURES, MARKET_STRUCTURE_CATEGORICAL_FEATURES
    raise ValueError(f"unknown feature profile: {feature_profile}")


def market_structure_features(row: dict[str, Any]) -> dict[str, Any]:
    """Derive portable nonlinear basis terms using opening information only."""
    probability = float(row["probability"])
    conservative_probability = float(row["conservative_probability"])
    odds = float(row["odds"])
    raw_odds = float(row["raw_odds"])
    dispersion = float(row["reference_dispersion"])
    depth = max(1.0, float(row["reference_bookmakers"]))
    odds_band_value = str(row["odds_band"])
    source_type = str(row["source_type"])
    outcome = str(row["outcome"])
    return {
        "implied_probability": 1.0 / odds,
        "price_ratio": odds * probability,
        "probability_uncertainty": probability - conservative_probability,
        "relative_dispersion": dispersion / max(probability, 1e-9),
        "log_odds": math.log(odds),
        "probability_squared": probability * probability,
        "odds_probability_interaction": math.log(odds) * probability,
        "reference_depth_inverse": 1.0 / depth,
        "raw_net_odds_gap_pct": (raw_odds / odds - 1.0) * 100.0,
        "outcome_odds_band": f"{outcome}:{odds_band_value}",
        "outcome_source_type": f"{outcome}:{source_type}",
        "source_odds_band": f"{source_type}:{odds_band_value}",
    }


def broad_strategy(exchange_commission_rate: float) -> Strategy:
    return Strategy(
        name="RC-F-v6-clv-ridge-broad",
        minimum_price_ratio=0.97,
        minimum_conservative_ev=-0.05,
        dispersion_multiplier=1.0,
        minimum_probability=0.12,
        maximum_odds=8.0,
        minimum_reference_bookmakers=4,
        uncertainty_floor=0.002,
        slippage_rate=0.02,
        exchange_commission_rate=exchange_commission_rate,
        daily_budget=100.0,
        maximum_single_stake=5.0,
        kelly_fraction=0.10,
    )


def _opening_rows(
    matches: list[HistoricalMatch], strategy: Strategy,
    candidate_cache: dict[tuple[str, int], dict[str, Any] | None],
    start: date, end: date, include_closing_target: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for match in matches:
        if not start <= match.match_date <= end:
            continue
        key = (match.source_file, match.source_row)
        candidate = candidate_cache.get(key)
        if candidate is None:
            continue
        buckets = _candidate_buckets(candidate)
        row = {
            "candidate_id": f"{match.source_file}:{match.source_row}",
            "source_file": match.source_file,
            "source_row": match.source_row,
            "date": match.match_date.isoformat(),
            "league": match.league,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "outcome": candidate["outcome"],
            "probability": float(candidate["probability"]),
            "conservative_probability": float(candidate["conservative_probability"]),
            "odds": float(candidate["odds"]),
            "raw_odds": float(candidate["raw_odds"]),
            "conservative_ev_pct": float(candidate["conservative_ev"]) * 100.0,
            "reference_dispersion": float(candidate["reference_dispersion"]),
            "reference_bookmakers": len(candidate["reference_bookmakers"]),
            "execution_cost_rate": float(candidate["execution_cost_rate"]),
            "execution_bookmaker": candidate["execution_bookmaker"],
            "odds_band": buckets[1].split(":", 1)[1],
            "source_type": buckets[2].split(":", 1)[1],
        }
        row.update(market_structure_features(row))
        if include_closing_target:
            quality = _closing_price_quality(match, candidate, strategy)
            if quality["closing_edge_pct"] is None:
                continue
            row["closing_edge_pct"] = float(quality["closing_edge_pct"])
            row["actual_outcome"] = match.actual_outcome
            row["unit_profit"] = (
                float(candidate["odds"]) - 1.0
                if match.actual_outcome == candidate["outcome"] else -1.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _pipeline(
    alpha: float, numeric_features: tuple[str, ...], categorical_features: tuple[str, ...],
) -> Pipeline:
    transform = ColumnTransformer((
        ("numeric", StandardScaler(), list(numeric_features)),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), list(categorical_features)),
    ))
    return Pipeline((
        ("features", transform),
        ("ridge", Ridge(alpha=alpha)),
    ))


def _rmse(actual: pd.Series, predicted: Any) -> float:
    errors = actual.to_numpy(dtype=float) - predicted
    return math.sqrt(float((errors * errors).mean()))


def fit_ranker(
    training: pd.DataFrame, validation_start: date, policy: RankerPolicy,
    selection_objective: str = "profit_tuned_cap", fixed_maximum_odds: float = 5.0,
    numeric_features: tuple[str, ...] = NUMERIC_FEATURES,
    categorical_features: tuple[str, ...] = CATEGORICAL_FEATURES,
) -> FittedRanker | None:
    dates = pd.to_datetime(training["date"]).dt.date
    inner_train = training.loc[dates < validation_start].copy()
    validation = training.loc[dates >= validation_start].copy()
    if len(inner_train) < 100 or len(validation) < policy.minimum_inner_validation_positions:
        return None

    diagnostics: list[dict[str, Any]] = []
    eligible: list[tuple[tuple[float, float, int, float], float, float, float, float]] = []
    odds_caps = MAXIMUM_ODDS_CAPS if selection_objective == "profit_tuned_cap" else (fixed_maximum_odds,)
    for alpha in ALPHAS:
        model = _pipeline(alpha, numeric_features, categorical_features)
        model.fit(inner_train, inner_train["closing_edge_pct"])
        predicted = model.predict(validation)
        rmse = _rmse(validation["closing_edge_pct"], predicted)
        for margin in SAFETY_MARGINS:
            lower = predicted - margin * rmse
            for maximum_odds in odds_caps:
                selected = validation.loc[
                    (lower >= MINIMUM_LOWER_CLV_PCT)
                    & (validation["odds"].to_numpy(dtype=float) <= maximum_odds)
                ]
                mean_clv = float(selected["closing_edge_pct"].mean()) if len(selected) else None
                positive_rate = float((selected["closing_edge_pct"] > 0).mean()) if len(selected) else None
                flat_profit = float(selected["unit_profit"].sum()) if len(selected) else 0.0
                payoff_scale = math.sqrt(float((selected["unit_profit"] ** 2).sum())) if len(selected) else 0.0
                risk_adjusted_profit = flat_profit / payoff_scale if payoff_scale else 0.0
                clv_passed = (
                    len(selected) >= policy.minimum_inner_validation_positions
                    and mean_clv is not None and mean_clv > 0
                    and positive_rate is not None
                    and positive_rate >= policy.minimum_inner_positive_clv_rate
                )
                passed = clv_passed and (
                    selection_objective != "profit_tuned_cap"
                    or (flat_profit > 0 and risk_adjusted_profit > 0)
                )
                diagnostics.append({
                    "alpha": alpha,
                    "safety_margin": margin,
                    "maximum_odds": maximum_odds,
                    "validation_candidates": len(validation),
                    "selected": len(selected),
                    "rmse_pct": round(rmse, 4),
                    "average_closing_edge_pct": round(mean_clv, 4) if mean_clv is not None else None,
                    "positive_clv_rate": round(positive_rate, 4) if positive_rate is not None else None,
                    "flat_unit_profit": round(flat_profit, 4),
                    "risk_adjusted_profit": round(risk_adjusted_profit, 4),
                    "eligible": passed,
                })
                if passed:
                    clv_score = float(mean_clv) * math.sqrt(len(selected))
                    score = (
                        (risk_adjusted_profit, clv_score, len(selected), -rmse)
                        if selection_objective == "profit_tuned_cap"
                        else (clv_score, float(mean_clv), len(selected), -rmse)
                    )
                    eligible.append((
                        score,
                        alpha, margin, maximum_odds, rmse,
                    ))
    if not eligible:
        return None

    _score, alpha, margin, maximum_odds, validation_rmse = max(eligible, key=lambda row: row[0])
    final_model = _pipeline(alpha, numeric_features, categorical_features)
    final_model.fit(training, training["closing_edge_pct"])
    return FittedRanker(
        final_model, alpha, margin, maximum_odds, validation_rmse, diagnostics,
        numeric_features, categorical_features,
    )


def freeze_decisions(
    opening_candidates: pd.DataFrame, fitted: FittedRanker, policy: RankerPolicy,
) -> list[dict[str, Any]]:
    if opening_candidates.empty:
        return []
    frame = opening_candidates.copy()
    frame["predicted_closing_edge_pct"] = fitted.model.predict(frame)
    frame["lower_closing_edge_pct"] = (
        frame["predicted_closing_edge_pct"] - fitted.safety_margin * fitted.validation_rmse_pct
    )
    frame = frame.loc[
        (frame["lower_closing_edge_pct"] >= MINIMUM_LOWER_CLV_PCT)
        & (frame["odds"] <= fitted.maximum_odds)
    ].copy()
    frame.sort_values(
        ["date", "lower_closing_edge_pct", "candidate_id"],
        ascending=[True, False, True], inplace=True,
    )

    frozen: list[dict[str, Any]] = []
    for match_date, daily in frame.groupby("date", sort=True):
        remaining = policy.daily_budget
        for row in daily.to_dict("records"):
            odds = float(row["odds"])
            lower_edge = float(row["lower_closing_edge_pct"]) / 100.0
            probability = min(0.99, (1.0 + lower_edge) / odds)
            full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
            stake = round(min(
                policy.maximum_single_stake,
                remaining,
                policy.daily_budget * policy.kelly_fraction * full_kelly,
            ), 2)
            if stake < 0.10:
                continue
            remaining = round(remaining - stake, 2)
            frozen.append({
                **row,
                "stake": stake,
                "estimated_probability_from_lower_clv": probability,
                "decision_frozen_before_closing_and_result": True,
            })
    return frozen


def settle_frozen_decisions(
    frozen: list[dict[str, Any]], matches_by_id: dict[str, HistoricalMatch], strategy: Strategy,
) -> list[dict[str, Any]]:
    settled: list[dict[str, Any]] = []
    for decision in frozen:
        match = matches_by_id[decision["candidate_id"]]
        candidate = {
            "outcome": decision["outcome"],
            "odds": decision["odds"],
        }
        quality = _closing_price_quality(match, candidate, strategy)
        won = match.actual_outcome == decision["outcome"]
        stake, odds = float(decision["stake"]), float(decision["odds"])
        profit = round(stake * (odds - 1.0) if won else -stake, 2)
        settled.append({
            **decision,
            **quality,
            "actual_outcome": match.actual_outcome,
            "won": won,
            "profit": profit,
        })
    return settled


def _daily_ledger(start: date, end: date, positions: list[dict[str, Any]], budget: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in positions:
        grouped.setdefault(str(row["date"]), []).append(row)
    ledger = []
    cumulative = peak = 0.0
    current = start
    while current <= end:
        rows = grouped.get(current.isoformat(), [])
        staked = round(sum(float(row["stake"]) for row in rows), 2)
        profit = round(sum(float(row["profit"]) for row in rows), 2)
        cumulative = round(cumulative + profit, 2)
        peak = max(peak, cumulative)
        ledger.append({
            "date": current.isoformat(), "bets": len(rows), "staked": staked,
            "profit": profit, "cumulative_profit": cumulative,
            "drawdown": round(peak - cumulative, 2),
            "cash_reserved": round(budget - staked, 2),
        })
        current += timedelta(days=1)
    return ledger


def rolling_v6(
    output_dir: Path, fold_count: int = 18, exchange_commission_rate: float = 0.025,
    minimum_month_rows: int = 300, matches: list[HistoricalMatch] | None = None,
    selection_objective: str = "profit_tuned_cap", fixed_maximum_odds: float = 5.0,
    feature_profile: str = "full",
    training_months: int = 6, validation_months: int = 2,
    prediction_profile: str = "aligned",
) -> dict[str, Any]:
    rows = matches if matches is not None else load_matches()
    latest_start, _latest_end = latest_complete_month(rows, minimum_month_rows)
    folds = [
        window for window in complete_months(rows, minimum_month_rows) if window[0] < latest_start
    ][-max(1, fold_count):]
    strategy = broad_strategy(exchange_commission_rate)
    policy = RankerPolicy()
    numeric_features, categorical_features = _feature_contract(feature_profile)
    cache = build_candidate_cache(rows, strategy)
    matches_by_id = {f"{row.source_file}:{row.source_row}": row for row in rows}
    monthly: list[dict[str, Any]] = []
    all_positions: list[dict[str, Any]] = []
    all_daily: list[dict[str, Any]] = []

    for test_start, test_end in folds:
        train_start = _months_before(test_start, training_months)
        train_end = test_start - timedelta(days=1)
        validation_start = _months_before(test_start, validation_months)
        training = _opening_rows(rows, strategy, cache, train_start, train_end, True)
        fitted = fit_ranker(
            training, validation_start, policy, selection_objective, fixed_maximum_odds,
            numeric_features, categorical_features,
        )
        if fitted is None:
            monthly.append({
                "month": test_start.strftime("%Y-%m"),
                "train_window": f"{train_start}..{train_end}",
                "status": "ABSTAIN_INNER_VALIDATION", "training_candidates": len(training),
                "bets": 0, "active_days": 0, "staked": 0.0, "profit": 0.0,
                "roi_pct": 0.0, "available_capacity": (test_end - test_start).days * 100.0 + 100.0,
            })
            continue

        # The test-month frame deliberately has no closing target or result column.
        opening_test = _opening_rows(rows, strategy, cache, test_start, test_end, False)
        if prediction_profile == "unknown_league" and "league" in opening_test:
            opening_test["league"] = "__UNKNOWN_LIVE_LEAGUE__"
        frozen = freeze_decisions(opening_test, fitted, policy)
        settled = settle_frozen_decisions(frozen, matches_by_id, strategy)
        ledger = _daily_ledger(test_start, test_end, settled, policy.daily_budget)
        all_positions.extend({"test_month": test_start.strftime("%Y-%m"), **row} for row in settled)
        all_daily.extend({"test_month": test_start.strftime("%Y-%m"), **row} for row in ledger)
        staked = round(sum(float(row["stake"]) for row in settled), 2)
        profit = round(sum(float(row["profit"]) for row in settled), 2)
        clv = [float(row["closing_edge_pct"]) for row in settled if row["closing_edge_pct"] is not None]
        monthly.append({
            "month": test_start.strftime("%Y-%m"),
            "train_window": f"{train_start}..{train_end}", "status": "FROZEN_MODEL_EVALUATED",
            "training_candidates": len(training), "test_candidates": len(opening_test),
            "alpha": fitted.alpha, "safety_margin": fitted.safety_margin,
            "maximum_odds": fitted.maximum_odds,
            "validation_rmse_pct": round(fitted.validation_rmse_pct, 4),
            "inner_validation": fitted.validation_diagnostics,
            "bets": len(settled), "active_days": sum(row["bets"] > 0 for row in ledger),
            "staked": staked, "profit": profit,
            "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
            "average_closing_edge_pct": round(sum(clv) / len(clv), 4) if clv else None,
            "positive_clv_rate": round(sum(value > 0 for value in clv) / len(clv), 4) if clv else None,
            "outcome_counts": dict(Counter(row["outcome"] for row in settled)),
            "available_capacity": len(ledger) * policy.daily_budget,
        })

    staked = round(sum(float(row["staked"]) for row in monthly), 2)
    profit = round(sum(float(row["profit"]) for row in monthly), 2)
    capacity = round(sum(float(row["available_capacity"]) for row in monthly), 2)
    active = [row for row in monthly if int(row["bets"]) > 0]
    outcomes = Counter(str(row["outcome"]) for row in all_positions)
    concentration = max(outcomes.values(), default=0) / len(all_positions) if all_positions else 0.0
    clv = [float(row["closing_edge_pct"]) for row in all_positions if row["closing_edge_pct"] is not None]
    average_clv = sum(clv) / len(clv) if clv else None
    positive_clv = sum(value > 0 for value in clv) / len(clv) if clv else None
    bootstrap = _monthly_bootstrap(monthly)
    utilization = staked / capacity * 100.0 if capacity else 0.0
    active_days = sum(int(row.get("active_days") or 0) for row in monthly)
    active_capacity = active_days * policy.daily_budget
    active_day_utilization = staked / active_capacity * 100.0 if active_capacity else 0.0
    reasons = []
    warnings = []
    if len(monthly) < 12: reasons.append("monthly_folds<12")
    if len(active) < 8: reasons.append("active_months<8")
    if len(all_positions) < 100: reasons.append("bets<100")
    if active and sum(float(row["profit"]) > 0 for row in active) / len(active) < 0.60:
        reasons.append("positive_active_month_rate<60pct")
    if profit <= 0: reasons.append("aggregate_profit<=0")
    if bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0:
        reasons.append("monthly_bootstrap_roi_lower_95<=0")
    if average_clv is None or average_clv <= 0: reasons.append("average_closing_edge<=0")
    if positive_clv is None or positive_clv < 0.55: reasons.append("positive_clv_rate<55pct")
    if concentration > 0.75: reasons.append("selected_outcome_concentration>75pct")
    if utilization < 0.50: warnings.append("calendar_capacity_utilization<0.5pct")
    if active_day_utilization < 0.50: warnings.append("active_day_capacity_utilization<0.5pct")

    payload = {
        "method": "Ridge CLV ranker; trailing train window, trailing inner validation, immediate next month evaluate",
        "training_months": training_months,
        "validation_months": validation_months,
        "prediction_profile": prediction_profile,
        "feature_contract": {
            "profile": feature_profile,
            "numeric": list(numeric_features), "categorical": list(categorical_features),
            "ridge_model_forbidden": ["actual_outcome", "unit_profit", "won", "profit"],
            "test_decision_frame_forbidden": ["actual_outcome", "unit_profit", "closing_edge_pct"],
        },
        "strategy": asdict(strategy), "policy": asdict(policy),
        "selection_objective": selection_objective,
        "fixed_maximum_odds": fixed_maximum_odds if selection_objective == "clv_fixed_cap" else None,
        "exchange_commission_rate": exchange_commission_rate,
        "latest_sealed_month_excluded": latest_start.strftime("%Y-%m"),
        "folds": len(monthly), "active_months": len(active),
        "positive_active_months": sum(float(row["profit"]) > 0 for row in active),
        "bets": len(all_positions), "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "available_capacity": capacity, "capital_utilization_pct": round(utilization, 4),
        "active_days": active_days, "active_day_capacity": active_capacity,
        "active_day_capital_utilization_pct": round(active_day_utilization, 4),
        "outcome_counts": dict(outcomes),
        "maximum_outcome_concentration_pct": round(concentration * 100.0, 2),
        "average_closing_edge_pct": round(average_clv, 4) if average_clv is not None else None,
        "positive_clv_rate": round(positive_clv, 4) if positive_clv is not None else None,
        "monthly_bootstrap_roi": bootstrap,
        "decision": "ROLLING_RESEARCH_SURVIVOR" if not reasons else "ROLLING_REJECTED",
        "decision_reasons": reasons, "warnings": warnings,
        "research_stage": "POST_HOC_EXPLORATORY",
        "live_promotion_allowed": False,
        "live_promotion_blocker": "The algorithm was developed after inspecting these historical folds; prospective T-1 confirmation is required.",
        "monthly": monthly,
        "guardrail": "Exploratory historical evidence only. No live order or automatic promotion is possible.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(monthly).drop(columns=["inner_validation"], errors="ignore").to_csv(
        output_dir / "monthly.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(all_daily).to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_positions).to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    return payload


def sealed_latest_month_v6(
    output_dir: Path, exchange_commission_rate: float = 0.025,
    minimum_month_rows: int = 300, matches: list[HistoricalMatch] | None = None,
    fixed_maximum_odds: float = 5.0, feature_profile: str = "market_structure",
    training_months: int = 6, validation_months: int = 2,
) -> dict[str, Any]:
    """Evaluate the latest complete month once, after freezing all test decisions."""
    rows = matches if matches is not None else load_matches()
    test_start, test_end = latest_complete_month(rows, minimum_month_rows)
    train_start = _months_before(test_start, training_months)
    train_end = test_start - timedelta(days=1)
    validation_start = _months_before(test_start, validation_months)
    strategy = broad_strategy(exchange_commission_rate)
    policy = RankerPolicy()
    numeric_features, categorical_features = _feature_contract(feature_profile)
    cache = build_candidate_cache(rows, strategy)
    training = _opening_rows(rows, strategy, cache, train_start, train_end, True)
    fitted = fit_ranker(
        training, validation_start, policy, "clv_fixed_cap", fixed_maximum_odds,
        numeric_features, categorical_features,
    )
    opening_test = _opening_rows(rows, strategy, cache, test_start, test_end, False)
    forbidden_present = sorted(
        {"actual_outcome", "unit_profit", "closing_edge_pct", "won", "profit"}
        & set(opening_test.columns)
    )
    if forbidden_present:
        raise ValueError(f"sealed test decision frame contains future fields: {forbidden_present}")

    frozen = freeze_decisions(opening_test, fitted, policy) if fitted is not None else []
    frozen_signature = hashlib.sha256(json.dumps([
        {
            "candidate_id": row["candidate_id"], "date": row["date"],
            "outcome": row["outcome"], "odds": row["odds"], "stake": row["stake"],
            "predicted_closing_edge_pct": row["predicted_closing_edge_pct"],
            "lower_closing_edge_pct": row["lower_closing_edge_pct"],
        }
        for row in frozen
    ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    matches_by_id = {f"{row.source_file}:{row.source_row}": row for row in rows}
    settled = settle_frozen_decisions(frozen, matches_by_id, strategy)
    ledger = _daily_ledger(test_start, test_end, settled, policy.daily_budget)
    staked = round(sum(float(row["stake"]) for row in settled), 2)
    profit = round(sum(float(row["profit"]) for row in settled), 2)
    clv = [float(row["closing_edge_pct"]) for row in settled if row["closing_edge_pct"] is not None]
    payload = {
        "method": "single sealed latest-complete-calendar-month holdout",
        "research_stage": "SEALED_HOLDOUT_EVALUATED",
        "feature_profile": feature_profile,
        "exchange_commission_rate": exchange_commission_rate,
        "period_start": test_start.isoformat(), "period_end": test_end.isoformat(),
        "training_window": f"{train_start}..{train_end}",
        "inner_validation_start": validation_start.isoformat(),
        "inner_gate_passed": fitted is not None,
        "training_candidates": len(training), "test_candidates": len(opening_test),
        "bets": len(settled), "active_days": sum(row["bets"] > 0 for row in ledger),
        "daily_budget_limit": policy.daily_budget,
        "maximum_daily_stake": max((float(row["staked"]) for row in ledger), default=0.0),
        "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "ending_equity_change": profit,
        "maximum_drawdown": max((float(row["drawdown"]) for row in ledger), default=0.0),
        "average_closing_edge_pct": round(sum(clv) / len(clv), 4) if clv else None,
        "positive_clv_rate": round(sum(value > 0 for value in clv) / len(clv), 4) if clv else None,
        "outcome_counts": dict(Counter(row["outcome"] for row in settled)),
        "frozen_decision_sha256": frozen_signature,
        "anti_leakage": {
            "test_decision_frame_forbidden_fields": [
                "actual_outcome", "unit_profit", "closing_edge_pct", "won", "profit"
            ],
            "forbidden_fields_present": forbidden_present,
            "decisions_and_stakes_frozen_before_settlement": True,
            "test_month_used_for_model_or_policy_selection": False,
        },
        "daily": ledger,
        "guardrail": "Historical sealed holdout only; this result cannot authorize real orders.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(ledger).to_csv(output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(settled).to_csv(output_dir / "positions.csv", index=False, encoding="utf-8-sig")
    return payload


def export_live_ranker(
    output_path: Path, exchange_commission_rate: float = 0.05,
    fixed_maximum_odds: float = 5.0, matches: list[HistoricalMatch] | None = None,
    training_end: date | None = None,
    feature_profile: str = "full",
    training_months: int = 6, validation_months: int = 2,
) -> dict[str, Any]:
    numeric_features, categorical_features = _feature_contract(feature_profile)
    rows = matches if matches is not None else load_matches()
    strategy = broad_strategy(exchange_commission_rate)
    cache = build_candidate_cache(rows, strategy)
    training_end = training_end or max(row.match_date for row in rows)
    next_month = training_end.replace(day=1) + timedelta(days=32)
    training_start = _months_before(next_month, training_months)
    validation_start = _months_before(next_month, validation_months)
    training = _opening_rows(rows, strategy, cache, training_start, training_end, True)
    fitted = fit_ranker(
        training, validation_start, RankerPolicy(), "clv_fixed_cap", fixed_maximum_odds,
        numeric_features, categorical_features,
    )
    if fitted is None:
        raise ValueError("latest six-month window did not pass the frozen inner CLV gate")

    transform = fitted.model.named_steps["features"]
    ridge = fitted.model.named_steps["ridge"]
    scaler = transform.named_transformers_["numeric"]
    encoder = transform.named_transformers_["categorical"]
    coefficients = ridge.coef_.tolist()
    numeric_count = len(fitted.numeric_features)
    numeric_scaled = coefficients[:numeric_count]
    numeric_coefficients = {
        name: float(coefficient) / float(scale)
        for name, coefficient, scale in zip(fitted.numeric_features, numeric_scaled, scaler.scale_)
    }
    intercept = float(ridge.intercept_) - sum(
        float(coefficient) * float(mean) / float(scale)
        for coefficient, mean, scale in zip(numeric_scaled, scaler.mean_, scaler.scale_)
    )
    categorical_coefficients: dict[str, dict[str, float]] = {}
    offset = numeric_count
    for field, categories in zip(fitted.categorical_features, encoder.categories_):
        values = coefficients[offset:offset + len(categories)]
        categorical_coefficients[field] = {
            str(category): float(coefficient) for category, coefficient in zip(categories, values)
        }
        offset += len(categories)

    parity_sample = training.head(200)
    pipeline_scores = fitted.model.predict(parity_sample)
    json_scores = []
    for row in parity_sample.to_dict("records"):
        score = intercept + sum(
            numeric_coefficients[field] * float(row[field]) for field in fitted.numeric_features
        )
        score += sum(
            categorical_coefficients[field].get(str(row[field]), 0.0)
            for field in fitted.categorical_features
        )
        json_scores.append(score)
    parity_error = max(
        (abs(float(expected) - actual) for expected, actual in zip(pipeline_scores, json_scores)),
        default=0.0,
    )
    if parity_error > 1e-8:
        raise ValueError(f"JSON model export parity failed: {parity_error}")

    model_version = {
        "full": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
        "portable": "clv-ridge-v6.4-portable-fixed-cap5-prospective-shadow",
        "market_structure": "clv-ridge-v6.6-market-structure-fixed-cap5-prospective-shadow",
    }[feature_profile]
    payload = {
        "model_version": model_version,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "training_window": f"{training_start}..{training_end}",
        "training_months": training_months,
        "validation_months": validation_months,
        "training_candidates": len(training),
        "training_result_used_as_feature": False,
        "target": "closing_edge_pct",
        "alpha": fitted.alpha,
        "safety_margin": fitted.safety_margin,
        "validation_rmse_pct": fitted.validation_rmse_pct,
        "minimum_lower_clv_pct": MINIMUM_LOWER_CLV_PCT,
        "maximum_odds": fitted.maximum_odds,
        "exchange_commission_rate": exchange_commission_rate,
        "slippage_rate": strategy.slippage_rate,
        "intercept": intercept,
        "numeric_features": list(fitted.numeric_features),
        "feature_profile": feature_profile,
        "categorical_features": list(fitted.categorical_features),
        "numeric_coefficients": numeric_coefficients,
        "categorical_coefficients": categorical_coefficients,
        "unknown_category_policy": "zero_coefficient",
        "export_parity_sample": len(parity_sample),
        "export_parity_max_abs_error": parity_error,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["model_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "clv_ridge_walk_forward_v6")
    parser.add_argument("--fold-count", type=int, default=18)
    parser.add_argument("--exchange-commission-rate", type=float, default=0.025)
    parser.add_argument(
        "--selection-objective",
        choices=("profit_tuned_cap", "clv_fixed_cap"),
        default="profit_tuned_cap",
    )
    parser.add_argument("--fixed-maximum-odds", type=float, default=5.0)
    parser.add_argument("--export-live-model", type=Path)
    parser.add_argument("--sealed-latest-month", action="store_true")
    parser.add_argument("--model-training-end", type=date.fromisoformat)
    parser.add_argument(
        "--feature-profile", choices=("full", "portable", "market_structure"), default="full"
    )
    parser.add_argument("--training-months", type=int, default=6)
    parser.add_argument("--validation-months", type=int, default=2)
    parser.add_argument(
        "--prediction-profile", choices=("aligned", "unknown_league"), default="aligned"
    )
    args = parser.parse_args()
    report = (
        sealed_latest_month_v6(
            args.output_dir, args.exchange_commission_rate,
            fixed_maximum_odds=args.fixed_maximum_odds,
            feature_profile=args.feature_profile,
            training_months=args.training_months, validation_months=args.validation_months,
        ) if args.sealed_latest_month else
        export_live_ranker(
            args.export_live_model, args.exchange_commission_rate, args.fixed_maximum_odds,
            training_end=args.model_training_end, feature_profile=args.feature_profile,
            training_months=args.training_months, validation_months=args.validation_months,
        ) if args.export_live_model else
        rolling_v6(
            args.output_dir, args.fold_count, args.exchange_commission_rate,
            selection_objective=args.selection_objective,
            fixed_maximum_odds=args.fixed_maximum_odds,
            feature_profile=args.feature_profile,
            training_months=args.training_months,
            validation_months=args.validation_months,
            prediction_profile=args.prediction_profile,
        )
    )
    print(json.dumps({key: value for key, value in report.items() if key != "monthly"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
