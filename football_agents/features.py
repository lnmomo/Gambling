from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .models import EloModel
from .repository import Repository


TEAM_ALIASES = {
    "\u7f8e\u56fd": "United States", "\u5fb7\u56fd": "Germany", "\u6fb3\u5927\u5229\u4e9a": "Australia",
    "\u745e\u58eb": "Switzerland", "\u5df4\u62ff\u9a6c": "Panama", "\u6ce2\u9ed1": "Bosnia and Herzegovina",
    "\u82f1\u683c\u5170": "England", "\u65b0\u897f\u5170": "New Zealand", "\u73bb\u5229\u7ef4\u4e9a": "Bolivia",
    "\u82cf\u683c\u5170": "Scotland", "\u5df4\u897f": "Brazil", "\u57c3\u53ca": "Egypt", "\u59d4\u5185\u745e\u62c9": "Venezuela",
    "\u571f\u8033\u5176": "Turkey", "\u963f\u6839\u5ef7": "Argentina", "\u6d2a\u90fd\u62c9\u65af": "Honduras",
    "\u514b\u7f57\u5730\u4e9a": "Croatia", "\u65af\u6d1b\u6587\u5c3c": "Slovenia", "\u65af\u6d1b\u6587\u5c3c\u4e9a": "Slovenia",
    "\u6469\u6d1b\u54e5": "Morocco", "\u632a\u5a01": "Norway", "\u5e0c\u814a": "Greece", "\u610f\u5927\u5229": "Italy",
    "\u54e5\u4f26\u6bd4\u4e9a": "Colombia", "\u7ea6\u65e6": "Jordan", "\u8377\u5170": "Netherlands",
    "\u4e4c\u5179\u522b\u514b": "Uzbekistan", "\u4e4c\u5179\u522b\u514b\u65af\u5766": "Uzbekistan", "\u6cd5\u56fd": "France",
    "\u5317\u7231\u5c14\u5170": "Northern Ireland", "\u79d8\u9c81": "Peru", "\u897f\u73ed\u7259": "Spain",
    "\u4e2d\u56fd": "China", "\u4e2d\u56fd\u961f": "China", "\u6cf0\u56fd": "Thailand", "\u5308\u7259\u5229": "Hungary",
    "\u54c8\u8428\u514b": "Kazakhstan", "\u54c8\u8428\u514b\u65af\u5766": "Kazakhstan", "\u51b0\u5c9b": "Iceland",
    "\u8461\u8404\u7259": "Portugal", "\u5c3c\u65e5\u5229\u4e9a": "Nigeria", "\u54e5\u65af\u8fbe": "Costa Rica",
    "\u54e5\u65af\u8fbe\u9ece\u52a0": "Costa Rica", "\u58a8\u897f\u54e5": "Mexico", "\u5357\u975e": "South Africa",
    "\u97e9\u56fd": "South Korea", "\u6377\u514b": "Czech Republic", "\u52a0\u62ff\u5927": "Canada",
    "\u5df4\u62c9\u572d": "Paraguay", "\u5361\u5854\u5c14": "Qatar", "\u6d77\u5730": "Haiti", "\u5e93\u62c9\u7d22": "Cura\u00e7ao",
    "\u65e5\u672c": "Japan", "\u79d1\u7279\u8fea\u74e6": "Ivory Coast", "\u5384\u74dc\u591a\u5c14": "Ecuador",
    "\u745e\u5178": "Sweden", "\u7a81\u5c3c\u65af": "Tunisia", "\u4f5b\u5f97\u89d2": "Cape Verde", "\u6bd4\u5229\u65f6": "Belgium",
    "\u6c99\u7279": "Saudi Arabia", "\u6c99\u7279\u963f\u62c9\u4f2f": "Saudi Arabia", "\u4e4c\u62c9\u572d": "Uruguay",
    "\u4f0a\u6717": "Iran", "\u585e\u5185\u52a0\u5c14": "Senegal", "\u4f0a\u62c9\u514b": "Iraq",
}


