from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.feature_enriched_candidate_filter import (
    FEATURE_COLUMNS,
    FeatureFilterConfig,
    assess_feature_filter_row,
    export_scorer_artifact,
    fit_ridge_probability_model,
    formal_i2_configs,
    predict_probability,
    score_with_scorer_artifact,
    training_window,
    walk_forward_feature_filter,
)


def _base_row(date: str, won: bool, market_probability: float = 0.35) -> dict:
    return {
        "date": date,
        "bet_date": pd.Timestamp(date),
        "month": pd.Timestamp(date).to_period("M").strftime("%Y-%m"),
        "league": "I2",
        "home_team": "A",
        "away_team": "B",
        "outcome": "draw",
        "actual_result": "draw" if won else "home",
        "odds": 3.0,
        "odds_source": "AVG_OPEN",
        "won": won,
        "unit_profit": 2.0 if won else -1.0,
        "rule_label": "I2_draw_2p8_3p5",
        "market_probability": market_probability,
        "log_odds": np.log(3.0),
        "is_draw": 1.0,
        "is_home": 0.0,
        "league_draw_rate": 0.30,
        "league_prior_matches_scaled": 0.5,
        "form_points_diff": 0.0,
        "abs_form_points_diff": 0.0,
        "form_goal_diff_delta": 0.0,
        "abs_form_goal_diff_delta": 0.0,
        "season_points_per_match_delta": 0.0,
        "abs_season_points_per_match_delta": 0.0,
        "season_goal_diff_per_match_delta": 0.0,
        "abs_season_goal_diff_per_match_delta": 0.0,
        "rest_days_delta": 0.0,
        "lambda_total": 2.4,
        "lambda_diff": 0.1,
    }


def test_training_window_excludes_current_month() -> None:
    frame = pd.DataFrame([
        _base_row("2024-01-05", True),
        _base_row("2024-02-05", False),
        _base_row("2024-03-05", True),
    ])

    train = training_window(frame, pd.Period("2024-03", freq="M"), train_months=2)

    assert train["month"].tolist() == ["2024-01", "2024-02"]
    assert "2024-03" not in set(train["month"])


def test_formal_i2_configs_are_fixed_research_candidate() -> None:
    configs = formal_i2_configs(("AVG_OPEN", "AVG_CLOSE"))

    assert [config.odds_source for config in configs] == ["AVG_OPEN", "AVG_CLOSE"]
    assert all(config.train_months == 30 for config in configs)
    assert all(config.min_train_rows == 120 for config in configs)
    assert all(config.min_predicted_ev == 0.02 for config in configs)
    assert all(config.selected_rules == ("I2_draw_2p8_3p5",) for config in configs)


def test_formal_i2_config_can_target_close_source() -> None:
    config = formal_i2_configs(("AVG_CLOSE",))[0]

    assert config.odds_source == "AVG_CLOSE"
    assert config.label.startswith("AVG_CLOSE_rulesi2_draw_2p8_3p5_train30_n120_ev0p02")


def test_feature_filter_label_keeps_rule_identity() -> None:
    home = FeatureFilterConfig("AVG_CLOSE", 30, 120, 0.02, 1, 10.0, selected_rules=("SWE_home_prob0p55_1p00",))
    away = FeatureFilterConfig("AVG_CLOSE", 30, 120, 0.02, 1, 10.0, selected_rules=("SWE_away_odds2p2_2p8",))

    assert home.label != away.label
    assert "swe_home_prob0p55_1p00" in home.label
    assert "swe_away_odds2p2_2p8" in away.label


