from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import DEFAULT_SEASONS, load_seasons  # noqa: E402
from market_bias_diagnostics import ODDS_SOURCE_COLUMNS, build_market_frame  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402
from walk_forward_residual_strategy import build_feature_history  # noqa: E402


FEATURE_COLUMNS = (
    "market_probability",
    "log_odds",
    "is_draw",
    "is_home",
    "league_draw_rate",
    "league_prior_matches_scaled",
    "form_points_diff",
    "abs_form_points_diff",
    "form_goal_diff_delta",
    "abs_form_goal_diff_delta",
    "season_points_per_match_delta",
    "abs_season_points_per_match_delta",
    "season_goal_diff_per_match_delta",
    "abs_season_goal_diff_per_match_delta",
    "rest_days_delta",
    "lambda_total",
    "lambda_diff",
)

I2_DRAW_RULE = "I2_draw_2p8_3p5"
SP1_HOME_RULE = "SP1_home_market_ge_55"


@dataclass(frozen=True)
class FeatureFilterConfig:
    odds_source: str
    train_months: int
    min_train_rows: int
    min_predicted_ev: float
    max_bets_per_day: int
    ridge: float
    residual_cap: float = 0.08
    selected_rules: tuple[str, ...] = (I2_DRAW_RULE, SP1_HOME_RULE)
    validation_months: int = 0
    min_validation_rows: int = 120
    require_probability_improvement: bool = False
    min_odds: float = 1.01
    max_odds: float = 100.0
    min_validation_selections: int = 0
    require_validation_tail_edge: bool = False

    @property
    def label(self) -> str:
        ev = str(self.min_predicted_ev).replace("-", "neg").replace(".", "p")
        rules = "rules" + "_".join(
            rule.lower()
            .replace("[", "")
            .replace("]", "")
            .replace(")", "")
            .replace(",", "_")
            .replace(".", "p")
            for rule in self.selected_rules
        )
        validation = f"_val{self.validation_months}" if self.require_probability_improvement else ""
        tail = (
            f"_tail{self.min_validation_selections}_odds{self.min_odds:g}_{self.max_odds:g}"
            if self.require_validation_tail_edge else ""
        )
        return (
            f"{self.odds_source}_{rules}_train{self.train_months}_n{self.min_train_rows}"
            f"_ev{ev}_top{self.max_bets_per_day}_ridge{self.ridge:g}_cap{self.residual_cap:g}{validation}{tail}"
        )


def _season(date_text: str) -> str:
    year = int(date_text[:4])
    month = int(date_text[5:7])
    start = year if month >= 7 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _candidate_rule(row: pd.Series) -> str | None:
    if row["league"] == "I2" and row["outcome"] == "draw" and row["odds_bucket"] == "[2.8,3.5)":
        return I2_DRAW_RULE
    if row["league"] == "SP1" and row["outcome"] == "home" and row["market_prob_bucket"] == "[0.55,1.00]":
        return SP1_HOME_RULE
    return None


def _prepare_candidate_features(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["log_odds"] = np.log(output["odds"].astype(float))
    output["is_draw"] = (output["outcome"] == "draw").astype(float)
    output["is_home"] = (output["outcome"] == "home").astype(float)
    output["league_prior_matches_scaled"] = output["league_prior_matches"].astype(float) / 1000.0
    for column in (
        "form_points_diff",
        "form_goal_diff_delta",
        "season_points_per_match_delta",
        "season_goal_diff_per_match_delta",
    ):
        output[f"abs_{column}"] = output[column].astype(float).abs()
    for column in FEATURE_COLUMNS:
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0.0)
    return output