def canonical_team_name(name: str) -> str:
    compact = re.sub(r"\s+", "", str(name).strip())
    return TEAM_ALIASES.get(compact, str(name).strip())


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class HistoricalFeatureBuilder:
    """Build pre-match features only from results available before kickoff."""

    def __init__(self, repository: Repository, min_matches: int = 10, half_life_days: int = 90) -> None:
        self.repository = repository
        self.min_matches = min_matches
        self.half_life_days = half_life_days

    def build(self, match: dict[str, Any]) -> dict[str, Any]:
        home = canonical_team_name(match["home_team"])
        away = canonical_team_name(match["away_team"])
        rows = self.repository.list_historical_matches(
            cutoff_time=match["kickoff_time"], teams=[home, away], limit=100_000
        )
        home_rows = [row for row in rows if home in {row["home_team"], row["away_team"]}]
        away_rows = [row for row in rows if away in {row["home_team"], row["away_team"]}]
        if len(home_rows) < self.min_matches or len(away_rows) < self.min_matches:
            return {"built": False, "reason": "insufficient_history", "home_team": home,
                    "away_team": away, "home_matches": len(home_rows), "away_matches": len(away_rows)}

        elo = EloModel(k_factor=20, home_advantage=65)
        for row in rows:
            elo.k_factor = {"FRIENDLY": 10, "CUP": 25}.get(row["match_type"], 20)
            elo.update(row["home_team"], row["away_team"], row["home_goals"], row["away_goals"])

        average_team_goals = max(
            0.5, sum(row["home_goals"] + row["away_goals"] for row in rows) / max(1, 2 * len(rows))
        )
        kickoff = _parse_time(match["kickoff_time"])
        home_stats = self._team_stats(home, home_rows, kickoff)
        away_stats = self._team_stats(away, away_rows, kickoff)
        home_reliability = min(1.0, home_stats["effective_matches"] / 20)
        away_reliability = min(1.0, away_stats["effective_matches"] / 20)
        home_attack = self._shrunk_ratio(home_stats["goals_for"], average_team_goals, home_reliability)
        home_defence = self._shrunk_ratio(home_stats["goals_against"], average_team_goals, home_reliability)
        away_attack = self._shrunk_ratio(away_stats["goals_for"], average_team_goals, away_reliability)
        away_defence = self._shrunk_ratio(away_stats["goals_against"], average_team_goals, away_reliability)

        features = {
            "home_rating": round(elo.rating(home), 3), "away_rating": round(elo.rating(away), 3),
            "lambda_home": round(min(4.0, max(0.25, average_team_goals * 1.08 * home_attack * away_defence)), 4),
            "lambda_away": round(min(3.5, max(0.20, average_team_goals / 1.08 * away_attack * home_defence)), 4),
            "home_recent_matches": len(home_rows), "away_recent_matches": len(away_rows),
            "home_weighted_goals_for": round(home_stats["goals_for"], 4),
            "home_weighted_goals_against": round(home_stats["goals_against"], 4),
            "away_weighted_goals_for": round(away_stats["goals_for"], 4),
            "away_weighted_goals_against": round(away_stats["goals_against"], 4),
            "historical_home_team": home, "historical_away_team": away,
            "history_cutoff": match["kickoff_time"],
            "source_confidence": round(0.45 + 0.5 * min(home_reliability, away_reliability), 3),
        }
        self.repository.add_features(match["id"], features, version="historical-v1")
        return {"built": True, "features": features}

    def _team_stats(self, team: str, rows: list[dict[str, Any]], kickoff: datetime) -> dict[str, float]:
        weighted_for = weighted_against = total_weight = 0.0
        for row in rows:
            days = max(0.0, (kickoff - _parse_time(row["played_at"])).total_seconds() / 86400)
            weight = math.exp(-math.log(2) * days / self.half_life_days)
            if row["home_team"] == team:
                goals_for, goals_against = row["home_goals"], row["away_goals"]
            else:
                goals_for, goals_against = row["away_goals"], row["home_goals"]
            weighted_for += goals_for * weight
            weighted_against += goals_against * weight
            total_weight += weight
        return {"goals_for": weighted_for / total_weight, "goals_against": weighted_against / total_weight,
                "effective_matches": total_weight}

    @staticmethod
    def _shrunk_ratio(value: float, baseline: float, reliability: float) -> float:
        return 1 + reliability * (value / baseline - 1)
