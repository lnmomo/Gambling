from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from football_agents.research.dataset import OddsTiming, audit_football_data, load_football_data
from football_agents.research.evaluation import evaluate_probabilities, paired_bootstrap_difference
from football_agents.research.features import FEATURE_COLUMNS, build_leakage_free_rolling_features
from football_agents.research.ml_baselines import ProbabilityBaselines
from football_agents.research.models import HierarchicalLeagueDixonColes, MarketAnchoredResidualModel, TimeDecayDixonColes


class ResearchFrameworkTests(unittest.TestCase):
    def test_dataset_audit_refuses_to_claim_exact_opening_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "E0.csv"
            pd.DataFrame([{
                "Div": "E0", "Date": "01/01/2025", "HomeTeam": "A", "AwayTeam": "B",
                "FTHG": 2, "FTAG": 1, "B365H": 2.0, "B365D": 3.2, "B365A": 4.0,
                "B365CH": 1.9, "B365CD": 3.3, "B365CA": 4.2,
            }]).to_csv(path, index=False)
            audit = audit_football_data(path)
            loaded = load_football_data(path, OddsTiming.PRE_CLOSING)
            self.assertFalse(audit.exact_snapshot_timestamps_available)
            self.assertEqual(audit.files_with_closing_odds, 1)
            self.assertEqual(loaded.loc[0, "odds_timing"], "pre_closing")
            self.assertEqual(loaded.loc[0, "closing_odds_home"], 1.9)

    def test_dixon_coles_uses_prior_attack_strength(self) -> None:
        rows = []
        for index in range(40):
            rows.append({
                "match_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                "home_team": "Strong" if index % 2 == 0 else "Weak",
                "away_team": "Weak" if index % 2 == 0 else "Strong",
                "home_goals": 3 if index % 2 == 0 else 0,
                "away_goals": 0 if index % 2 == 0 else 2,
            })
        model = TimeDecayDixonColes().fit(pd.DataFrame(rows), cutoff=pd.Timestamp("2025-01-01"))
        probability = model.predict("Strong", "Weak")
        self.assertGreater(probability["home"], probability["away"])

    def test_rolling_features_do_not_use_same_day_results(self) -> None:
        rows = pd.DataFrame([
            {"match_date": pd.Timestamp("2025-01-01"), "league": "L", "home_team": "A", "away_team": "B",
             "home_goals": 1, "away_goals": 0},
            {"match_date": pd.Timestamp("2025-01-02"), "league": "L", "home_team": "A", "away_team": "B",
             "home_goals": 2, "away_goals": 1},
        ])
        changed = rows.copy()
        changed.loc[1, ["home_goals", "away_goals"]] = [0, 9]
        first = build_leakage_free_rolling_features(rows)
        second = build_leakage_free_rolling_features(changed)
        self.assertTrue(first.loc[1, list(FEATURE_COLUMNS)].equals(second.loc[1, list(FEATURE_COLUMNS)]))

    def test_hierarchical_dixon_coles_returns_probabilities(self) -> None:
        rows = []
        for index in range(60):
            rows.append({"match_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                         "league": "L1" if index < 30 else "L2", "home_team": f"H{index % 4}",
                         "away_team": f"A{index % 4}", "home_goals": 2, "away_goals": index % 2})
        model = HierarchicalLeagueDixonColes().fit(pd.DataFrame(rows), cutoff=pd.Timestamp("2025-01-01"))
        probability = model.predict("H1", "A1", "L1")
        self.assertAlmostEqual(sum(probability.values()), 1.0)

    def test_market_anchored_model_returns_simplex(self) -> None:
        rng = np.random.default_rng(9)
        market = rng.dirichlet([4, 3, 3], size=500)
        football = rng.dirichlet([3, 3, 3], size=500)
        outcomes = np.array([("home", "draw", "away")[index] for index in
                             [rng.choice(3, p=row) for row in market]])
        leagues = np.where(np.arange(500) % 2, "A", "B")
        features = rng.normal(size=(500, 4))
        model = MarketAnchoredResidualModel().fit(
            market[:350], football[:350], outcomes[:350], leagues[:350], features[:350],
        )
        model.calibrate(market[350:425], football[350:425], outcomes[350:425], leagues[350:425], features[350:425])
        predicted = model.predict(market[425:], football[425:], leagues[425:], features[425:])
        self.assertTrue(np.allclose(predicted.sum(axis=1), 1))
        self.assertTrue(np.all(predicted > 0))

    def test_metrics_and_bootstrap_are_reproducible(self) -> None:
        outcomes = np.array(["home", "draw", "away", "home"])
        first = np.array([[.7, .2, .1], [.2, .6, .2], [.1, .2, .7], [.6, .2, .2]])
        second = np.full((4, 3), 1 / 3)
        metrics = evaluate_probabilities(first, outcomes)
        log_loss = lambda p, y: float(evaluate_probabilities(p, y)["log_loss"])
        one = paired_bootstrap_difference(first, second, outcomes, log_loss, samples=100, seed=5)
        two = paired_bootstrap_difference(first, second, outcomes, log_loss, samples=100, seed=5)
        self.assertLess(metrics["log_loss"], 1.0)
        self.assertEqual(one, two)

    def test_ml_baselines_preserve_outcome_order(self) -> None:
        rng = np.random.default_rng(4)
        features = rng.normal(size=(120, 5))
        outcomes = np.array((["home", "draw", "away"] * 40))
        predictions = ProbabilityBaselines(seed=3).fit(features, outcomes).predict(features[:5])
        self.assertEqual(set(predictions), {"multinomial_logit", "random_forest", "hist_gradient_boosting"})
        self.assertTrue(all(np.allclose(values.sum(axis=1), 1) for values in predictions.values()))


if __name__ == "__main__":
    unittest.main()
