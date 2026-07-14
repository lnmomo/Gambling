from __future__ import annotations

import numpy as np
import pandas as pd
import unittest
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.walk_forward_residual_strategy import (
    IsotonicPAV,
    PortfolioConfig,
    EXPERIMENT_PROFILES,
    ResidualProbabilityModel,
    _best_failed_validation_row,
    build_feature_history,
    choose_candidates,
    fit_quality_gate,
    load_season_matches,
    promotion_decision,
    select_persistent_buckets,
    simulate,
)


class ResidualStrategyTests(unittest.TestCase):
    def test_pav_calibration_is_monotonic(self) -> None:
        calibrator = IsotonicPAV().fit(
            np.array([.1, .2, .3, .4, .5, .6]),
            np.array([0, 1, 0, 1, 0, 1]),
        )
        predicted = calibrator.predict(np.linspace(.1, .6, 30))
        self.assertTrue(np.all(np.diff(predicted) >= 0))

    def test_same_day_result_is_not_used_to_build_features(self) -> None:
        rows = pd.DataFrame([
            {"match_date": pd.Timestamp("2025-01-01"), "league": "L", "HomeTeam": "A", "AwayTeam": "B",
             "home_goals": 1, "away_goals": 0, "odds_home": 2.0, "odds_draw": 3.4, "odds_away": 4.0},
            {"match_date": pd.Timestamp("2025-01-02"), "league": "L", "HomeTeam": "A", "AwayTeam": "B",
             "home_goals": 2, "away_goals": 1, "odds_home": 2.1, "odds_draw": 3.3, "odds_away": 3.8},
        ])
        changed = rows.copy()
        changed.loc[1, ["home_goals", "away_goals"]] = [0, 8]
        original_features = build_feature_history(rows)
        changed_features = build_feature_history(changed)
        columns = [
            f"pure_{outcome}" for outcome in ("home", "draw", "away")
        ] + [
            "form_points_diff",
            "form_goal_diff_delta",
            "season_points_per_match_delta",
            "rest_days_delta",
            "combined_recent_draw_rate",
            "combined_recent_low_score_rate",
            "draw_market_vs_league",
        ]
        self.assertTrue(original_features[columns].equals(changed_features[columns]))

    def test_recent_form_features_use_prior_matches(self) -> None:
        rows = pd.DataFrame([
            {"match_date": pd.Timestamp("2025-01-01"), "league": "L", "HomeTeam": "A", "AwayTeam": "B",
             "home_goals": 3, "away_goals": 0, "odds_home": 2.0, "odds_draw": 3.4, "odds_away": 4.0},
            {"match_date": pd.Timestamp("2025-01-08"), "league": "L", "HomeTeam": "A", "AwayTeam": "C",
             "home_goals": 1, "away_goals": 1, "odds_home": 2.1, "odds_draw": 3.3, "odds_away": 3.8},
        ])

        features = build_feature_history(rows)

        self.assertEqual(float(features.loc[0, "form_points_diff"]), 0.0)
        self.assertGreater(float(features.loc[1, "form_points_diff"]), 0.0)
        self.assertGreater(float(features.loc[1, "combined_recent_low_score_rate"]), 0.0)
        self.assertEqual(float(features.loc[1, "home_rest_days"]), 7.0)

    def test_constrained_kelly_respects_daily_and_league_limits(self) -> None:
        rows = []
        for index in range(20):
            rows.append({
                "match_date": pd.Timestamp("2025-01-01"), "league": "L" if index < 10 else "M",
                "home_team": f"H{index}", "away_team": f"A{index}", "actual_result": "home",
                "probability_home": .60, "uncertainty_home": .01, "lower_ev_home": .15, "odds_home": 2.0,
                "probability_draw": .20, "uncertainty_draw": .01, "lower_ev_draw": -.2, "odds_draw": 3.4,
                "probability_away": .20, "uncertainty_away": .01, "lower_ev_away": -.2, "odds_away": 4.0,
            })
        days, bets = simulate(pd.DataFrame(rows), PortfolioConfig(0, 5, .25))
        self.assertLessEqual(float(days["staked"].max()), 100)
        self.assertLessEqual(float(bets.groupby(["date", "league"])["stake"].sum().max()), 40)
        self.assertLessEqual(float(bets["stake"].max()), 20)

    def test_load_season_matches_uses_requested_seasons(self) -> None:
        matches = load_season_matches(("2324", "2425"))

        self.assertFalse(matches.empty)
        self.assertGreaterEqual(matches["match_date"].min(), pd.Timestamp("2023-01-01"))
        self.assertLess(matches["match_date"].max(), pd.Timestamp("2026-01-01"))
        self.assertGreaterEqual(matches["match_date"].dt.year.nunique(), 2)

    def test_load_season_matches_can_read_new_single_csv_domains(self) -> None:
        matches = load_season_matches(("WORLD_CUP",))

        self.assertFalse(matches.empty)
        self.assertEqual(set(matches["league"]), {"WORLD_CUP"})
        self.assertGreaterEqual(len(matches), 100)
        self.assertTrue({"odds_home", "odds_draw", "odds_away"}.issubset(matches.columns))

    def test_load_season_matches_accepts_direct_csv_path(self) -> None:
        matches = load_season_matches(("data/historical_csv/football-data/new/WORLD_CUP.csv",))

        self.assertFalse(matches.empty)
        self.assertEqual(set(matches["league"]), {"WORLD_CUP"})

    def test_stability_profile_requires_larger_validation_sample(self) -> None:
        profile = EXPERIMENT_PROFILES["stability"]

        self.assertGreater(profile["validation_min_bets"], EXPERIMENT_PROFILES["relaxed"]["validation_min_bets"])
        self.assertGreater(profile["min_validation_roi"], 0)
        self.assertGreater(profile["min_validation_profit"], 0)

    def test_guarded_profile_caps_kelly_and_requires_drawdown_cover(self) -> None:
        profile = EXPERIMENT_PROFILES["guarded"]

        self.assertEqual(profile["kelly_fractions"], (0.10,))
        self.assertLess(profile["max_drawdown_profit_ratio"], 1.0)
        self.assertGreater(profile["min_validation_roi"], EXPERIMENT_PROFILES["relaxed"].get("min_validation_roi", 0))

    def test_world_cup_sparse_profile_uses_sparse_event_thresholds(self) -> None:
        profile = EXPERIMENT_PROFILES["world_cup_sparse"]
        all_profile = EXPERIMENT_PROFILES["world_cup_sparse_all"]
        probe_profile = EXPERIMENT_PROFILES["world_cup_sparse_probe"]

        self.assertLess(profile["min_train_rows"], 300)
        self.assertLess(profile["min_validation_rows"], 100)
        self.assertEqual(profile["allowed_outcomes"], (("draw",),))
        self.assertTrue(profile["research_only"])
        self.assertEqual(all_profile["allowed_outcomes"], (("home", "draw", "away"),))
        self.assertTrue(all_profile["research_only"])
        self.assertEqual(probe_profile["validation_min_bets"], 1)
        self.assertTrue(probe_profile["research_only"])

    def test_residual_model_min_fit_rows_is_configurable(self) -> None:
        rows = []
        for index in range(20):
            actual = ("home", "draw", "away")[index % 3]
            rows.append({
                "league": "L",
                "actual_result": actual,
                "market_home": 0.45,
                "market_draw": 0.28,
                "market_away": 0.27,
                "pure_home": 0.46,
                "pure_draw": 0.27,
                "pure_away": 0.27,
                "odds_home": 2.0,
                "odds_draw": 3.2,
                "odds_away": 3.6,
            })

        model = ResidualProbabilityModel(min_fit_rows=20)

        self.assertIs(model.fit(pd.DataFrame(rows)), model)

    def test_best_failed_validation_row_is_serializable(self) -> None:
        row = {
            "config": PortfolioConfig(0.01, 4.0, 0.05),
            "rejection_reasons": ["validation_bets<minimum"],
            "positive_validation_months": 1,
            "bets": 2,
            "winning_bets": 1,
            "total_staked": 2.0,
            "profit": 1.2,
            "roi_pct": 60.0,
            "max_drawdown": 1.0,
            "active_days": 2,
        }

        best = _best_failed_validation_row([row])

        self.assertEqual(best["config"]["min_lower_ev"], 0.01)
        self.assertEqual(best["rejection_reasons"], ["validation_bets<minimum"])
        self.assertEqual(best["profit"], 1.2)

    def test_candidate_selection_can_restrict_outcomes_and_odds_floor(self) -> None:
        rows = pd.DataFrame([{
            "match_date": pd.Timestamp("2025-01-01"),
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "actual_result": "draw",
            "elo_delta": 20.0,
            "lambda_total": 2.45,
            "market_draw": .27,
            "league_draw_rate": .28,
            "combined_recent_draw_rate": .40,
            "combined_recent_low_score_rate": .70,
            "draw_market_vs_league": -.04,
            "probability_home": .70,
            "uncertainty_home": .01,
            "lower_ev_home": .25,
            "odds_home": 1.7,
            "probability_draw": .34,
            "uncertainty_draw": .01,
            "lower_ev_draw": .08,
            "odds_draw": 3.2,
            "probability_away": .20,
            "uncertainty_away": .01,
            "lower_ev_away": -.1,
            "odds_away": 4.5,
        }])

        candidates = choose_candidates(
            rows,
            PortfolioConfig(0.0, 3.5, 0.1, min_odds=2.2, allowed_outcomes=("draw",)),
        )

        self.assertEqual(candidates.iloc[0]["outcome"], "draw")
        self.assertGreaterEqual(float(candidates.iloc[0]["odds"]), 2.2)
        self.assertEqual(candidates.iloc[0]["market_draw_bucket"], "market_draw_mid")
        self.assertEqual(candidates.iloc[0]["league_draw_rate_bucket"], "league_draw_mid")
        self.assertEqual(candidates.iloc[0]["recent_draw_bucket"], "recent_draw_high")
        self.assertEqual(candidates.iloc[0]["recent_low_score_bucket"], "low_score_high")
        self.assertEqual(candidates.iloc[0]["draw_market_gap_bucket"], "draw_under_league")
        self.assertEqual(candidates.iloc[0]["strength_gap_bucket"], "strength_close")
        self.assertEqual(candidates.iloc[0]["goal_env_bucket"], "goal_env_mid")
        self.assertIn("model_probability", candidates.columns)
        self.assertIn("model_lower_ev", candidates.columns)

    def test_simulation_records_model_ev_diagnostic_separately(self) -> None:
        rows = pd.DataFrame([{
            "match_date": pd.Timestamp("2025-01-01"),
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "actual_result": "home",
            "probability_home": .55,
            "model_probability_home": .70,
            "uncertainty_home": .01,
            "lower_ev_home": .09,
            "model_lower_ev_home": .35,
            "odds_home": 2.0,
            "probability_draw": .20,
            "model_probability_draw": .20,
            "uncertainty_draw": .01,
            "lower_ev_draw": -.2,
            "model_lower_ev_draw": -.2,
            "odds_draw": 3.4,
            "probability_away": .20,
            "model_probability_away": .20,
            "uncertainty_away": .01,
            "lower_ev_away": -.2,
            "model_lower_ev_away": -.2,
            "odds_away": 4.0,
        }])

        _, bets = simulate(rows, PortfolioConfig(0.0, 3.0, .10))

        self.assertEqual(float(bets.iloc[0]["probability"]), .55)
        self.assertEqual(float(bets.iloc[0]["model_probability"]), .70)
        self.assertGreater(float(bets.iloc[0]["model_ev"]), float(bets.iloc[0]["lower_ev"]))

    def test_simulation_can_rank_and_limit_daily_candidates(self) -> None:
        rows = []
        for index, score in enumerate([0.1, 0.9, 0.4]):
            rows.append({
                "match_date": pd.Timestamp("2025-01-01"),
                "league": "L",
                "home_team": f"A{index}",
                "away_team": f"B{index}",
                "actual_result": "draw",
                "probability_home": .30,
                "uncertainty_home": .01,
                "lower_ev_home": -.1,
                "odds_home": 2.0,
                "probability_draw": .36,
                "uncertainty_draw": .01,
                "lower_ev_draw": .02 + index * .001,
                "odds_draw": 3.0,
                "probability_away": .30,
                "uncertainty_away": .01,
                "lower_ev_away": -.1,
                "odds_away": 4.0,
                "quality_score": score,
            })

        _, bets = simulate(
            pd.DataFrame(rows),
            PortfolioConfig(
                0.0,
                3.5,
                .10,
                min_odds=2.2,
                allowed_outcomes=("draw",),
                candidate_limit_per_day=1,
                ranking_key="quality_score",
            ),
        )

        self.assertEqual(len(bets), 1)
        self.assertEqual(bets.iloc[0]["home_team"], "A1")

    def test_draw_regime_profile_uses_feature_buckets(self) -> None:
        profile = EXPERIMENT_PROFILES["draw_regime"]

        self.assertIn(("odds_bucket", "market_draw_bucket"), profile["bucket_keys"])
        self.assertEqual(profile["allowed_outcomes"], (("draw",),))
        self.assertGreaterEqual(profile["min_bucket_samples"][0], 8)

    def test_draw_regime_strict_is_more_selective(self) -> None:
        profile = EXPERIMENT_PROFILES["draw_regime_strict"]

        self.assertEqual(profile["min_odds"], (2.8,))
        self.assertEqual(profile["max_odds"], (3.5,))
        self.assertGreater(profile["min_bucket_samples"][0], EXPERIMENT_PROFILES["draw_regime"]["min_bucket_samples"][0])
        self.assertGreater(profile["min_bucket_roi"][0], EXPERIMENT_PROFILES["draw_regime"]["min_bucket_roi"][0])

    def test_quality_gate_trains_and_filters_candidates(self) -> None:
        rows = []
        for index in range(24):
            won = index % 3 == 0
            rows.append({
                "match_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=index),
                "league": "L",
                "home_team": f"A{index}",
                "away_team": f"B{index}",
                "actual_result": "draw" if won else "home",
                "elo_delta": 10.0 if won else 160.0,
                "lambda_total": 2.45 if won else 2.95,
                "market_draw": .29 if won else .21,
                "league_draw_rate": .30 if won else .20,
                "probability_home": .30,
                "uncertainty_home": .01,
                "lower_ev_home": -.1,
                "odds_home": 2.0,
                "probability_draw": .38 if won else .31,
                "uncertainty_draw": .01,
                "lower_ev_draw": .08,
                "odds_draw": 3.0,
                "probability_away": .30,
                "uncertainty_away": .01,
                "lower_ev_away": -.1,
                "odds_away": 4.0,
            })
        frame = pd.DataFrame(rows)
        base = PortfolioConfig(0.0, 3.5, 0.05, min_odds=2.8, allowed_outcomes=("draw",))

        gate = fit_quality_gate(frame, base, quantile=.5, min_samples=12)
        candidates = choose_candidates(frame, replace(base, quality_gate=gate))

        self.assertIsNotNone(gate)
        self.assertGreater(gate["training_samples"], 12)
        self.assertIn("coefficients", gate)
        self.assertFalse(candidates.empty)
        self.assertIn("quality_score", candidates.columns)

    def test_draw_quality_pooled_uses_longer_validation_history(self) -> None:
        profile = EXPERIMENT_PROFILES["draw_quality_pooled"]

        self.assertEqual(profile["validation_months"], 12)
        self.assertEqual(profile["training_months"], 18)
        self.assertGreater(profile["quality_min_samples"], EXPERIMENT_PROFILES["draw_quality"]["quality_min_samples"])
        self.assertIn(0.75, profile["quality_quantiles"])

    def test_draw_quality_pooled_full_disables_holdout_split(self) -> None:
        profile = EXPERIMENT_PROFILES["draw_quality_pooled_full"]

        self.assertEqual(profile["validation_months"], 12)
        self.assertIs(profile["quality_holdout"], False)
        self.assertTrue(profile["quality_gate"])

    def test_draw_quality_pooled_lite_has_single_fast_grid(self) -> None:
        profile = EXPERIMENT_PROFILES["draw_quality_pooled_lite"]

        self.assertEqual(profile["ev_thresholds"], (0.01,))
        self.assertEqual(profile["min_odds"], (2.8,))
        self.assertEqual(profile["max_odds"], (3.5,))
        self.assertEqual(profile["kelly_fractions"], (0.05,))
        self.assertEqual(profile["quality_quantiles"], (0.50,))

    def test_real_ev_probe_draw_is_research_only_sparse_signal_profile(self) -> None:
        profile = EXPERIMENT_PROFILES["real_ev_probe_draw"]

        self.assertTrue(profile["research_only"])
        self.assertLess(profile["validation_min_bets"], EXPERIMENT_PROFILES["draw_quality_pooled_lite"]["validation_min_bets"])
        self.assertEqual(profile["allowed_outcomes"], (("draw",),))
        self.assertIn(-0.01, profile["ev_thresholds"])

    def test_real_ev_draw_regime_features_profile_uses_new_draw_buckets(self) -> None:
        profile = EXPERIMENT_PROFILES["real_ev_draw_regime_features"]
        bucket_columns = {column for key in profile["bucket_keys"] for column in key}

        self.assertTrue(profile["research_only"])
        self.assertIn("recent_draw_bucket", bucket_columns)
        self.assertIn("recent_low_score_bucket", bucket_columns)
        self.assertIn("draw_market_gap_bucket", bucket_columns)

    def test_real_ev_draw_regime_features_fast_keeps_small_grid(self) -> None:
        profile = EXPERIMENT_PROFILES["real_ev_draw_regime_features_fast"]

        self.assertTrue(profile["research_only"])
        self.assertEqual(len(profile["bucket_keys"]), 2)
        self.assertEqual(profile["ev_thresholds"], (-0.01,))

    def test_real_ev_draw_ranked_profile_limits_daily_candidates(self) -> None:
        profile = EXPERIMENT_PROFILES["real_ev_draw_ranked"]

        self.assertTrue(profile["research_only"])
        self.assertEqual(profile["candidate_limits_per_day"], (1, 2))
        self.assertIn("quality_score", profile["ranking_keys"])

    def test_real_ev_draw_ranked_fast_uses_single_daily_candidate(self) -> None:
        profile = EXPERIMENT_PROFILES["real_ev_draw_ranked_fast"]

        self.assertTrue(profile["research_only"])
        self.assertEqual(profile["candidate_limits_per_day"], (1,))
        self.assertEqual(profile["ranking_keys"], ("lower_ev",))

    def test_persistent_bucket_requires_repeated_positive_months(self) -> None:
        rows = []
        for month, won in [("2025-01", True), ("2025-02", True), ("2025-03", False), ("2025-04", True)]:
            for index in range(4):
                rows.append({
                    "match_date": pd.Timestamp(f"{month}-{index + 1:02d}"),
                    "league": "L",
                    "home_team": f"A{month}{index}",
                    "away_team": f"B{month}{index}",
                    "actual_result": "draw" if won else "home",
                    "elo_delta": 20.0,
                    "lambda_total": 2.45,
                    "market_draw": .30,
                    "league_draw_rate": .30,
                    "probability_home": .30,
                    "uncertainty_home": .01,
                    "lower_ev_home": -.1,
                    "odds_home": 2.0,
                    "probability_draw": .37,
                    "uncertainty_draw": .01,
                    "lower_ev_draw": .08,
                    "odds_draw": 3.0,
                    "probability_away": .30,
                    "uncertainty_away": .01,
                    "lower_ev_away": -.1,
                    "odds_away": 4.0,
                })
        frame = pd.DataFrame(rows)
        base = PortfolioConfig(0.0, 3.5, 0.05, min_odds=2.8, allowed_outcomes=("draw",))

        accepted = select_persistent_buckets(
            frame,
            base,
            ("odds_bucket", "market_draw_bucket"),
            min_samples=12,
            min_roi=0.05,
            min_active_months=4,
            min_positive_months=3,
        )
        rejected = select_persistent_buckets(
            frame,
            base,
            ("odds_bucket", "market_draw_bucket"),
            min_samples=12,
            min_roi=0.05,
            min_active_months=4,
            min_positive_months=4,
        )

        self.assertEqual(accepted, (("[2.8,3.5)", "market_draw_high"),))
        self.assertEqual(rejected, ())

    def test_simulation_halts_after_stop_loss(self) -> None:
        rows = []
        for day in range(5):
            rows.append({
                "match_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=day),
                "league": "L",
                "home_team": f"A{day}",
                "away_team": f"B{day}",
                "actual_result": "away",
                "probability_home": .20,
                "uncertainty_home": .01,
                "lower_ev_home": -.2,
                "odds_home": 2.0,
                "probability_draw": .40,
                "uncertainty_draw": .01,
                "lower_ev_draw": .1,
                "odds_draw": 3.0,
                "probability_away": .20,
                "uncertainty_away": .01,
                "lower_ev_away": -.2,
                "odds_away": 4.0,
            })

        days, bets = simulate(
            pd.DataFrame(rows),
            PortfolioConfig(0.0, 3.5, 0.05, min_odds=2.2, allowed_outcomes=("draw",), stop_loss=2.0),
        )

        self.assertEqual(len(bets), 2)
        self.assertTrue(bool(days.loc[2, "halted_by_stop_loss"]))
        self.assertEqual(float(days.loc[2:, "staked"].sum()), 0.0)

    def test_positive_roi_does_not_promote_when_drawdown_exceeds_profit(self) -> None:
        decision = promotion_decision(
            {"bets": 135, "roi_pct": 7.01, "profit": 11.12, "max_drawdown": 15.13},
            {"ece": 0.003},
            profitable_invested_months=7,
            losing_invested_months=4,
        )

        self.assertEqual(decision, "NEED_MORE_DATA")


if __name__ == "__main__":
    unittest.main()
