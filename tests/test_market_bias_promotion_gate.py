import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_promotion_gate import evaluate_market_bias_promotion  # noqa: E402


def robust():
    return {
        "decision": "RESEARCH_CANDIDATE_SHADOW_VALIDATION",
        "total_runs": 24,
        "passed_runs": 22,
        "source_passes": 8,
        "profile_passes": 3,
        "rules": ["league|outcome|odds_bucket=I2|draw|[2.8,3.5)"],
    }


def portfolio():
    return {
        "overall": {"profit": 827.6, "roi_pct": 9.5, "max_drawdown": 225.0},
        "positive_months": 17,
        "negative_months": 11,
        "positive_seasons": 3,
        "negative_seasons": 1,
    }


def test_market_bias_promotion_gate_blocks_production_when_official_sample_missing():
    official = {
        "settled_candidate_count": 0,
        "roi_pct": 0.0,
        "positive_months": 0,
        "negative_months": 0,
        "monthly": [],
    }
    result = evaluate_market_bias_promotion(robust(), portfolio(), official)
    assert result["decision"] == "SHADOW_READY_PRODUCTION_BLOCKED"
    assert result["strategy_id"] == "league|outcome|odds_bucket=I2|draw|[2.8,3.5)"
    assert result["recommended_for_shadow"] is True
    assert result["recommended_for_production"] is False
    assert "official_sample" in result["failed_production_checks"]


def test_market_bias_promotion_gate_allows_production_candidate_after_official_validation():
    official = {
        "settled_candidate_count": 180,
        "roi_pct": 6.0,
        "positive_months": 9,
        "negative_months": 4,
        "monthly": [{"month": f"2027-{month:02d}"} for month in range(1, 14)],
    }
    result = evaluate_market_bias_promotion(robust(), portfolio(), official)
    assert result["decision"] == "PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION"
    assert result["recommended_for_production"] is True


def test_market_bias_promotion_gate_uses_official_strategy_id_when_available():
    official = {
        "strategy_id": "market-bias-sp1-home-market-prob-0.55-1.00-v1",
        "settled_candidate_count": 0,
        "roi_pct": 0.0,
        "positive_months": 0,
        "negative_months": 0,
        "monthly": [],
    }
    result = evaluate_market_bias_promotion(robust(), portfolio(), official)
    assert result["strategy_id"] == "market-bias-sp1-home-market-prob-0.55-1.00-v1"


def test_market_bias_promotion_gate_explicit_strategy_id_wins():
    official = {
        "strategy_id": "market-bias-sp1-home-market-prob-0.55-1.00-v1",
        "settled_candidate_count": 0,
        "roi_pct": 0.0,
        "positive_months": 0,
        "negative_months": 0,
        "monthly": [],
    }
    result = evaluate_market_bias_promotion(
        robust(),
        portfolio(),
        official,
        {"strategy_id": "manual-strategy"},
    )
    assert result["strategy_id"] == "manual-strategy"
