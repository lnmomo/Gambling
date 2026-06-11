from __future__ import annotations

import math


class PoissonModel:
    def __init__(self, max_goals: int = 10, rho: float = -0.08) -> None:
        self.max_goals = max_goals
        self.rho = rho

    @staticmethod
    def _pmf(k: int, rate: float) -> float:
        return math.exp(-rate) * rate**k / math.factorial(k)

    def _tau(self, home: int, away: int, lh: float, la: float) -> float:
        if home == 0 and away == 0:
            return 1 - lh * la * self.rho
        if home == 0 and away == 1:
            return 1 + lh * self.rho
        if home == 1 and away == 0:
            return 1 + la * self.rho
        if home == 1 and away == 1:
            return 1 - self.rho
        return 1.0

    def predict(self, lambda_home: float, lambda_away: float) -> dict[str, float]:
        lambda_home = min(5.0, max(0.15, lambda_home))
        lambda_away = min(5.0, max(0.15, lambda_away))
        result = {"home": 0.0, "draw": 0.0, "away": 0.0}
        total = 0.0
        for home in range(self.max_goals + 1):
            for away in range(self.max_goals + 1):
                probability = self._pmf(home, lambda_home) * self._pmf(away, lambda_away)
                probability *= self._tau(home, away, lambda_home, lambda_away)
                total += probability
                key = "home" if home > away else "draw" if home == away else "away"
                result[key] += probability
        return {key: value / total for key, value in result.items()}

