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
        self.assertEqual(candidates.iloc[0]["strength_gap_bucket"], "strength_close")
        self.assertEqual(candidates.iloc[0]["goal_env_bucket"], "goal_env_mid")

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