def test_ridge_probability_model_learns_directional_feature() -> None:
    rows = []
    for index in range(80):
        row = _base_row(f"2024-01-{index % 28 + 1:02d}", index >= 40)
        row["market_probability"] = 0.25 if index < 40 else 0.55
        rows.append(row)
    frame = pd.DataFrame(rows)

    coefficients, means, stds = fit_ridge_probability_model(frame, FEATURE_COLUMNS, ridge=1.0)
    low = pd.DataFrame([_base_row("2024-02-01", False, market_probability=0.25)])
    high = pd.DataFrame([_base_row("2024-02-02", True, market_probability=0.55)])

    assert predict_probability(high, coefficients, means, stds)[0] > predict_probability(low, coefficients, means, stds)[0]


def test_walk_forward_filter_uses_prior_rows_and_selects_positive_ev() -> None:
    rows = []
    for month in ("2024-01", "2024-02"):
        for index in range(20):
            row = _base_row(f"{month}-{index % 20 + 1:02d}", index >= 10, market_probability=0.55 if index >= 10 else 0.25)
            rows.append(row)
    for index in range(4):
        rows.append(_base_row(f"2024-03-{index + 1:02d}", True, market_probability=0.60))
    frame = pd.DataFrame(rows)
    config = FeatureFilterConfig(
        odds_source="AVG_OPEN",
        train_months=3,
        min_train_rows=30,
        min_predicted_ev=0.05,
        max_bets_per_day=3,
        ridge=1.0,
        residual_cap=0.30,
    )

    summary, selected = walk_forward_feature_filter(frame, config, "2024-03", "2024-03")

    assert summary["months"][0]["prior_candidates"] == 40
    assert not selected.empty
    assert selected["date"].str.startswith("2024-03").all()


def test_exported_scorer_artifact_replays_prediction() -> None:
    rows = []
    for month in ("2024-01", "2024-02", "2024-03"):
        for index in range(20):
            rows.append(_base_row(
                f"{month}-{index % 20 + 1:02d}",
                won=index >= 10,
                market_probability=0.55 if index >= 10 else 0.25,
            ))
    frame = pd.DataFrame(rows)
    config = FeatureFilterConfig(
        odds_source="AVG_OPEN",
        train_months=3,
        min_train_rows=30,
        min_predicted_ev=0.01,
        max_bets_per_day=1,
        ridge=1.0,
        residual_cap=0.30,
        selected_rules=("I2_draw_2p8_3p5",),
    )

    artifact = export_scorer_artifact(frame, config, "2024-04")
    scored = score_with_scorer_artifact(pd.DataFrame([_base_row("2024-04-01", True, 0.60)]), artifact)

    assert artifact["training_window"]["rows"] == 60
    assert artifact["selection"]["selected_rules"] == ["I2_draw_2p8_3p5"]
    assert scored.loc[0, "predicted_probability"] > 0.60
    assert scored.loc[0, "passes_scorer"]


def test_feature_filter_assessment_blocks_recent_losing_candidate() -> None:
    row = {
        "bets": 335,
        "profit": 439.9,
        "roi_pct": 13.13,
        "max_drawdown": 115.8,
        "positive_months": 21,
        "negative_months": 19,
        "positive_seasons": 3,
        "negative_seasons": 1,
        "latest_season_bets": 47,
        "latest_season_profit": -72.2,
        "active_pass_rate": 0.6667,
    }

    verdict, reasons = assess_feature_filter_row(row)

    assert verdict == "RESEARCH_ONLY_UNSTABLE"
    assert "latest_season_profit<0" in reasons


def test_feature_filter_assessment_accepts_stable_shadow_candidate() -> None:
    row = {
        "bets": 334,
        "profit": 625.7,
        "roi_pct": 18.73,
        "max_drawdown": 110.0,
        "positive_months": 25,
        "negative_months": 15,
        "positive_seasons": 4,
        "negative_seasons": 0,
        "latest_season_bets": 84,
        "latest_season_profit": 67.5,
        "active_pass_rate": 0.6667,
    }

    verdict, reasons = assess_feature_filter_row(row)

    assert verdict == "SHADOW_READY_RESEARCH_CANDIDATE"
    assert reasons == []