def build_feature_enriched_candidates(
    seasons: tuple[str, ...],
    odds_source: str,
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
    candidates["rule_label"] = candidates.apply(_candidate_rule, axis=1)
    candidates = candidates[candidates["rule_label"].notna()].copy()
    candidates = candidates.merge(
        features[join_columns + feature_columns],
        on=join_columns,
        how="inner",
        validate="many_to_one",
    )
    candidates["bet_date"] = pd.to_datetime(candidates["date"])
    candidates["month"] = candidates["bet_date"].dt.to_period("M").astype(str)
    candidates["season"] = candidates["date"].map(_season)
    candidates["unit_profit"] = candidates["odds"].astype(float).where(candidates["won"], 0.0) - 1.0
    return _prepare_candidate_features(candidates).sort_values(["bet_date", "rule_label", "odds_source"]).reset_index(drop=True)


def training_window(frame: pd.DataFrame, period: pd.Period, train_months: int) -> pd.DataFrame:
    test_start = period.start_time.normalize()
    train_start = test_start - pd.DateOffset(months=train_months)
    return frame[(frame["bet_date"] >= train_start) & (frame["bet_date"] < test_start)].copy()


def fit_ridge_probability_model(frame: pd.DataFrame, feature_columns: tuple[str, ...] = FEATURE_COLUMNS,
                                ridge: float = 25.0) -> tuple[np.ndarray, pd.Series, pd.Series]:
    if frame.empty:
        raise ValueError("Cannot fit model on an empty frame")
    x = frame.loc[:, feature_columns].astype(float)
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, 1.0)
    matrix = np.column_stack([np.ones(len(x)), ((x - means) / stds).to_numpy(float)])
    y = frame["won"].astype(float).to_numpy() - frame["market_probability"].astype(float).to_numpy()
    penalty = np.eye(matrix.shape[1]) * ridge
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(matrix.T @ matrix + penalty, matrix.T @ y)
    return coefficients, means, stds


def predict_probability(frame: pd.DataFrame, coefficients: np.ndarray, means: pd.Series, stds: pd.Series,
                        feature_columns: tuple[str, ...] = FEATURE_COLUMNS,
                        residual_cap: float = 0.08) -> np.ndarray:
    x = frame.loc[:, feature_columns].astype(float)
    matrix = np.column_stack([np.ones(len(x)), ((x - means) / stds).to_numpy(float)])
    residual = np.clip(matrix @ coefficients, -residual_cap, residual_cap)
    return np.clip(frame["market_probability"].astype(float).to_numpy() + residual, 0.01, 0.98)


def normalize_complete_three_way_probabilities(frame: pd.DataFrame, probabilities: np.ndarray) -> np.ndarray:
    """Project complete home/draw/away candidate sets back onto the probability simplex."""
    output = pd.Series(probabilities, index=frame.index, dtype=float)
    match_columns = ["date", "league", "home_team", "away_team"]
    if any(column not in frame.columns for column in match_columns) or "outcome" not in frame.columns:
        return output.to_numpy()
    work = frame.loc[:, match_columns + ["outcome"]].copy()
    work["_probability"] = output
    for _, group in work.groupby(match_columns, sort=False):
        if len(group) != 3 or set(group["outcome"].astype(str)) != {"home", "draw", "away"}:
            continue
        total = float(group["_probability"].sum())
        if total > 0:
            output.loc[group.index] = group["_probability"] / total
    return output.to_numpy()


def multiclass_probability_metrics(frame: pd.DataFrame, probability_column: str) -> dict[str, float | int]:
    match_columns = ["date", "league", "home_team", "away_team"]
    if frame.empty:
        return {"matches": 0, "log_loss": 0.0, "brier": 0.0}
    work = frame.loc[:, match_columns + ["outcome", "won", probability_column]].copy()
    grouped = work.groupby(match_columns, sort=False)
    complete = grouped["outcome"].transform("size").eq(3) & grouped["outcome"].transform("nunique").eq(3)
    work = work[complete].copy()
    if work.empty:
        return {"matches": 0, "log_loss": 0.0, "brier": 0.0}
    probabilities = work[probability_column].astype(float).clip(0.001, 0.999)
    probabilities = probabilities / probabilities.groupby(
        [work[column] for column in match_columns], sort=False
    ).transform("sum")
    outcomes = work["won"].astype(float)
    matches = int(work.groupby(match_columns, sort=False).ngroups)
    log_loss = float(-(outcomes * np.log(probabilities)).sum() / matches)
    brier = float(((probabilities - outcomes) ** 2).sum() / matches)
    return {
        "matches": matches,
        "log_loss": round(log_loss, 6),
        "brier": round(brier, 6),
    }


def select_scored_candidates(frame: pd.DataFrame, config: FeatureFilterConfig) -> pd.DataFrame:
    selected = frame[
        frame["rule_label"].isin(config.selected_rules)
        & (frame["predicted_ev"] >= config.min_predicted_ev)
        & (frame["odds"].astype(float) >= config.min_odds)
        & (frame["odds"].astype(float) <= config.max_odds)
    ].copy()
    if config.max_bets_per_day > 0 and not selected.empty:
        selected = (
            selected.sort_values(["date", "predicted_ev"], ascending=[True, False])
            .groupby("date", as_index=False, group_keys=False)
            .head(config.max_bets_per_day)
        )
    return selected


