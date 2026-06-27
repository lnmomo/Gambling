from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .dataset import OddsTiming, audit_football_data, load_football_data
from .evaluation import evaluate_probabilities, paired_bootstrap_difference
from .features import FEATURE_COLUMNS, build_leakage_free_rolling_features
from .ml_baselines import ProbabilityBaselines
from .models import HierarchicalLeagueDixonColes, MarketAnchoredResidualModel, TimeDecayDixonColes


OUTCOMES = ("home", "draw", "away")


@dataclass(frozen=True)
class ExperimentConfig:
    first_test_month: str
    test_months: int
    min_training_matches: int = 1000
    residual_training_months: int = 24
    calibration_months: int = 3
    bootstrap_samples: int = 2000
    seed: int = 20260622


def market_probability(frame: pd.DataFrame) -> np.ndarray:
    inverse = 1 / frame[[f"odds_{outcome}" for outcome in OUTCOMES]].to_numpy(float)
    return inverse / inverse.sum(axis=1, keepdims=True)


def closing_market_probability(frame: pd.DataFrame) -> np.ndarray | None:
    columns = [f"closing_odds_{outcome}" for outcome in OUTCOMES]
    if not set(columns).issubset(frame.columns) or frame[columns].isna().any(axis=1).any():
        return None
    inverse = 1 / frame[columns].to_numpy(float)
    return inverse / inverse.sum(axis=1, keepdims=True)


def build_rolling_football_predictions(frame: pd.DataFrame, min_training_matches: int = 1000,
                                       first_period: pd.Period | None = None,
                                       last_period: pd.Period | None = None) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    periods = pd.PeriodIndex(frame["match_date"].dt.to_period("M").unique()).sort_values()
    if first_period is not None:
        periods = periods[periods >= first_period]
    if last_period is not None:
        periods = periods[periods <= last_period]
    for period in periods:
        start, end = period.start_time, period.end_time
        train = frame[frame["match_date"] < start]
        test = frame[(frame["match_date"] >= start) & (frame["match_date"] <= end)].copy()
        if len(train) < min_training_matches or test.empty:
            continue
        model = TimeDecayDixonColes().fit(train, cutoff=start, iterations=180)
        hierarchical = HierarchicalLeagueDixonColes().fit(train, cutoff=start, iterations=180)
        probability = np.array([
            list(model.predict(row.home_team, row.away_team).values())
            for row in test.itertuples()
        ])
        hierarchical_probability = np.array([
            list(hierarchical.predict(row.home_team, row.away_team, row.league).values())
            for row in test.itertuples()
        ])
        for column, outcome in enumerate(OUTCOMES):
            test[f"dc_{outcome}"] = probability[:, column]
            test[f"hierarchical_dc_{outcome}"] = hierarchical_probability[:, column]
        rows.append(test)
    if not rows:
        raise ValueError("No rolling month has enough prior training matches")
    return pd.concat(rows, ignore_index=True).sort_values("match_date").reset_index(drop=True)


def _matrix(frame: pd.DataFrame, prefix: str) -> np.ndarray:
    return frame[[f"{prefix}_{outcome}" for outcome in OUTCOMES]].to_numpy(float)


def _log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    indices = np.array([OUTCOMES.index(str(value)) for value in outcomes])
    return float(-np.mean(np.log(np.clip(probabilities[np.arange(len(indices)), indices], 1e-12, 1))))


def _features(frame: pd.DataFrame, include_model_probability: bool = False) -> np.ndarray:
    values = frame[list(FEATURE_COLUMNS)].to_numpy(float)
    if include_model_probability:
        values = np.column_stack([values, _matrix(frame, "hierarchical_dc")])
    return values


def _select_proposed_model(train: pd.DataFrame, calibration: pd.DataFrame) -> tuple[MarketAnchoredResidualModel, dict[str, float]]:
    train_market, train_dc = _matrix(train, "market"), _matrix(train, "hierarchical_dc")
    cal_market, cal_dc = _matrix(calibration, "market"), _matrix(calibration, "hierarchical_dc")
    train_features, cal_features = _features(train), _features(calibration)
    candidates: list[tuple[float, float, MarketAnchoredResidualModel, float, bool]] = []
    for use_features in (False, True):
        fit_features = train_features if use_features else None
        validation_features = cal_features if use_features else None
        for shrinkage in (50.0, 200.0, 1000.0, 1e12):
            model = MarketAnchoredResidualModel(league_shrinkage=shrinkage).fit(
                train_market, train_dc, train.actual_result.to_numpy(), train.league.to_numpy(), fit_features,
            ).calibrate(cal_market, cal_dc, calibration.actual_result.to_numpy(),
                        calibration.league.to_numpy(), validation_features)
            loss = _log_loss(model.predict(cal_market, cal_dc, calibration.league.to_numpy(), validation_features),
                             calibration.actual_result.to_numpy())
            complexity_penalty = 1e-4 * int(use_features) + 1e-4 * int(shrinkage < 1e11)
            candidates.append((loss + complexity_penalty, loss, model, shrinkage, use_features))
    _, loss, model, shrinkage, use_features = min(candidates, key=lambda item: item[0])
    return model, {"validation_log_loss": loss, "league_shrinkage": shrinkage,
                   "temperature": model.temperature, "uses_rolling_features": use_features}


