import unittest
from datetime import datetime, timedelta, timezone

from football_agents.risk import CriticPolicy, RiskLimits, calculate_stake


class RiskTests(unittest.TestCase):
    def test_stale_odds_are_vetoed(self):
        report = CriticPolicy().evaluate(
            odds_fetched_at=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            source_confidence=.95, disagreement=.02, ev=.12, match_status="scheduled",
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["data_fresh"])

    def test_stake_respects_hard_cap(self):
        stake = calculate_stake(10_000, .70, 2.2, RiskLimits(max_single_fraction=.01))
        self.assertLessEqual(stake, 100)

    def test_loss_pause_vetoes(self):
        report = CriticPolicy().evaluate(
            odds_fetched_at=datetime.now(timezone.utc).isoformat(), source_confidence=.95,
            disagreement=.02, ev=.12, match_status="scheduled", consecutive_losses=3,
        )
        self.assertFalse(report["checks"]["loss_pause_clear"])


if __name__ == "__main__":
    unittest.main()