def prior_probability_improvement_gate(
    train: pd.DataFrame,
    period: pd.Period,
    config: FeatureFilterConfig,
) -> dict[str, Any]:
    if not config.require_probability_improvement or config.validation_months <= 0:
        return {"passed": True, "reason": "disabled"}
    validation_start = period.start_time.normalize() - pd.DateOffset(months=config.validation_months)
    fit = train[train["bet_date"] < validation_start].copy()
    validation = train[train["bet_date"] >= validation_start].copy()
    if len(fit) < config.min_train_rows or len(validation) < config.min_validation_rows:
        return {
            "passed": False,
            "reason": "insufficient_prior_validation_rows",
            "fit_rows": int(len(fit)),
            "validation_rows": int(len(validation)),
        }
    coefficients, means, stds = fit_ridge_probability_model(fit, ridge=config.ridge)
    validation["model_probability"] = normalize_complete_three_way_probabilities(
        validation,
        predict_probability(validation, coefficients, means, stds, residual_cap=config.residual_cap),
    )
    market = multiclass_probability_metrics(validation, "market_probability")
    model = multiclass_probability_metrics(validation, "model_probability")
    probability_passed = (
        model["matches"] > 0
        and model["log_loss"] < market["log_loss"]
        and model["brier"] < market["brier"]
    )
    validation["predicted_probability"] = validation["model_probability"]
    validation["predicted_ev"] = (
        validation["predicted_probability"] * validation["odds"].astype(float) - 1.0
    )
    tail = select_scored_candidates(validation, config)
    tail_profit = float(tail["unit_profit"].sum()) if not tail.empty else 0.0
    tail_hit_rate = float(tail["won"].astype(float).mean()) if not tail.empty else 0.0
    tail_market_probability = float(tail["market_probability"].mean()) if not tail.empty else 0.0
    tail_edge = tail_hit_rate - tail_market_probability
    tail_passed = (
        not config.require_validation_tail_edge
        or (
            len(tail) >= config.min_validation_selections
            and tail_profit > 0
            and tail_edge > 0
        )
    )
    passed = probability_passed and tail_passed
    if not probability_passed:
        reason = "model_did_not_beat_market_on_prior_validation"
    elif not tail_passed:
        reason = "selected_tail_did_not_show_prior_edge"
    else:
        reason = None
    return {
        "passed": passed,
        "reason": reason,
        "fit_rows": int(len(fit)),
        "validation_rows": int(len(validation)),
        "market": market,
        "model": model,
        "log_loss_improvement": round(float(market["log_loss"] - model["log_loss"]), 6),
        "brier_improvement": round(float(market["brier"] - model["brier"]), 6),
        "selected_tail": {
            "bets": int(len(tail)),
            "profit_units": round(tail_profit, 2),
            "hit_rate": round(tail_hit_rate, 6),
            "average_market_probability": round(tail_market_probability, 6),
            "edge_vs_market_probability": round(tail_edge, 6),
            "passed": tail_passed,
        },
    }


def export_scorer_artifact(candidates: pd.DataFrame, config: FeatureFilterConfig,
                           prediction_month: str) -> dict[str, Any]:
    """Freeze the no-leak residual scorer available before a future prediction month."""
    period = pd.Period(prediction_month, freq="M")
    train = training_window(candidates, period, config.train_months)
    if len(train) < config.min_train_rows:
        raise ValueError(
            f"Insufficient prior candidates for scorer export: {len(train)} < {config.min_train_rows}"
        )
    validation_gate = prior_probability_improvement_gate(train, period, config)
    if not validation_gate["passed"]:
        raise ValueError(f"Prior probability improvement gate failed: {validation_gate['reason']}")
    coefficients, means, stds = fit_ridge_probability_model(train, ridge=config.ridge)
    return {
        "artifact_type": "market_anchored_feature_residual_scorer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy_label": config.label,
        "prediction_month": prediction_month,
        "training_window": {
            "train_months": config.train_months,
            "first_date": train["date"].min(),
            "last_date": train["date"].max(),
            "rows": int(len(train)),
        },
        "selection": {
            "odds_source": config.odds_source,
            "selected_rules": list(config.selected_rules),
            "min_predicted_ev": config.min_predicted_ev,
            "max_bets_per_day": config.max_bets_per_day,
            "residual_cap": config.residual_cap,
            "ridge": config.ridge,
            "min_odds": config.min_odds,
            "max_odds": config.max_odds,
            "prior_probability_improvement_gate": validation_gate,
            "feature_columns": list(FEATURE_COLUMNS),
        },
        "model": {
            "target": "won - market_probability",
            "intercept_and_coefficients": [float(value) for value in coefficients.tolist()],
            "feature_means": {column: float(means[column]) for column in FEATURE_COLUMNS},
            "feature_stds": {column: float(stds[column]) for column in FEATURE_COLUMNS},
        },
        "deployment_notes": [
            "Only score matches whose feature columns are produced before kickoff.",
            "The scorer adjusts market probability by a bounded residual; it is not an unconstrained win-rate model.",
            "Use official-SP shadow validation before any production allocation.",
        ],
    }


