import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rule_exposure_grid_search import run_grid  # noqa: E402


def test_rule_exposure_grid_reports_window_metrics():
    rows = []
    for index in range(24):
        won = index % 3 == 0
        rows.append({
            "date": f"2024-{index // 2 + 1:02d}-01",
            "league": "L",
            "home_team": f"H{index}",
            "away_team": f"A{index}",
            "outcome": "home",
            "actual_result": "home" if won else "away",
            "odds": 3.5 if won else 2.0,
            "won": won,
            "rule_label": "r",
            "candidate_id": "candidate",
            "odds_source": "AVG_CLOSE",
        })

    result = run_grid(
        pd.DataFrame(rows),
        candidate_id="candidate",
        first_month="2024-01",
        last_month="2024-12",
        lookbacks=(4,),
        min_settlements=(2,),
        cooldowns=(14,),
    )

    assert result["grid_size"] == 1
    assert "active_pass_rate" in result["best"]
    assert result["best"]["active_window_count"] >= 1
