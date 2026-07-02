from __future__ import annotations

import pandas as pd

from scripts.strategy_statistical_audit import audit_bets_csv


def test_statistical_audit_accepts_stable_positive_months(tmp_path):
    rows = []
    for month in range(1, 13):
        for index in range(20):
            rows.append({
                "bet_date": f"2026-{month:02d}-01",
                "month": f"2026-{month:02d}",
                "stake": 10.0,
                "profit": 1.0,
                "rule_label": "stable",
            })
    path = tmp_path / "bets.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    report = audit_bets_csv(path, iterations=300, seed=7, min_bets=100, min_months=6)

    assert report["decision"] == "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
    assert report["bootstrap"]["roi_ci_pct"]["p05"] > 0
    assert report["sign_flip_test"]["one_sided_p_value"] <= 0.05


def test_statistical_audit_rejects_tiny_positive_sample(tmp_path):
    path = tmp_path / "bets.csv"
    pd.DataFrame([
        {"bet_date": "2026-01-01", "month": "2026-01", "stake": 10.0, "profit": 20.0, "rule_label": "tiny"},
        {"bet_date": "2026-02-01", "month": "2026-02", "stake": 10.0, "profit": -10.0, "rule_label": "tiny"},
    ]).to_csv(path, index=False)

    report = audit_bets_csv(path, iterations=300, seed=7, min_bets=100, min_months=6)

    assert report["decision"] != "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE"
    assert "bets<minimum" in report["decision_reasons"]
    assert "active_months<minimum" in report["decision_reasons"]