def score_with_scorer_artifact(frame: pd.DataFrame, artifact: dict[str, Any]) -> pd.DataFrame:
    selection = artifact["selection"]
    model = artifact["model"]
    feature_columns = tuple(selection["feature_columns"])
    coefficients = np.array(model["intercept_and_coefficients"], dtype=float)
    means = pd.Series(model["feature_means"], dtype=float)
    stds = pd.Series(model["feature_stds"], dtype=float)
    output = frame.copy()
    output["predicted_probability"] = normalize_complete_three_way_probabilities(output, predict_probability(
        output,
        coefficients,
        means,
        stds,
        feature_columns=feature_columns,
        residual_cap=float(selection["residual_cap"]),
    ))
    output["predicted_ev"] = output["predicted_probability"] * output["odds"].astype(float) - 1.0
    output["passes_scorer"] = (
        output["rule_label"].isin(selection["selected_rules"])
        & (output["predicted_ev"] >= float(selection["min_predicted_ev"]))
        & (output["odds"].astype(float) >= float(selection.get("min_odds", 1.01)))
        & (output["odds"].astype(float) <= float(selection.get("max_odds", 100.0)))
    )
    return output


def walk_forward_feature_filter(candidates: pd.DataFrame, config: FeatureFilterConfig,
                                first_month: str, last_month: str) -> tuple[dict[str, Any], pd.DataFrame]:
    selected_months: list[pd.DataFrame] = []
    month_reports: list[dict[str, Any]] = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        test = candidates[candidates["month"] == str(period)].copy()
        train = training_window(candidates, period, config.train_months)
        if test.empty:
            month_reports.append({"month": str(period), "decision": "ABSTAIN", "reason": "no_candidates"})
            continue
        if len(train) < config.min_train_rows:
            month_reports.append({
                "month": str(period),
                "decision": "ABSTAIN",
                "reason": "insufficient_prior_candidates",
                "prior_candidates": int(len(train)),
                "candidate_count": int(len(test)),
            })
            continue
        validation_gate = prior_probability_improvement_gate(train, period, config)
        if not validation_gate["passed"]:
            month_reports.append({
                "month": str(period),
                "decision": "ABSTAIN",
                "reason": validation_gate["reason"],
                "prior_candidates": int(len(train)),
                "candidate_count": int(len(test)),
                "probability_validation": validation_gate,
            })
            continue
        coefficients, means, stds = fit_ridge_probability_model(train, ridge=config.ridge)
        test["predicted_probability"] = normalize_complete_three_way_probabilities(
            test,
            predict_probability(test, coefficients, means, stds, residual_cap=config.residual_cap),
        )
        test["predicted_ev"] = test["predicted_probability"] * test["odds"].astype(float) - 1.0
        selected = select_scored_candidates(test, config)
        selected["rule_label"] = config.label + "|" + selected["rule_label"].astype(str)
        selected_months.append(selected)
        month_reports.append({
            "month": str(period),
            "decision": "INVEST" if not selected.empty else "ABSTAIN",
            "reason": None if not selected.empty else "no_positive_feature_edge",
            "prior_candidates": int(len(train)),
            "candidate_count": int(len(test)),
            "selected": int(len(selected)),
            "mean_predicted_ev": round(float(selected["predicted_ev"].mean()), 4) if not selected.empty else 0.0,
            "probability_validation": validation_gate,
        })
    selected_all = pd.concat(selected_months, ignore_index=True) if selected_months else pd.DataFrame()
    summary = {
        "config": config.__dict__,
        "months": month_reports,
        "selected_candidates": int(len(selected_all)),
    }
    return summary, selected_all


