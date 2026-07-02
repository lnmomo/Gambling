import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_robustness_gate import _row_passes  # noqa: E402


def passing_row():
    return {
        "bets": 250,
        "roi_pct": 7.5,
        "profit": 18.75,
        "active_months": 14,
        "positive_months": 8,
        "negative_months": 6,
        "max_drawdown": 10.0,
        "latest_season_bets": 40,
        "latest_season_profit": 3.0,
        "positive_seasons": 3,
        "negative_seasons": 1,
    }


def test_market_bias_robustness_row_passes_when_stable():
    passed, reasons = _row_passes(passing_row())
    assert passed
    assert reasons == []


def test_market_bias_robustness_row_rejects_recent_degradation():
    row = passing_row()
    row["latest_season_profit"] = -2.0
    row["positive_months"] = 5
    row["negative_months"] = 8
    passed, reasons = _row_passes(row)
    assert not passed
    assert "latest_season_profit<0" in reasons
    assert "positive_months<=negative_months" in reasons
