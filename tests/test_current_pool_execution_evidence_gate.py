from scripts.current_pool_execution_evidence_gate import EvidenceThresholds, evaluate_domain


def _evidence(*, roi: float = 5.0, supported: bool = True, calibrated: bool = True):
    rolling = {
        "selection_uses_validation_data": False,
        "validation_windows_overlap": False,
        "summary": {
            "bets": 300,
            "profit": 15.0,
            "roi_pct": roi,
            "active_window_count": 6,
            "active_passed_windows": 4,
            "active_pass_rate": 0.6667,
        },
    }
    statistical = {
        "decision": "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE" if supported else "REJECT_STATISTICALLY_WEAK",
        "bootstrap": {"roi_ci_pct": {"p05": 1.0}},
    }
    calibration = {
        "decision": "CALIBRATED_EDGE_CONFIRMED" if calibrated else "NO_CALIBRATED_EDGE",
        "overall": {"conservative_edge_vs_implied": 0.01},
    }
    return rolling, statistical, calibration


def test_domain_requires_both_representative_price_sources():
    result = evaluate_domain(
        "USA",
        {"AVG_CLOSE": _evidence()},
        {"decision": "EVIDENCE_READY", "research_usable": True},
        EvidenceThresholds(),
    )

    assert result["decision"] == "REJECTED_HISTORICAL_EVIDENCE"
    assert result["missing_sources"] == ["PS_CLOSE"]


def test_domain_waits_for_official_sp_after_historical_pass():
    result = evaluate_domain(
        "USA",
        {"AVG_CLOSE": _evidence(), "PS_CLOSE": _evidence()},
        {"decision": "EVIDENCE_COLLECTING", "research_usable": False},
        EvidenceThresholds(),
    )

    assert result["historical_passed"] is True
    assert result["decision"] == "HISTORICALLY_SUPPORTED_AWAIT_OFFICIAL_SP"


def test_domain_rejects_when_one_source_fails():
    result = evaluate_domain(
        "USA",
        {"AVG_CLOSE": _evidence(), "PS_CLOSE": _evidence(roi=-2.0, supported=False, calibrated=False)},
        {"decision": "EVIDENCE_READY", "research_usable": True},
        EvidenceThresholds(),
    )

    assert result["historical_passed"] is False
    assert result["decision"] == "REJECTED_HISTORICAL_EVIDENCE"
    assert "roi<minimum" in result["sources"][1]["reasons"]
