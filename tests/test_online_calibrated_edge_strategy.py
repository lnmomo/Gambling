import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from online_calibrated_edge_strategy import _bucket_report, _settle_month  # noqa: E402


def test_bucket_report_uses_prior_history_before_current_settlement():
    current = pd.DataFrame([{
        "date": "2025-01-01",
        "month": "2025-01",
        "league": "L",
        "home_team": "H",
        "away_team": "A",
        "outcome": "home",
        "actual_result": "home",
        "probability": 0.6,
        "market_probability": 0.5,
        "model_market_delta": 0.1,
        "lower_ev": 0.05,
        "odds": 2.0,
        "odds_bucket": "[1.8,2.2)",
        "won": True,
        "unit_profit": 1.0,
        "bucket_id": "L|home|[1.8,2.2)",
    }])

    allowed, _ = _bucket_report(
        pd.DataFrame(),
        min_samples=1,
        min_roi=0.0,
        min_positive_month_edge=0,
    )
    _, bets = _settle_month(current, allowed, stake=1.0)
    assert bets.empty

    allowed_after_history, _ = _bucket_report(
        current,
        min_samples=1,
        min_roi=0.0,
        min_positive_month_edge=0,
    )
    _, bets_after_history = _settle_month(current, allowed_after_history, stake=1.0)
    assert len(bets_after_history) == 1
