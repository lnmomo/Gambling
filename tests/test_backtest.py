import csv
import unittest
from pathlib import Path

from football_agents.backtesting import BacktestEngine


class BacktestTests(unittest.TestCase):
    def test_sample_backtest(self):
        path = Path("football_agents/sample_data/historical_matches.csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            report = BacktestEngine().run(list(csv.DictReader(handle)))
        self.assertEqual(report["metrics"]["matches"], 6)
        self.assertGreater(report["metrics"]["brier_score"], 0)
        self.assertEqual(len(report["equity"]), 7)


if __name__ == "__main__":
    unittest.main()