def _score_config(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("stability_verdict") == "SHADOW_READY_RESEARCH_CANDIDATE",
        row["active_pass_rate"],
        row["passed_windows"],
        row["roi_pct"] > 0,
        row["roi_pct"],
        row["profit"],
        -row["max_drawdown"],
        row["bets"],
    )


def season_summary_from_bets(bets: pd.DataFrame) -> list[dict[str, Any]]:
    if bets.empty:
        return []
    frame = bets.copy()
    frame["season"] = frame["bet_date"].astype(str).map(_season)
    rows = []
    for season, group in frame.groupby("season"):
        staked = float(group["stake"].sum())
        profit = float(group["profit"].sum())
        rows.append({
            "season": season,
            "bets": int(len(group)),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        })
    return rows


def assess_feature_filter_row(row: dict[str, Any], *, min_bets: int = 250,
                              min_active_pass_rate: float = 0.60) -> tuple[str, list[str]]:
    reasons: list[str] = []
    profit = float(row.get("profit") or 0.0)
    drawdown = float(row.get("max_drawdown") or 0.0)
    latest_profit = float(row.get("latest_season_profit") or 0.0)
    if int(row.get("bets") or 0) < min_bets:
        reasons.append(f"bets<{min_bets}")
    if profit <= 0:
        reasons.append("profit<=0")
    if float(row.get("roi_pct") or 0.0) < 3.0:
        reasons.append("roi<3%")
    if drawdown > max(profit, 1.0):
        reasons.append("drawdown>profit")
    if int(row.get("positive_months") or 0) <= int(row.get("negative_months") or 0):
        reasons.append("positive_months<=negative_months")
    if int(row.get("positive_seasons") or 0) <= int(row.get("negative_seasons") or 0):
        reasons.append("positive_seasons<=negative_seasons")
    if int(row.get("latest_season_bets") or 0) < 20:
        reasons.append("latest_season_bets<20")
    if latest_profit < 0:
        reasons.append("latest_season_profit<0")
    if float(row.get("active_pass_rate") or 0.0) < min_active_pass_rate:
        reasons.append(f"active_pass_rate<{min_active_pass_rate:g}")
    verdict = "SHADOW_READY_RESEARCH_CANDIDATE" if not reasons else "RESEARCH_ONLY_UNSTABLE"
    return verdict, reasons


