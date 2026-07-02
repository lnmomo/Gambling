import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rule_exposure_control import simulate_rule_exposure_control  # noqa: E402


def test_rule_exposure_control_uses_settled_losses_before_cooling_rule():
    rows = []
    for index, day in enumerate(["2024-01-01", "2024-01-03", "2024-01-05"]):
        rows.append({
            "date": day,
            "league": "L",
            "home_team": f"H{index}",
            "away_team": f"A{index}",
            "outcome": "home",
            "actual_result": "away",
            "odds": 2.0,
            "won": False,
            "rule_label": "bad-rule",
            "candidate_id": "candidate",
            "odds_source": "AVG_CLOSE",
        })
    rows.append({
        "date": "2024-01-07",
        "league": "L",
        "home_team": "H3",
        "away_team": "A3",
        "outcome": "home",
        "actual_result": "home",
        "odds": 2.0,
        "won": True,
        "rule_label": "bad-rule",
        "candidate_id": "candidate",
        "odds_source": "AVG_CLOSE",
    })

    summary, _, bets = simulate_rule_exposure_control(
        pd.DataFrame(rows),
        candidate_id="candidate",
        settlement_delay_days=1,
        min_rule_settlements=2,
        rule_lookback_settlements=2,
        min_rule_profit=0.0,
        cooldown_days=10,
    )

    assert summary["overall"]["bets"] == 2
    assert summary["overall"]["skipped_by_rule_cooldown"] == 2
    assert bets["bet_date"].tolist() == ["2024-01-01", "2024-01-03"]
