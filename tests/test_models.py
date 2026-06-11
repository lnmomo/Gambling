import unittest

from football_agents.models import EloModel, EnsembleModel, PoissonModel
from football_agents.models.ensemble import market_probabilities


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


if __name__ == "__main__":
    unittest.main()

