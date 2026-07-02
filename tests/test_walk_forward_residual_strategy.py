from __future__ import annotations

import numpy as np
import pandas as pd
import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.walk_forward_residual_strategy import (
    IsotonicPAV,
    PortfolioConfig,
    build_feature_history,
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


if __name__ == "__main__":
    unittest.main()
