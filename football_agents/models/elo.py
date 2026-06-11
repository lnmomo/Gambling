from __future__ import annotations

import math


class EloModel:
    def __init__(self, base_rating: float = 1500, k_factor: float = 24, home_advantage: float = 65) -> None:
        self.base_rating = base_rating
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.ratings: dict[str, float] = {}

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.base_rating)

    def predict(self, home_team: str, away_team: str, home_rating: float | None = None,
                away_rating: float | None = None) -> dict[str, float]:
        rh = self.rating(home_team) if home_rating is None else home_rating
        ra = self.rating(away_team) if away_rating is None else away_rating
        expected_home = 1 / (1 + 10 ** (-(rh - ra + self.home_advantage) / 400))
        closeness = math.exp(-abs(rh - ra + self.home_advantage) / 380)
        draw = min(0.32, max(0.16, 0.29 * closeness))
        home = expected_home * (1 - draw)
        away = (1 - expected_home) * (1 - draw)
        return {"home": home, "draw": draw, "away": away}

    def update(self, home_team: str, away_team: str, home_score: int, away_score: int) -> None:
        rh, ra = self.rating(home_team), self.rating(away_team)
        expected = 1 / (1 + 10 ** (-(rh - ra + self.home_advantage) / 400))
        actual = 1.0 if home_score > away_score else 0.5 if home_score == away_score else 0.0
        margin = max(1, abs(home_score - away_score))
        multiplier = math.log1p(margin) * (2.2 / (2.2 + abs(rh - ra) * 0.001))
        delta = self.k_factor * multiplier * (actual - expected)
        self.ratings[home_team] = rh + delta
        self.ratings[away_team] = ra - delta

