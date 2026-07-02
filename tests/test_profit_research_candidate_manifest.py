from __future__ import annotations

import json
from pathlib import Path


def test_i2_avg_close_manifest_is_shadow_only() -> None:
    manifest = json.loads(
        Path("reports/profit_strategy_research_candidates/i2_avg_close_stop3_cool14_v1/manifest.json")
        .read_text(encoding="utf-8")
    )

    assert manifest["strategy_id"] == "profit-i2-draw-market-anchored-avg-close-stop3-cool14-v1"
    assert manifest["status"] == "STATISTICALLY_CALIBRATED_RESEARCH_LEAD_WAITING_OFFICIAL_SP_SHADOW"
    assert manifest["selection"]["odds_source"] == "AVG_CLOSE"
    assert manifest["risk_control"]["cooldown_days"] == 14
    assert manifest["evidence_reports"]["statistical_audit"].endswith("/summary.json")
    assert manifest["evidence_reports"]["edge_calibration"].endswith("/summary.json")
    assert manifest["evidence_reports"]["official_pool_diagnosis"].endswith("/summary.json")
    assert manifest["evidence_reports"]["official_sp_validation"].endswith("/summary.json")
    assert "historical reports use football-data AVG_CLOSE, not China Sporttery official SP" in manifest["blockers"]
    assert any("shadow validation only" in item for item in manifest["freeze_notes"])
    assert any("200 settled selected official-SP" in item for item in manifest["promotion_requirements"])
