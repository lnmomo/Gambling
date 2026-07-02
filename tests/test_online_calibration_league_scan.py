import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from online_calibration_league_scan import _decision  # noqa: E402


def test_league_scan_decision_requires_sample_profit_and_month_balance():
    assert _decision({
        "overall": {"bets": 3, "profit": 10.0, "roi_pct": 50.0, "max_drawdown": 1.0},
        "positive_months": 2,
        "negative_months": 0,
    }, min_bets=5) == "TOO_FEW_BETS"

    assert _decision({
        "overall": {"bets": 10, "profit": -1.0, "roi_pct": -10.0, "max_drawdown": 3.0},
        "positive_months": 2,
        "negative_months": 1,
    }, min_bets=5) == "REJECT_NEGATIVE"

    assert _decision({
        "overall": {"bets": 10, "profit": 4.0, "roi_pct": 40.0, "max_drawdown": 3.0},
        "positive_months": 3,
        "negative_months": 1,
    }, min_bets=5) == "RESEARCH_WATCH"
