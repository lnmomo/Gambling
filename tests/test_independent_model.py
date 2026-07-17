from football_agents.independent_model import (
    INDEPENDENT_MODEL_WEIGHTS,
    independent_football_probability,
)


def test_independent_model_uses_frozen_elo_poisson_weights() -> None:
    probability = independent_football_probability(
        {"home": 0.60, "draw": 0.25, "away": 0.15},
        {"home": 0.30, "draw": 0.30, "away": 0.40},
    )

    assert INDEPENDENT_MODEL_WEIGHTS == {"elo": 0.60, "poisson": 0.40}
    assert probability["home"] == 0.48
    assert probability["draw"] == 0.27
    assert probability["away"] == 0.25
    assert sum(probability.values()) == 1.0
