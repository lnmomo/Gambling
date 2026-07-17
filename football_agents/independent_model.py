from __future__ import annotations

from typing import Mapping

from .models.ensemble import normalize


INDEPENDENT_MODEL_WEIGHTS = {"elo": 0.60, "poisson": 0.40}


def independent_football_probability(
    elo_probability: Mapping[str, float],
    poisson_probability: Mapping[str, float],
) -> dict[str, float]:
    elo = normalize(elo_probability)
    poisson = normalize(poisson_probability)
    return normalize({
        outcome: (
            INDEPENDENT_MODEL_WEIGHTS["elo"] * elo[outcome]
            + INDEPENDENT_MODEL_WEIGHTS["poisson"] * poisson[outcome]
        )
        for outcome in ("home", "draw", "away")
    })
