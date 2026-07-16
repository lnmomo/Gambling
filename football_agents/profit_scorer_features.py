from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .features import canonical_team_name
from .models import EloModel
from .repository import Repository


LeagueMatcher = Callable[[Any], bool]
FEATURE_ENGINE = "market-anchored-research-parity-v1"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _played_date(value: Any) -> str:
    return str(value or "")[:10]


def _points(goals_for: int, goals_against: int) -> float:
    return 3.0 if goals_for > goals_against else 1.0 if goals_for == goals_against else 0.0


def _recent_form(history: list[dict[str, float]], window: int = 5) -> dict[str, float]:
    recent = history[-window:]
    if not recent:
        return {"points": 1.0, "goal_diff": 0.0}
    count = float(len(recent))
    goals_for = sum(row["goals_for"] for row in recent) / count
    goals_against = sum(row["goals_against"] for row in recent) / count
    return {
        "points": sum(row["points"] for row in recent) / count,
        "goal_diff": goals_for - goals_against,
    }


def _rate(stats: dict[str, float] | None) -> dict[str, float]:
    values = stats or {}
    matches = float(values.get("matches", 0.0))
    if matches <= 0:
        return {"points_per_match": 1.0, "goal_diff_per_match": 0.0}
    return {
        "points_per_match": float(values.get("points", 0.0)) / matches,
        "goal_diff_per_match": float(values.get("goal_diff", 0.0)) / matches,
    }


def _rest_days(last_played: str | None, kickoff: datetime) -> float:
    if not last_played:
        return 7.0
    previous = _parse_time(f"{last_played[:10]}T00:00:00+00:00")
    current = kickoff.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return float(max(0, min(21, (current - previous).days)))


def build_research_parity_features(
    repository: Repository,
    match: dict[str, Any],
    league_matches: LeagueMatcher,
    min_team_matches: int = 10,
) -> tuple[dict[str, float] | None, list[str]]:
    """Reproduce the historical scorer feature definitions using pre-kickoff rows only."""
    kickoff = _parse_time(str(match["kickoff_time"]))
    kickoff_date = kickoff.date().isoformat()
    home = canonical_team_name(str(match.get("home_team") or ""))
    away = canonical_team_name(str(match.get("away_team") or ""))
    raw_rows = repository.list_historical_matches(cutoff_time=match["kickoff_time"], limit=100_000)
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        played_at = _played_date(raw.get("played_at"))
        if not played_at or played_at >= kickoff_date:
            continue
        rows.append({
            **raw,
            "played_at": played_at,
            "home_team": canonical_team_name(str(raw.get("home_team") or "")),
            "away_team": canonical_team_name(str(raw.get("away_team") or "")),
            "home_goals": int(raw["home_goals"]),
            "away_goals": int(raw["away_goals"]),
        })
    rows.sort(key=lambda row: (row["played_at"], str(row.get("id") or "")))

    team_history: dict[str, list[dict[str, float]]] = {}
    family_stats: dict[str, dict[str, float]] = {}
    family_matches = family_draws = 0
    last_played: dict[str, str] = {}
    elo = EloModel()
    home_matches = away_matches = 0

    for row in rows:
        row_home = str(row["home_team"])
        row_away = str(row["away_team"])
        home_goals = int(row["home_goals"])
        away_goals = int(row["away_goals"])
        if home in {row_home, row_away}:
            home_matches += 1
        if away in {row_home, row_away}:
            away_matches += 1

        elo.update(row_home, row_away, home_goals, away_goals)
        team_history.setdefault(row_home, []).append({
            "points": _points(home_goals, away_goals),
            "goals_for": float(home_goals),
            "goals_against": float(away_goals),
        })
        team_history.setdefault(row_away, []).append({
            "points": _points(away_goals, home_goals),
            "goals_for": float(away_goals),
            "goals_against": float(home_goals),
        })
        last_played[row_home] = row["played_at"]
        last_played[row_away] = row["played_at"]

        if league_matches(row.get("league")):
            family_matches += 1
            family_draws += int(home_goals == away_goals)
            for team, goals_for, goals_against in (
                (row_home, home_goals, away_goals),
                (row_away, away_goals, home_goals),
            ):
                stats = family_stats.setdefault(team, {"matches": 0.0, "points": 0.0, "goal_diff": 0.0})
                stats["matches"] += 1.0
                stats["points"] += _points(goals_for, goals_against)
                stats["goal_diff"] += float(goals_for - goals_against)

    missing: list[str] = []
    if home_matches < min_team_matches:
        missing.append(f"home_history<{min_team_matches}:{home_matches}")
    if away_matches < min_team_matches:
        missing.append(f"away_history<{min_team_matches}:{away_matches}")
    if family_matches < 120:
        missing.append(f"league_prior_matches<120:{family_matches}")
    if missing and (home_matches < min_team_matches or away_matches < min_team_matches):
        return None, missing

    home_form = _recent_form(team_history.get(home, []))
    away_form = _recent_form(team_history.get(away, []))
    home_rate = _rate(family_stats.get(home))
    away_rate = _rate(family_stats.get(away))
    elo_delta = elo.rating(home) - elo.rating(away)
    lambda_home = max(0.45, 1.35 + elo_delta / 700.0)
    lambda_away = max(0.35, 1.05 - elo_delta / 900.0)
    home_rest = _rest_days(last_played.get(home), kickoff)
    away_rest = _rest_days(last_played.get(away), kickoff)
    return {
        "league_prior_matches": float(family_matches),
        "league_draw_rate": family_draws / family_matches if family_matches else 0.27,
        "league_prior_matches_scaled": float(family_matches) / 1000.0,
        "form_points_diff": home_form["points"] - away_form["points"],
        "form_goal_diff_delta": home_form["goal_diff"] - away_form["goal_diff"],
        "season_points_per_match_delta": home_rate["points_per_match"] - away_rate["points_per_match"],
        "season_goal_diff_per_match_delta": (
            home_rate["goal_diff_per_match"] - away_rate["goal_diff_per_match"]
        ),
        "rest_days_delta": home_rest - away_rest,
        "lambda_total": lambda_home + lambda_away,
        "lambda_diff": abs(lambda_home - lambda_away),
    }, missing
