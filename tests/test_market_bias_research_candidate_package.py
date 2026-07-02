import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_research_candidate_package import build_research_candidate_package  # noqa: E402


def test_research_package_keeps_cross_source_candidate_out_of_shadow_when_robustness_fails():
    rule = "league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)"
    result = build_research_candidate_package(
        strategy_id="research-market-bias-jpn-away-market-prob-0.28-0.34-v1",
        rule=rule,
        robustness={
            "decision": "KEEP_SHADOW_ONLY",
            "passed_runs": 4,
            "total_runs": 12,
            "source_passes": 2,
            "profile_passes": 3,
            "rules": [rule],
        },
        portfolio={
            "overall": {"profit": 211.4, "roi_pct": 6.24, "max_drawdown": 165.8},
            "positive_months": 27,
            "negative_months": 20,
            "positive_seasons": 7,
            "negative_seasons": 3,
        },
        candidate_screen={
            "rule_summary": [{
                "rule": rule,
                "passes_all_validation_sources": True,
                "passed_validation_sources": 2,
                "validation_source_count": 2,
            }],
        },
    )

    assert result["classification"] == "RESEARCH_WATCH_ONLY"
    assert result["promotion_decision"] == "REJECT_RESEARCH_CANDIDATE"
    assert result["recommended_for_shadow"] is False
    assert result["recommended_for_production"] is False
    assert "robust_decision" in result["failed_blocking_checks"]
    assert "source_passes" in result["failed_blocking_checks"]
