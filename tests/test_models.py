import unittest

from football_agents.models import EloModel, EnsembleModel, PoissonModel
from football_agents.models.ensemble import market_probabilities, market_residual_anchor


class ModelTests(unittest.TestCase):
    def test_probabilities_sum_to_one(self):
        predictions = [
            EloModel().predict("A", "B"),
            PoissonModel().predict(1.6, 0.9),
            market_probabilities({"home": 2.0, "draw": 3.4, "away": 4.0}),
        ]
        for prediction in predictions:
            self.assertAlmostEqual(sum(prediction.values()), 1.0, places=8)
            self.assertTrue(all(0 <= value <= 1 for value in prediction.values()))

    def test_ensemble_favors_stronger_consensus(self):
        model = EnsembleModel()
        result = model.predict({
            "elo": {"home": .6, "draw": .25, "away": .15},
            "poisson": {"home": .58, "draw": .26, "away": .16},
            "market": {"home": .55, "draw": .27, "away": .18},
        })
        self.assertEqual(max(result, key=result.get), "home")

    def test_market_residual_anchor_caps_sparse_longshot_edges(self):
        market = {"home": .14, "draw": .23, "away": .63}
        raw_model = {"home": .32, "draw": .25, "away": .43}
        anchored, metadata = market_residual_anchor(raw_model, market, reliability=.55)
        self.assertAlmostEqual(sum(anchored.values()), 1.0, places=8)
        self.assertTrue(metadata["capped"])
        self.assertLess(anchored["home"] - market["home"], .05)
        self.assertGreater(anchored["away"], raw_model["away"])


if __name__ == "__main__":
    unittest.main()

