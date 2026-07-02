import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from low_correlation_rule_combo_search import load_unit_bets, run_low_correlation_search  # noqa: E402


def test_low_correlation_search_dedupes_and_reports_active_windows(tmp_path):
    rows = []
    for month in range(1, 13):
        for rule in ("AVG_CLOSE::rule-a", "AVG_CLOSE::rule-b"):
            odds_source, rule_label = rule.split("::", 1)
            won = month % 3 != 0 if rule_label == "rule-a" else month % 4 != 0
            rows.append({
                "date": f"2024-{month:02d}-01",
                "league": "L",
                "home_team": f"H{month}",
                "away_team": f"A{month}",
                "outcome": "home" if rule_label == "rule-a" else "away",
                "actual_result": "home" if won else "draw",
                "odds": 2.4 if won else 2.0,
                "odds_source": odds_source,
                "rule_label": rule_label,
                "stake": 1.0,
                "profit": 1.4 if won else -1.0,
            })
    rows.append(rows[0].copy())
    path = tmp_path / "unit_bets.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    unit_bets = load_unit_bets([path])
    result = run_low_correlation_search(
        unit_bets,
        first_month="2024-01",
        last_month="2024-12",
        combo_size=2,
        max_rules=5,
        min_rule_bets=1,
        min_rule_roi_pct=-100.0,
        max_pairwise_corr=1.0,
        window_months=12,
        step_months=6,
        min_window_bets=1,
        min_window_roi_pct=-100.0,
        min_positive_month_edge=-12,
        max_drawdown_to_profit=999.0,
    )

    assert len(unit_bets) == 24
    assert result["best"]["rule_count"] == 2
    assert result["best"]["active_window_count"] == 1
