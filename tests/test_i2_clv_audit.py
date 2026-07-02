import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from i2_clv_audit import _band, _summary  # noqa: E402


def test_band_assigns_i2_draw_ranges() -> None:
    assert _band(2.79) == "[0,2.8)"
    assert _band(2.80) == "[2.8,3.3)"
    assert _band(3.30) == "[3.3,3.5)"
    assert _band(3.50) == "[3.5,inf)"


def test_summary_reports_positive_clv_and_closing_edge() -> None:
    frame = pd.DataFrame([
        {
            "stake": 10.0, "profit": 20.0, "won": True, "odds": 3.2, "close_odds": 3.0,
            "clv": 3.2 / 3.0 - 1.0, "raw_closing_price_edge": 3.2 / 3.0 - 1.0,
            "no_vig_closing_edge": 0.03,
        },
        {
            "stake": 10.0, "profit": -10.0, "won": False, "odds": 3.1, "close_odds": 3.2,
            "clv": 3.1 / 3.2 - 1.0, "raw_closing_price_edge": 3.1 / 3.2 - 1.0,
            "no_vig_closing_edge": -0.01,
        },
    ])

    summary = _summary(frame, "x")

    assert summary["bets"] == 2
    assert summary["profit"] == 10.0
    assert summary["roi_pct"] == 50.0
    assert summary["positive_clv_rate"] == 0.5
    assert summary["avg_no_vig_closing_edge_pct"] == 1.0


def test_summary_handles_empty_frame() -> None:
    summary = _summary(pd.DataFrame(), "empty")

    assert summary["bets"] == 0
    assert summary["avg_clv_pct"] == 0.0
