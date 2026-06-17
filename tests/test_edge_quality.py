from football_agents.edge_quality import calculate_edge_quality
from football_agents.multi_devig import calculate_multi_devig_probabilities
from football_agents.probability_uncertainty import estimate_probability_uncertainty


def test_lower_bound_ev_blocks_edge():
    devig = calculate_multi_devig_probabilities({"home": 2.1, "draw": 3.2, "away": 3.4})
    uncertainty = estimate_probability_uncertainty({"finalProbability": {"home": .48, "draw": .28, "away": .24}}, devig, {"sample_reliability": .2})
    edge = calculate_edge_quality("HOME", 2.1, {"home": .48, "draw": .28, "away": .24}, uncertainty, None, {"method_agreement_score": 1}, .03)
    assert edge.lower_bound_ev <= 0
    assert not edge.passes_true_odds_filter


def test_high_quality_edge_can_pass():
    devig = calculate_multi_devig_probabilities({"home": 2.1, "draw": 3.2, "away": 3.4})
    uncertainty = estimate_probability_uncertainty({"finalProbability": {"home": .62, "draw": .22, "away": .16}}, devig, {"sample_reliability": 1})
    edge = calculate_edge_quality("HOME", 2.1, {"home": .62, "draw": .22, "away": .16}, uncertainty, None, {"method_agreement_score": 1, "external_market_quality": "HIGH"}, .03)
    assert edge.edge_quality_level in {"MEDIUM", "HIGH"}
    assert edge.passes_true_odds_filter