def run_nested_experiment(frame: pd.DataFrame, config: ExperimentConfig) -> tuple[dict[str, object], pd.DataFrame]:
    first_test = pd.Period(config.first_test_month, freq="M")
    first_required = first_test - config.calibration_months - config.residual_training_months
    last_required = first_test + config.test_months - 1
    feature_history = build_leakage_free_rolling_features(frame)
    enriched = build_rolling_football_predictions(
        feature_history, config.min_training_matches, first_period=first_required, last_period=last_required,
    )
    market = market_probability(enriched)
    for column, outcome in enumerate(OUTCOMES):
        enriched[f"market_{outcome}"] = market[:, column]
    prediction_rows: list[pd.DataFrame] = []
    fold_reports: list[dict[str, object]] = []
    for period in pd.period_range(config.first_test_month, periods=config.test_months, freq="M"):
        test_start, test_end = period.start_time, period.end_time
        calibration_start = test_start - pd.DateOffset(months=config.calibration_months)
        training_start = calibration_start - pd.DateOffset(months=config.residual_training_months)
        train = enriched[(enriched.match_date >= training_start) & (enriched.match_date < calibration_start)]
        calibration = enriched[(enriched.match_date >= calibration_start) & (enriched.match_date < test_start)]
        test = enriched[(enriched.match_date >= test_start) & (enriched.match_date <= test_end)].copy()
        if len(train) < config.min_training_matches or len(calibration) < 200 or test.empty:
            fold_reports.append({"month": str(period), "status": "ABSTAIN", "train": len(train),
                                 "calibration": len(calibration), "test": len(test)})
            continue
        train_market, train_dc = _matrix(train, "market"), _matrix(train, "hierarchical_dc")
        cal_market, cal_dc = _matrix(calibration, "market"), _matrix(calibration, "hierarchical_dc")
        test_market, test_dc = _matrix(test, "market"), _matrix(test, "hierarchical_dc")
        train_features, cal_features, test_features = _features(train), _features(calibration), _features(test)
        proposed, selected = _select_proposed_model(train, calibration)
        no_calibration = MarketAnchoredResidualModel().fit(
            train_market, train_dc, train.actual_result.to_numpy(), train.league.to_numpy(), train_features,
        )
        no_league = MarketAnchoredResidualModel(league_shrinkage=1e12).fit(
            train_market, train_dc, train.actual_result.to_numpy(), train.league.to_numpy(), train_features,
        ).calibrate(cal_market, cal_dc, calibration.actual_result.to_numpy(), calibration.league.to_numpy(), cal_features)
        no_features = MarketAnchoredResidualModel(league_shrinkage=1e12).fit(
            train_market, train_dc, train.actual_result.to_numpy(), train.league.to_numpy(),
        ).calibrate(cal_market, cal_dc, calibration.actual_result.to_numpy(), calibration.league.to_numpy())
        ml = ProbabilityBaselines(seed=config.seed).fit(
            _features(train, include_model_probability=True), train.actual_result.to_numpy(),
        ).predict(_features(test, include_model_probability=True))
        predictions = {
            "market": test_market,
            "dixon_coles": _matrix(test, "dc"),
            "hierarchical_dixon_coles": test_dc,
            "fixed_blend": 0.75 * test_market + 0.25 * test_dc,
            "proposed": proposed.predict(test_market, test_dc, test.league.to_numpy(),
                                          test_features if proposed.uses_extra_features else None),
            "ablation_no_features": no_features.predict(test_market, test_dc, test.league.to_numpy()),
            "ablation_no_calibration": no_calibration.predict(test_market, test_dc, test.league.to_numpy(), test_features),
            "ablation_no_league": no_league.predict(test_market, test_dc, test.league.to_numpy(), test_features),
            **ml,
        }
        closing = closing_market_probability(test)
        if closing is not None:
            predictions["closing_market_reference"] = closing
        for name, values in predictions.items():
            for column, outcome in enumerate(OUTCOMES):
                test[f"{name}_{outcome}"] = values[:, column]
        test["fold_month"] = str(period)
        test["calibration_temperature"] = proposed.temperature
        prediction_rows.append(test)
        fold_reports.append({
            "month": str(period), "status": "EVALUATED", "train": len(train),
            "calibration": len(calibration), "test": len(test), **selected,
        })
    if not prediction_rows:
        raise ValueError("No nested fold met the minimum train/calibration requirements")
    predictions = pd.concat(prediction_rows, ignore_index=True)
    outcomes = predictions.actual_result.to_numpy()
    model_names = ["market", "dixon_coles", "hierarchical_dixon_coles", "fixed_blend",
                   "multinomial_logit", "random_forest", "hist_gradient_boosting", "proposed",
                   "ablation_no_features", "ablation_no_calibration", "ablation_no_league"]
    closing_columns = [f"closing_market_reference_{outcome}" for outcome in OUTCOMES]
    if set(closing_columns).issubset(predictions.columns) and predictions[closing_columns].notna().all(axis=None):
        model_names.append("closing_market_reference")
    metrics = {name: evaluate_probabilities(_matrix(predictions, name), outcomes) for name in model_names}
    comparisons = {
        baseline: paired_bootstrap_difference(
            _matrix(predictions, "proposed"), _matrix(predictions, baseline), outcomes, _log_loss,
            samples=config.bootstrap_samples, seed=config.seed,
        )
        for baseline in model_names if baseline != "proposed"
    }
    report: dict[str, object] = {
        "method": "nested rolling-origin market-anchored hierarchical residual experiment",
        "config": config.__dict__, "evaluated_matches": len(predictions),
        "folds": fold_reports, "metrics": metrics,
        "paired_bootstrap_log_loss_proposed_minus_baseline": comparisons,
        "lower_difference_is_better": True,
        "closing_market_is_reference_only": "closing_market_reference" in model_names,
    }
    return report, predictions


