from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import settings
from .db import Database, db


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _check(
    check_id: str,
    passed: bool,
    severity: str,
    value: Any,
    threshold: str,
    evidence: str,
    impact: str,
    remediation: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "PASS" if passed else "FAIL",
        "severity": "NONE" if passed else severity,
        "value": value,
        "threshold": threshold,
        "evidence": evidence,
        "impact": impact,
        "remediation": remediation,
    }


def build_official_sp_evidence_quality(
    database: Database = db,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess whether official SP observations can support prospective ROI and CLV claims."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    now_text = current.astimezone(timezone.utc).isoformat()
    max_freshness_hours = max(0.5, settings.official_sp_refresh_minutes * 2 / 60)

    with database.connect() as connection:
        totals = dict(connection.execute("""SELECT COUNT(*) observations,
            COUNT(DISTINCT match_id) observed_matches,
            COUNT(DISTINCT CASE WHEN is_pre_match=1 THEN match_id END) pre_match_matches,
            SUM(CASE WHEN is_pre_match=1 THEN 1 ELSE 0 END) pre_match_observations,
            MIN(observed_at) first_observed_at,MAX(observed_at) last_observed_at
            FROM official_odds_observations""").fetchone())
        latest_fetch = connection.execute("""SELECT fetched_at,record_count FROM official_fetch_logs
            WHERE success=1 ORDER BY fetched_at DESC LIMIT 1""").fetchone()
        cohort = dict(connection.execute("""WITH boundary AS (
                SELECT MIN(observed_at) started_at FROM official_odds_observations
            ), eligible AS (
                SELECT m.id,m.status FROM matches m,boundary b
                WHERE m.official_match_id LIKE 'sporttery-%'
                  AND b.started_at IS NOT NULL
                  AND unixepoch(m.kickoff_time)>=unixepoch(b.started_at)
                  AND unixepoch(m.kickoff_time)<=unixepoch(?)
                  AND m.status NOT IN ('cancelled','postponed')
            )
            SELECT COUNT(DISTINCT eligible.id) eligible_matches,
                COUNT(DISTINCT CASE WHEN o.match_id IS NOT NULL THEN eligible.id END) with_pre_match_sp,
                COUNT(DISTINCT CASE WHEN eligible.status='finished' THEN eligible.id END) finished_matches,
                COUNT(DISTINCT CASE WHEN eligible.status='finished' AND o.match_id IS NOT NULL THEN eligible.id END) finished_with_sp,
                COUNT(DISTINCT CASE WHEN eligible.status='finished' AND o.match_id IS NOT NULL AND r.match_id IS NOT NULL THEN eligible.id END) settled_with_sp
            FROM eligible
            LEFT JOIN official_odds_observations o ON o.match_id=eligible.id AND o.is_pre_match=1
            LEFT JOIN results r ON r.match_id=eligible.id""", (now_text,)).fetchone())
        closing = dict(connection.execute("""SELECT COUNT(*) closing_matches,
            SUM(CASE WHEN minutes_to_kickoff<=60 THEN 1 ELSE 0 END) within_1h,
            SUM(CASE WHEN minutes_to_kickoff<=360 THEN 1 ELSE 0 END) within_6h,
            ROUND(AVG(minutes_to_kickoff),1) average_minutes_to_kickoff
            FROM official_odds_closing_observations
            WHERE unixepoch(kickoff_time)<=unixepoch(?)""", (now_text,)).fetchone())
        validity = dict(connection.execute("""SELECT
            SUM(CASE WHEN home_sp<=1 OR draw_sp<=1 OR away_sp<=1 THEN 1 ELSE 0 END) invalid_prices,
            SUM(CASE WHEN is_pre_match=1 AND unixepoch(observed_at)>unixepoch(kickoff_time) THEN 1
                     WHEN is_pre_match=0 AND unixepoch(observed_at)<=unixepoch(kickoff_time) THEN 1 ELSE 0 END) temporal_conflicts,
            COUNT(*)-COUNT(DISTINCT match_id||'|'||observed_at) duplicate_grain
            FROM official_odds_observations""").fetchone())
        depth = dict(connection.execute("""SELECT COUNT(*) matches,
            ROUND(AVG(observation_count),2) average_observations,
            SUM(CASE WHEN observation_count>=2 THEN 1 ELSE 0 END) matches_ge_2,
            SUM(CASE WHEN observation_count>=6 THEN 1 ELSE 0 END) matches_ge_6
            FROM (SELECT match_id,COUNT(*) observation_count
                  FROM official_odds_observations WHERE is_pre_match=1 GROUP BY match_id)""").fetchone())
        stages = [dict(row) for row in connection.execute("""SELECT capture_stage,
            COUNT(*) observations,COUNT(DISTINCT match_id) matches
            FROM official_odds_observations GROUP BY capture_stage ORDER BY observations DESC""").fetchall()]
        leagues = [dict(row) for row in connection.execute("""SELECT m.league,
            COUNT(DISTINCT m.id) matches,COUNT(o.id) observations,
            COUNT(DISTINCT CASE WHEN o.capture_stage='T_MINUS_1H' THEN m.id END) within_1h,
            COUNT(DISTINCT CASE WHEN r.match_id IS NOT NULL THEN m.id END) settled
            FROM matches m
            JOIN official_odds_observations o ON o.match_id=m.id AND o.is_pre_match=1
            LEFT JOIN results r ON r.match_id=m.id
            GROUP BY m.league ORDER BY observations DESC,matches DESC""").fetchall()]

    last_success_at = str(latest_fetch["fetched_at"]) if latest_fetch else None
    last_success = None
    if last_success_at:
        parsed = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
        last_success = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    freshness_hours = (
        max(0.0, (current.astimezone(timezone.utc) - last_success.astimezone(timezone.utc)).total_seconds() / 3600)
        if last_success else None
    )
    eligible = int(cohort.get("eligible_matches") or 0)
    with_sp = int(cohort.get("with_pre_match_sp") or 0)
    finished_with_sp = int(cohort.get("finished_with_sp") or 0)
    settled_with_sp = int(cohort.get("settled_with_sp") or 0)
    closing_matches = int(closing.get("closing_matches") or 0)
    within_1h = int(closing.get("within_1h") or 0)
    pre_match_coverage = _ratio(with_sp, eligible)
    settlement_coverage = _ratio(settled_with_sp, finished_with_sp)
    closing_1h_coverage = _ratio(within_1h, closing_matches)

    checks = [
        _check(
            "collector_freshness",
            freshness_hours is not None and freshness_hours <= max_freshness_hours,
            "CRITICAL",
            round(freshness_hours, 2) if freshness_hours is not None else None,
            f"<={max_freshness_hours:.1f} hours",
            f"Latest successful fetch: {last_success_at or 'none'}.",
            "A stopped collector creates permanent gaps in opening and closing prices.",
            "Keep the API service running continuously and alert after two missed capture cycles.",
        ),
        _check(
            "pre_match_sp_coverage",
            eligible > 0 and pre_match_coverage >= 0.90,
            "HIGH",
            round(pre_match_coverage, 4),
            ">=0.90 of eligible kicked-off matches",
            f"{with_sp}/{eligible} collector-era matches have a pre-match three-way SP.",
            "Missing prices bias strategy selection and reduce the auditable sample.",
            "Investigate omitted cards and parser failures by league before using ROI estimates.",
        ),
        _check(
            "closing_sp_within_1h",
            closing_matches > 0 and closing_1h_coverage >= 0.80,
            "HIGH",
            round(closing_1h_coverage, 4),
            ">=0.80 of closing observations within 60 minutes",
            f"{within_1h}/{closing_matches} closing observations are within one hour of kickoff.",
            "Weak closing coverage makes CLV incomparable and can hide stale executable prices.",
            "Run official SP capture every 15 minutes for matches starting within six hours.",
        ),
        _check(
            "settlement_coverage",
            finished_with_sp > 0 and settlement_coverage >= 0.95,
            "HIGH",
            round(settlement_coverage, 4),
            ">=0.95 of observed finished matches",
            f"{settled_with_sp}/{finished_with_sp} finished matches with SP have a result.",
            "Missing outcomes distort ROI, hit rate, drawdown, and promotion decisions.",
            "Backfill missing final scores and alert on finished matches without results.",
        ),
        _check(
            "odds_validity",
            int(validity.get("invalid_prices") or 0) == 0,
            "CRITICAL",
            int(validity.get("invalid_prices") or 0),
            "0 invalid three-way prices",
            "All stored home/draw/away prices must be greater than 1.",
            "Invalid prices corrupt implied probabilities and EV.",
            "Reject the fetch and retain the previous valid snapshot.",
        ),
        _check(
            "temporal_integrity",
            int(validity.get("temporal_conflicts") or 0) == 0,
            "CRITICAL",
            int(validity.get("temporal_conflicts") or 0),
            "0 pre/post-match timestamp conflicts",
            "is_pre_match must agree with observed_at relative to kickoff_time.",
            "Timestamp conflicts create direct future leakage.",
            "Quarantine conflicting observations and verify timezone normalization.",
        ),
        _check(
            "observation_grain_uniqueness",
            int(validity.get("duplicate_grain") or 0) == 0,
            "CRITICAL",
            int(validity.get("duplicate_grain") or 0),
            "0 duplicate match_id + observed_at rows",
            "Each fetch time is one immutable observation per match.",
            "Duplicate grain overweights prices in downstream analyses.",
            "Keep the database uniqueness constraint and reject duplicate inserts.",
        ),
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    critical = [item for item in failed if item["severity"] == "CRITICAL"]
    decision = "EVIDENCE_READY" if not failed else "EVIDENCE_CRITICAL" if critical else "EVIDENCE_DEGRADED"
    warnings = [f"{item['id']}: {item['evidence']}" for item in failed]
    return {
        "method": "official SP evidence-chain data quality",
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "decision": decision,
        "research_usable": decision == "EVIDENCE_READY",
        "dataset_grain": "one immutable official three-way SP observation per match and fetch timestamp",
        "summary": {
            "observations": int(totals.get("observations") or 0),
            "observed_matches": int(totals.get("observed_matches") or 0),
            "pre_match_matches": int(totals.get("pre_match_matches") or 0),
            "pre_match_observations": int(totals.get("pre_match_observations") or 0),
            "first_observed_at": totals.get("first_observed_at"),
            "last_observed_at": totals.get("last_observed_at"),
            "last_successful_fetch_at": last_success_at,
            "freshness_hours": round(freshness_hours, 2) if freshness_hours is not None else None,
            "eligible_collector_era_matches": eligible,
            "pre_match_sp_coverage": round(pre_match_coverage, 4),
            "closing_1h_coverage": round(closing_1h_coverage, 4),
            "settlement_coverage": round(settlement_coverage, 4),
            "average_observations_per_match": float(depth.get("average_observations") or 0),
        },
        "checks": checks,
        "failed_checks": len(failed),
        "critical_checks": len(critical),
        "warnings": warnings,
        "capture_stages": stages,
        "league_coverage": leagues,
        "guardrail": "EVIDENCE_DEGRADED or EVIDENCE_CRITICAL blocks official-SP promotion and capital allocation.",
    }
