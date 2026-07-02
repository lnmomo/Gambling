from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_OBJECTS = (
    "matches",
    "results",
    "official_odds_observations",
    "official_odds_closing_observations",
    "external_bookmaker_odds",
)


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _objects(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        row["name"]: row["type"]
        for row in connection.execute(
            "SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"
        )
    }


def _count(connection: sqlite3.Connection, name: str, objects: dict[str, str]) -> int | None:
    if name not in objects:
        return None
    return int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])


def _scalar(connection: sqlite3.Connection, sql: str, objects: dict[str, str],
            required: tuple[str, ...]) -> int | None:
    if any(name not in objects for name in required):
        return None
    return int(connection.execute(sql).fetchone()[0])


def _monthly_counts(connection: sqlite3.Connection, sql: str, objects: dict[str, str],
                    required: tuple[str, ...]) -> list[dict[str, Any]]:
    if any(name not in objects for name in required):
        return []
    return [dict(row) for row in connection.execute(sql).fetchall()]


def _decision(counts: dict[str, Any], missing: list[str], min_settled: int,
              min_months: int) -> tuple[str, list[str]]:
    if missing:
        return "BLOCKED_SCHEMA_MISSING", [
            "run database initialization/migrations before algorithm validation",
            "do not evaluate official-SP edge until official odds observation tables exist",
        ]
    if counts["results"] == 0:
        return "BLOCKED_NO_SETTLED_RESULTS", [
            "settle official matches into results after final scores are public",
            "keep live shadow bets pending until settlement instead of backfilling outcomes early",
        ]
    if counts["official_odds_observations"] == 0:
        return "BLOCKED_NO_OFFICIAL_OBSERVATIONS", [
            "start hourly official SP capture before kickoff",
            "archive immutable snapshots with observed_at and kickoff_time",
        ]
    if counts["official_opening_settled_matches"] < min_settled:
        return "BLOCKED_INSUFFICIENT_OFFICIAL_SETTLED_SAMPLE", [
            f"collect at least {min_settled} settled matches with pre-match official SP",
            "then run no-leakage walk-forward validation on official prices",
        ]
    if counts["official_settled_months"] < min_months:
        return "BLOCKED_INSUFFICIENT_MONTH_COVERAGE", [
            f"collect settled official-SP samples across at least {min_months} months",
            "avoid promoting a strategy from one lucky month",
        ]
    if counts["external_settled_matches"] == 0:
        return "OFFICIAL_SP_READY_EXTERNAL_MARKET_BLOCKED", [
            "official-SP validation can run, but external market divergence cannot",
            "capture external bookmaker odds for the same matches before kickoff",
        ]
    return "READY_FOR_OFFICIAL_MARKET_EDGE_RESEARCH", [
        "run official-vs-external divergence experiments with walk-forward gates",
        "require candidate selection to use only prior settled months",
    ]


def diagnose_official_market_data(database_path: Path | str,
                                  min_settled: int = 200,
                                  min_months: int = 6) -> dict[str, Any]:
    path = Path(database_path)
    with _connect(path) as connection:
        objects = _objects(connection)
        missing = [name for name in REQUIRED_OBJECTS if name not in objects]
        counts: dict[str, Any] = {
            name: _count(connection, name, objects)
            for name in REQUIRED_OBJECTS
        }
        counts["official_opening_settled_matches"] = _scalar(
            connection,
            """SELECT COUNT(DISTINCT r.match_id)
               FROM results r
               JOIN official_odds_observations o ON o.match_id=r.match_id
               WHERE o.is_pre_match=1""",
            objects,
            ("results", "official_odds_observations"),
        )
        counts["official_closing_settled_matches"] = _scalar(
            connection,
            """SELECT COUNT(DISTINCT r.match_id)
               FROM results r
               JOIN official_odds_closing_observations o ON o.match_id=r.match_id""",
            objects,
            ("results", "official_odds_closing_observations"),
        )
        counts["external_settled_matches"] = _scalar(
            connection,
            """SELECT COUNT(DISTINCT r.match_id)
               FROM results r
               JOIN external_bookmaker_odds e ON e.match_id=r.match_id""",
            objects,
            ("results", "external_bookmaker_odds"),
        )
        official_monthly = _monthly_counts(
            connection,
            """SELECT substr(m.kickoff_time,1,7) month,COUNT(DISTINCT r.match_id) settled_matches
               FROM results r
               JOIN matches m ON m.id=r.match_id
               JOIN official_odds_observations o ON o.match_id=r.match_id AND o.is_pre_match=1
               GROUP BY substr(m.kickoff_time,1,7)
               ORDER BY month""",
            objects,
            ("results", "matches", "official_odds_observations"),
        )
        external_monthly = _monthly_counts(
            connection,
            """SELECT substr(m.kickoff_time,1,7) month,COUNT(DISTINCT r.match_id) settled_matches
               FROM results r
               JOIN matches m ON m.id=r.match_id
               JOIN external_bookmaker_odds e ON e.match_id=r.match_id
               GROUP BY substr(m.kickoff_time,1,7)
               ORDER BY month""",
            objects,
            ("results", "matches", "external_bookmaker_odds"),
        )

    counts["official_settled_months"] = len(official_monthly)
    decision, next_actions = _decision(counts, missing, min_settled, min_months)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_path": str(path),
        "required_objects": [{"name": name, "status": "present" if name not in missing else "missing"}
                             for name in REQUIRED_OBJECTS],
        "counts": counts,
        "monthly": {
            "official_sp_settled": official_monthly,
            "external_market_settled": external_monthly,
        },
        "thresholds": {"min_settled": min_settled, "min_months": min_months},
        "decision": decision,
        "algorithm_blocked": decision.startswith("BLOCKED"),
        "next_actions": next_actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose whether real official/external market data can support edge research.")
    parser.add_argument("--database", default="data/football_agents.db")
    parser.add_argument("--min-settled", type=int, default=200)
    parser.add_argument("--min-months", type=int, default=6)
    parser.add_argument("--output-dir", type=Path, default=Path("reports") / "official_market_data_sufficiency")
    args = parser.parse_args()

    report = diagnose_official_market_data(args.database, args.min_settled, args.min_months)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