def run_grid(seasons: tuple[str, ...], first_month: str, last_month: str,
             configs: list[FeatureFilterConfig]) -> dict[str, Any]:
    feature_history = build_feature_history(load_seasons(seasons))
    by_source = {
        source: build_feature_enriched_candidates(seasons, source, feature_history)
        for source in sorted({config.odds_source for config in configs})
    }
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, pd.DataFrame]] = {}
    for config in configs:
        candidates = by_source[config.odds_source]
        wf_summary, selected = walk_forward_feature_filter(candidates, config, first_month, last_month)
        portfolio, daily, bets = simulate_settlement_portfolio(selected, daily_limit=100.0, max_single_stake=10.0)
        windows = _window_rows(bets, first_month, last_month)
        window_summary = _summarize_windows(windows)
        overall = portfolio["overall"]
        season_rows = season_summary_from_bets(bets)
        latest_season = season_rows[-1] if season_rows else {}
        row = {
            "label": config.label,
            "odds_source": config.odds_source,
            "train_months": config.train_months,
            "min_train_rows": config.min_train_rows,
            "min_predicted_ev": config.min_predicted_ev,
            "max_bets_per_day": config.max_bets_per_day,
            "ridge": config.ridge,
            "residual_cap": config.residual_cap,
            "selected_rules": "|".join(config.selected_rules),
            "candidate_count": int(len(candidates)),
            "selected_candidates": int(len(selected)),
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
        verdict, fail_reasons = assess_feature_filter_row(row)
        row["stability_verdict"] = verdict
        row["fail_reasons"] = fail_reasons
        rows.append(row)
        artifacts[config.label] = {
            "selected": selected,
            "daily": daily,
            "bets": bets,
            "windows": pd.DataFrame(windows),
            "month_reports": pd.DataFrame(wf_summary["months"]),
        }
    rows.sort(key=_score_config, reverse=True)
    best_label = rows[0]["label"] if rows else None
    return {
        "method": "feature-enriched no-leak candidate quality filter",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "configs_tested": len(configs),
        "results": rows,
        "best_label": best_label,
        "artifacts": artifacts,
    }


def default_configs(odds_sources: tuple[str, ...]) -> list[FeatureFilterConfig]:
    configs: list[FeatureFilterConfig] = []
    rule_scopes = (
        (I2_DRAW_RULE,),
        (I2_DRAW_RULE, SP1_HOME_RULE),
    )
    for odds_source, train_months, min_train_rows, min_ev, max_per_day, ridge, residual_cap, selected_rules in itertools.product(
        odds_sources,
        (18, 30, 42),
        (120, 240),
        (-0.01, 0.0, 0.02, 0.04),
        (1, 3),
        (10.0, 35.0),
        (0.04, 0.08),
        rule_scopes,
    ):
        configs.append(FeatureFilterConfig(
            odds_source, train_months, min_train_rows, min_ev, max_per_day, ridge, residual_cap, selected_rules
        ))
    return configs


def formal_i2_configs(odds_sources: tuple[str, ...]) -> list[FeatureFilterConfig]:
    return [
        FeatureFilterConfig(
            odds_source,
            train_months=30,
            min_train_rows=120,
            min_predicted_ev=0.02,
            max_bets_per_day=1,
            ridge=10.0,
            residual_cap=0.08,
            selected_rules=(I2_DRAW_RULE,),
        )
        for odds_source in odds_sources
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="No-leak feature-enriched candidate filter for I2 draw and SP1 home.")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/feature_enriched_candidate_filter"))
    parser.add_argument("--formal-i2-only", action="store_true",
                        help="Run only the formal I2 draw market-anchored configuration")
    parser.add_argument("--export-formal-i2-scorer", action="store_true",
                        help="Export the formal I2 market-anchored scorer artifact instead of running the full grid")
    parser.add_argument("--export-sp1-shadow-scorer", action="store_true",
                        help="Export the audited SP1 home scorer for official-SP shadow validation")
    parser.add_argument("--export-odds-source", default="AVG_OPEN",
                        help="Odds source to use when exporting --export-formal-i2-scorer")
    parser.add_argument("--prediction-month", default="2026-06",
                        help="Future month the exported scorer is allowed to predict")
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    odds_sources = tuple(item.strip() for item in args.odds_sources.split(",") if item.strip())
    unknown = [source for source in odds_sources if source not in ODDS_SOURCE_COLUMNS]
    if unknown:
        raise SystemExit(f"Unknown odds source(s): {', '.join(unknown)}")

    if args.export_formal_i2_scorer or args.export_sp1_shadow_scorer:
        if args.export_odds_source not in ODDS_SOURCE_COLUMNS:
            raise SystemExit(f"Unknown export odds source: {args.export_odds_source}")
        if args.export_sp1_shadow_scorer:
            config = FeatureFilterConfig(
                args.export_odds_source,
                train_months=18,
                min_train_rows=80,
                min_predicted_ev=0.0,
                max_bets_per_day=1,
                ridge=35.0,
                residual_cap=0.08,
                selected_rules=(SP1_HOME_RULE,),
            )
        else:
            config = FeatureFilterConfig(
                args.export_odds_source,
                train_months=30,
                min_train_rows=120,
                min_predicted_ev=0.02,
                max_bets_per_day=1,
                ridge=10.0,
                residual_cap=0.08,
                selected_rules=(I2_DRAW_RULE,),
            )
        candidates = build_feature_enriched_candidates(seasons, config.odds_source)
        artifact = export_scorer_artifact(candidates, config, args.prediction_month)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "scorer.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
        return

    configs = formal_i2_configs(odds_sources) if args.formal_i2_only else default_configs(odds_sources)
    report = run_grid(seasons, args.first_month, args.last_month, configs)
    artifacts = report.pop("artifacts")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report["results"]).to_csv(args.output_dir / "grid_results.csv", index=False, encoding="utf-8-sig")
    if report["best_label"]:
        best = artifacts[report["best_label"]]
        for name, frame in best.items():
            frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    summary = {
        **report,
        "top": report["results"][:20],
        "notes": [
            "Candidate rules are fixed to the current research legs: I2 draw odds [2.8,3.5) and SP1 home market probability >= 0.55.",
            "Each test month is trained only on prior candidate rows inside the configured rolling window.",
            "This is still football-data market odds, not verified Chinese official SP.",
        ],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
