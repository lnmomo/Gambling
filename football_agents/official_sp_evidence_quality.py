from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings
from .db import Database, db


QUALITY_LOOKBACK_DAYS = 30
MIN_OPERATIONAL_MATCHES = 10


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


def _sample_check(
    check_id: str,
    numerator: int,
    denominator: int,
    minimum_samples: int,
    minimum_ratio: float,
    severity: str,
    unit: str,
    impact: str,
    remediation: str,
) -> dict[str, Any]:
    value = _ratio(numerator, denominator)
    if denominator < minimum_samples:
        return {
            "id": check_id,
            "status": "PENDING",
            "severity": "NONE",
            "value": round(value, 4),
            "threshold": f">={minimum_ratio:.2f} after >={minimum_samples} {unit}",
            "evidence": f"{numerator}/{denominator} {unit}; waiting for {minimum_samples - denominator} more.",
            "impact": impact,
            "remediation": remediation,
        }
    return _check(
        check_id,
        value >= minimum_ratio,
        severity,
        round(value, 4),
        f">={minimum_ratio:.2f} across >={minimum_samples} {unit}",
        f"{numerator}/{denominator} {unit} satisfy the requirement.",
        impact,
        remediation,
    )


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
        availability_start_row = connection.execute(
            "SELECT MIN(observed_at) started_at FROM official_market_availability_observations"
        ).fetchone()
        availability_start = availability_start_row["started_at"] if availability_start_row else None
        rolling_start = current.astimezone(timezone.utc) - timedelta(days=QUALITY_LOOKBACK_DAYS)
        if availability_start:
            parsed_start = datetime.fromisoformat(str(availability_start).replace("Z", "+00:00"))
            if parsed_start.tzinfo is None:
                parsed_start = parsed_start.replace(tzinfo=timezone.utc)
            measurement_start = max(rolling_start, parsed_start.astimezone(timezone.utc))
        else:
            measurement_start = rolling_start
        measurement_start_text = measurement_start.isoformat()
        operational = dict(connection.execute("""WITH cards AS (
                SELECT * FROM official_market_availability_observations
                WHERE unixepoch(observed_at)>=unixepoch(?) AND unixepoch(observed_at)<=unixepoch(?)
                  AND unixepoch(observed_at)<=unixepoch(kickoff_time)
            ), offered AS (
                SELECT DISTINCT match_id FROM cards WHERE raw_sale_status='已开售'
            ), captured AS (
                SELECT DISTINCT cards.match_id FROM cards
                JOIN official_odds_observations odds
                  ON odds.match_id=cards.match_id AND odds.observed_at=cards.observed_at
                WHERE cards.raw_sale_status='已开售' AND cards.has_valid_three_way_sp=1
                  AND odds.is_pre_match=1
            ), closing_eligible AS (
                SELECT offered.match_id FROM offered JOIN matches m ON m.id=offered.match_id
                WHERE unixepoch(m.kickoff_time)<=unixepoch(?)
            ), settlement_eligible AS (
                SELECT offered.match_id FROM offered JOIN matches m ON m.id=offered.match_id
                WHERE unixepoch(m.kickoff_time)<=unixepoch(?)-14400
                  AND m.status NOT IN ('cancelled','postponed')
            )
            SELECT
                (SELECT COUNT(*) FROM cards) availability_observations,
                (SELECT COUNT(*) FROM offered) offered_matches,
                (SELECT COUNT(*) FROM captured) captured_offered_matches,
                (SELECT COUNT(*) FROM closing_eligible) closing_eligible_matches,
                (SELECT COUNT(*) FROM closing_eligible eligible WHERE EXISTS(
                    SELECT 1 FROM official_odds_observations odds
                    WHERE odds.match_id=eligible.match_id AND odds.is_pre_match=1
                      AND odds.minutes_to_kickoff BETWEEN 0 AND 60
                      AND unixepoch(odds.observed_at)>=unixepoch(?))) closing_within_1h,
                (SELECT COUNT(*) FROM settlement_eligible) settlement_eligible_matches,
                (SELECT COUNT(*) FROM settlement_eligible eligible WHERE EXISTS(
                    SELECT 1 FROM results r WHERE r.match_id=eligible.match_id)) settled_matches
            """, (
                measurement_start_text, now_text, now_text, now_text, measurement_start_text,
            )).fetchone())
        historical_cohort = dict(connection.execute("""WITH boundary AS (
                SELECT MIN(observed_at) started_at FROM official_odds_observations
            ), eligible AS (
                SELECT m.id,m.first_seen_at,m.kickoff_time FROM matches m,boundary b
                WHERE m.official_match_id LIKE 'sporttery-%'
                  AND b.started_at IS NOT NULL
                  AND unixepoch(m.kickoff_time)>=unixepoch(b.started_at)
                  AND unixepoch(m.kickoff_time)<=unixepoch(?)
                  AND m.status NOT IN ('cancelled','postponed')
            )
            SELECT COUNT(*) kicked_matches,
                SUM(unixepoch(first_seen_at)<=unixepoch(kickoff_time)) discovered_pre_match,
                SUM(unixepoch(first_seen_at)<=unixepoch(kickoff_time) AND EXISTS(
                    SELECT 1 FROM official_odds_observations o
                    WHERE o.match_id=eligible.id AND o.is_pre_match=1)) discovered_pre_with_sp
            FROM eligible""", (now_text,)).fetchone())
        historical_closing = dict(connection.execute("""SELECT COUNT(*) closing_matches,
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
        availability_reasons = [dict(row) for row in connection.execute("""SELECT
            raw_sale_status,COALESCE(missing_reason,'valid_three_way_sp') reason,
            COUNT(*) observations,COUNT(DISTINCT match_id) matches
            FROM official_market_availability_observations
            WHERE unixepoch(observed_at)>=unixepoch(?)
            GROUP BY raw_sale_status,COALESCE(missing_reason,'valid_three_way_sp')
            ORDER BY observations DESC""", (measurement_start_text,)).fetchall()]

    last_success_at = str(latest_fetch["fetched_at"]) if latest_fetch else None
    last_success = None
    if last_success_at:
        parsed = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
        last_success = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    freshness_hours = (
        max(0.0, (current.astimezone(timezone.utc) - last_success.astimezone(timezone.utc)).total_seconds() / 3600)
        if last_success else None
    )
    offered_matches = int(operational.get("offered_matches") or 0)
    captured_offered = int(operational.get("captured_offered_matches") or 0)
    closing_eligible = int(operational.get("closing_eligible_matches") or 0)
    closing_within_1h = int(operational.get("closing_within_1h") or 0)
    settlement_eligible = int(operational.get("settlement_eligible_matches") or 0)
    settled_matches = int(operational.get("settled_matches") or 0)
    pre_match_coverage = _ratio(captured_offered, offered_matches)
    settlement_coverage = _ratio(settled_matches, settlement_eligible)
    closing_1h_coverage = _ratio(closing_within_1h, closing_eligible)

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
        _sample_check(
            "pre_match_sp_coverage",
            captured_offered,
            offered_matches,
            MIN_OPERATIONAL_MATCHES,
            0.95,
            "HIGH",
            "offered matches",
            "Missing prices bias strategy selection and reduce the auditable sample.",
            "Investigate sold cards with invalid or missing three-way SP before using ROI estimates.",
        ),
        _sample_check(
            "closing_sp_within_1h",
            closing_within_1h,
            closing_eligible,
            MIN_OPERATIONAL_MATCHES,
            0.80,
            "HIGH",
            "offered kicked-off matches",
            "Weak closing coverage makes CLV incomparable and can hide stale executable prices.",
            "Keep 15-minute capture running through kickoff for every offered match.",
        ),
        _sample_check(
            "settlement_coverage",
            settled_matches,
            settlement_eligible,
            MIN_OPERATIONAL_MATCHES,
            0.95,
            "HIGH",
            "offered matches at least four hours after kickoff",
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
    pending = [item for item in checks if item["status"] == "PENDING"]
    critical = [item for item in failed if item["severity"] == "CRITICAL"]
    decision = (
        "EVIDENCE_CRITICAL" if critical else "EVIDENCE_DEGRADED" if failed
        else "EVIDENCE_COLLECTING" if pending else "EVIDENCE_READY"
    )
    warnings = [f"{item['id']}: {item['evidence']}" for item in checks if item["status"] != "PASS"]
    return {
        "method": "official SP evidence-chain data quality",
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "decision": decision,
        "research_usable": decision == "EVIDENCE_READY",
        "dataset_grain": (
            "one immutable market-availability card and zero-or-one immutable official three-way SP "
            "observation per match and fetch timestamp"
        ),
        "summary": {
            "observations": int(totals.get("observations") or 0),
            "observed_matches": int(totals.get("observed_matches") or 0),
            "pre_match_matches": int(totals.get("pre_match_matches") or 0),
            "pre_match_observations": int(totals.get("pre_match_observations") or 0),
            "first_observed_at": totals.get("first_observed_at"),
            "last_observed_at": totals.get("last_observed_at"),
            "last_successful_fetch_at": last_success_at,
            "freshness_hours": round(freshness_hours, 2) if freshness_hours is not None else None,
            "measurement_start": measurement_start_text,
            "availability_observations": int(operational.get("availability_observations") or 0),
            "offered_matches": offered_matches,
            "captured_offered_matches": captured_offered,
            "closing_eligible_matches": closing_eligible,
            "settlement_eligible_matches": settlement_eligible,
            "pre_match_sp_coverage": round(pre_match_coverage, 4),
            "closing_1h_coverage": round(closing_1h_coverage, 4),
            "settlement_coverage": round(settlement_coverage, 4),
            "average_observations_per_match": float(depth.get("average_observations") or 0),
        },
        "checks": checks,
        "failed_checks": len(failed),
        "pending_checks": len(pending),
        "critical_checks": len(critical),
        "warnings": warnings,
        "capture_stages": stages,
        "availability_reasons": availability_reasons,
        "league_coverage": leagues,
        "historical_baseline": {
            "kicked_matches": int(historical_cohort.get("kicked_matches") or 0),
            "discovered_pre_match": int(historical_cohort.get("discovered_pre_match") or 0),
            "discovered_pre_with_sp": int(historical_cohort.get("discovered_pre_with_sp") or 0),
            "closing_matches": int(historical_closing.get("closing_matches") or 0),
            "closing_within_1h": int(historical_closing.get("within_1h") or 0),
        },
        "guardrail": "Only EVIDENCE_READY permits official-SP promotion and capital allocation.",
    }