def run_from_directory(source: Path, output: Path, config: ExperimentConfig) -> dict[str, object]:
    audit = audit_football_data(source, OddsTiming.PRE_CLOSING)
    frame = load_football_data(source, OddsTiming.PRE_CLOSING)
    report, predictions = run_nested_experiment(frame, config)
    report["dataset_audit"] = audit.to_dict()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "report.md").write_text(render_markdown_report(report), encoding="utf-8")
    predictions.to_csv(output / "predictions.csv", index=False, encoding="utf-8-sig")
    return report


def render_markdown_report(report: dict[str, object]) -> str:
    audit = report["dataset_audit"]
    metrics = report["metrics"]
    comparisons = report["paired_bootstrap_log_loss_proposed_minus_baseline"]
    lines = [
        "# Research Experiment Report", "",
        "## Dataset Audit", "",
        f"- Files: {audit['files']}",
        f"- Raw rows: {audit['raw_rows']}",
        f"- Usable rows: {audit['usable_rows']}",
        f"- Date range: {audit['first_match_date']} to {audit['last_match_date']}",
        f"- Odds timing: {audit['selected_odds_timing']}",
        f"- Exact odds timestamps: {audit['exact_snapshot_timestamps_available']}", "",
        "## Probability Metrics", "",
        "| Model | N | Log Loss | Brier | RPS | Top-label ECE | Macro classwise ECE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, values in metrics.items():
        lines.append(
            f"| {name} | {values['sample_count']} | {values['log_loss']:.6f} | "
            f"{values['brier_score']:.6f} | {values['rps']:.6f} | "
            f"{values['top_label_ece']:.6f} | {values['macro_classwise_ece']:.6f} |"
        )
    lines.extend(["", "## Paired Bootstrap: Proposed Minus Baseline Log Loss", "",
                  "Negative values favor the proposed model.", "",
                  "| Baseline | Difference | 95% CI | P(proposed better) |",
                  "|---|---:|---:|---:|"])
    for name, values in comparisons.items():
        lines.append(
            f"| {name} | {values['difference']:.6f} | "
            f"[{values['ci95_low']:.6f}, {values['ci95_high']:.6f}] | "
            f"{values['probability_first_better']:.3f} |"
        )
    lines.extend(["", "## Interpretation Guardrails", "",
                  "- Closing market is a reference benchmark and is never a deployable pre-match input.",
                  "- A confidence interval crossing zero is not evidence of superiority.",
                  "- Betting ROI is intentionally excluded from model selection.",
                  "- CSV odds lack exact collection timestamps and are not described as guaranteed opening odds.", ""])
    return "\n".join(lines)
