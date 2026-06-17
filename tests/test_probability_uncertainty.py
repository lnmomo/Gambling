from football_agents.multi_devig import calculate_multi_devig_probabilities
from football_agents.probability_uncertainty import estimate_probability_uncertainty


def test_uncertainty_bounds_are_ordered_and_finite():
    devig = calculate_multi_devig_probabilities({"home": 2.1, "draw": 3.2, "away": 3.4})
    result = estimate_probability_uncertainty({
        "finalProbability": {"home": .48, "draw": .28, "away": .24},
        "pureModelProbability": {"home": .45, "draw": .30, "away": .25},
    }, devig, {"sample_reliability": .8})
    assert abs(sum(result.mean.values()) - 1) < 1e-9
    for key in ("home", "draw", "away"):
        assert result.lower[key] <= result.mean[key] <= result.upper[key]
        assert result.std[key] > 0
