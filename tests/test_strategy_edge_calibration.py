from __future__ import annotations

import pandas as pd

from scripts.strategy_edge_calibration import audit_edge_calibration


def test_edge_calibration_confirms_conservative_edge(tmp_path):
    rows = []
    for index in range(100):
        rows.append({
            "bet_date": "2026-01-01",
            "season": "2025-26",
            "rule_label": "draw-band",
            "odds": 3.0,
            "stake": 10.0,
            "won": index < 45,
            "profit": 20.0 if index < 45 else -10.0,
        })
    path = tmp_path / "bets.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    report = audit_edge_calibration(path, min_bets=80)

    assert report["decision"] == "CALIBRATED_EDGE_CONFIRMED"
    assert report["overall"]["hit_rate"] == 0.45
    assert report["overall"]["conservative_edge_vs_implied"] > 0


def test_edge_calibration_rejects_positive_but_tiny_sample(tmp_path):
    rows = [
        {
            "bet_date": "2026-01-01",
            "season": "2025-26",
            "rule_label": "tiny",
            "odds": 3.0,
            "stake": 10.0,
            "won": True,
            "profit": 20.0,
        }
        for _ in range(5)
    ]
    path = tmp_path / "bets.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    report = audit_edge_calibration(path, min_bets=80)

    assert report["decision"] == "POSITIVE_EDGE_BUT_NOT_CONSERVATIVE"
    assert "bets<minimum" in report["decision_reasons"]
