import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_walk_forward import select_market_rules  # noqa: E402


def _month(good_profit: float, volatile_profit: float) -> dict:
    return {
        "rule_results": {
            "stable": {"bets": 10, "profit": good_profit, "total_staked": 10.0},
            "volatile": {"bets": 10, "profit": volatile_profit, "total_staked": 10.0},
        }
    }


def test_select_market_rules_prefers_recent_stable_lcb_over_higher_total_profit():
    history = [
        _month(1.0, 18.0),
        _month(1.0, 18.0),
        _month(1.0, -6.0),
        _month(1.0, -6.0),
        _month(1.0, -6.0),
        _month(1.0, 1.0),
    ]

    selected, report = select_market_rules(
        history,
        min_active_months=3,
        min_bets=30,
        min_roi=0.01,
        max_rules=2,
    )

    assert selected == ["stable"]
    assert report["selected"][0]["edge_lcb"] > 0
    assert report["stability_filters"]["edge_lcb_must_be_positive"] is True
