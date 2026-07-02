from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .db import Database, db
from .market_bias_shadow_strategy import expand_market_bias_strategy_id, find_market_bias_shadow_candidates, is_i2_league


@dataclass(frozen=True)
class MarketBiasOfficialValidation:
    strategy_id: str
    created_at: str
    sample_count: int
    candidate_count: int
    settled_candidate_count: int
    winning_count: int
    total_staked: float
    profit: float
    roi_pct: float
    hit_rate: float | None
    max_drawdown: float
    positive_months: int
    negative_months: int
    monthly: list[dict[str, Any]]
    selections: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _actual_outcome(row: dict[str, Any]) -> str:
    return str(row["outcome"]).upper()


def _profit(selected_outcome: str, selected_sp: float, actual: str) -> float:
    return selected_sp - 1.0 if selected_outcome == actual else -1.0


def _max_drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def _month(kickoff_time: str) -> str:
    return kickoff_time[:7]


def _load_opening_official_sp_samples(database: Database, limit: int) -> list[dict[str, Any]]:
    with database.connect() as c:
        rows = c.execute("""SELECT m.id match_id,m.official_match_id,m.league,m.home_team,m.away_team,m.kickoff_time,
            opening.observed_at,opening.home_sp,opening.draw_sp,opening.away_sp,
            r.outcome,r.home_score,r.away_score,r.settled_at
            FROM results r
            JOIN matches m ON m.id=r.match_id
            JOIN official_odds_observations opening ON opening.id=(
                SELECT first.id FROM official_odds_observations first
                WHERE first.match_id=m.id AND first.is_pre_match=1
                ORDER BY first.observed_at ASC LIMIT 1)
            ORDER BY m.kickoff_time ASC
            LIMIT ?""", (max(1, min(limit, 100_000)),)).fetchall()
    return [dict(row) for row in rows]


def _load_opening_official_sp_funnel_rows(database: Database, limit: int) -> list[dict[str, Any]]:
    with database.connect() as c:
        rows = c.execute("""SELECT m.id match_id,m.official_match_id,m.league,m.home_team,m.away_team,
            m.kickoff_time,m.status,
            opening.observed_at,opening.home_sp,opening.draw_sp,opening.away_sp,
            r.outcome,r.home_score,r.away_score,r.settled_at
            FROM matches m
            JOIN official_odds_observations opening ON opening.id=(
                SELECT first.id FROM official_odds_observations first
                WHERE first.match_id=m.id AND first.is_pre_match=1
                ORDER BY first.observed_at ASC LIMIT 1)
            LEFT JOIN results r ON r.match_id=m.id
            ORDER BY m.kickoff_time ASC
            LIMIT ?""", (max(1, min(limit, 100_000)),)).fetchall()
    return [dict(row) for row in rows]


def diagnose_market_bias_official_sp_funnel(database: Database = db, limit: int = 100_000,
                                            draw_low: float = 2.8,
                                            draw_high: float = 3.5) -> dict[str, Any]:
    rows = _load_opening_official_sp_funnel_rows(database, limit)
    valid_three_way = [
        row for row in rows
        if all(float(row.get(key) or 0) > 1 for key in ("home_sp", "draw_sp", "away_sp"))
    ]
    i2_rows = [row for row in valid_three_way if is_i2_league(row.get("league"))]
    band_rows = [
        row for row in i2_rows
        if draw_low <= float(row.get("draw_sp") or 0) < draw_high
    ]
    settled_band_rows = [row for row in band_rows if row.get("outcome")]
    league_counts: dict[str, int] = {}
    for row in valid_three_way:
        league = str(row.get("league") or "UNKNOWN")
        league_counts[league] = league_counts.get(league, 0) + 1
    band_by_status: dict[str, int] = {}
    for row in band_rows:
        status = str(row.get("status") or "UNKNOWN")
        band_by_status[status] = band_by_status.get(status, 0) + 1
    return {
        "method": "market-bias official SP funnel diagnostics",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "draw_band": {"low": draw_low, "high": draw_high, "label": f"[{draw_low:.2f},{draw_high:.2f})"},
        "opening_pre_match_samples": len(rows),
        "valid_three_way_samples": len(valid_three_way),
        "settled_opening_samples": sum(1 for row in valid_three_way if row.get("outcome")),
        "i2_opening_samples": len(i2_rows),
        "i2_settled_samples": sum(1 for row in i2_rows if row.get("outcome")),
        "i2_draw_band_samples": len(band_rows),
        "i2_draw_band_settled_samples": len(settled_band_rows),
        "i2_draw_band_unsettled_samples": len(band_rows) - len(settled_band_rows),
        "top_leagues": [
            {"league": league, "samples": count}
            for league, count in sorted(league_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        ],
        "i2_draw_band_by_status": [
            {"status": status, "samples": count}
            for status, count in sorted(band_by_status.items(), key=lambda item: item[1], reverse=True)
        ],
        "i2_draw_band_examples": [
            {
                "official_match_id": row.get("official_match_id"),
                "league": row.get("league"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "kickoff_time": row.get("kickoff_time"),
                "status": row.get("status"),
                "observed_at": row.get("observed_at"),
                "draw_sp": row.get("draw_sp"),
                "settled": bool(row.get("outcome")),
                "outcome": row.get("outcome"),
            }
            for row in band_rows[:50]
        ],
        "blocker": (
            "no opening official SP observations"
            if not rows
            else "no I2 opening official SP samples"
            if not i2_rows
            else "no I2 draw odds inside target band"
            if not band_rows
            else "I2 target-band samples exist but are not settled yet"
            if not settled_band_rows
            else "settled target-band samples exist"
        ),
    }


def validate_market_bias_on_official_sp(database: Database = db, limit: int = 100_000,
                                        strategy_id: str | None = None) -> MarketBiasOfficialValidation:
    samples = _load_opening_official_sp_samples(database, limit)
    allowed_strategy_ids = expand_market_bias_strategy_id(strategy_id)
    selections: list[dict[str, Any]] = []
    for row in samples:
        official_sp = {"home": row["home_sp"], "draw": row["draw_sp"], "away": row["away_sp"]}
        candidates = find_market_bias_shadow_candidates(row, official_sp)
        if allowed_strategy_ids is not None:
            candidates = [candidate for candidate in candidates if candidate.strategy_id in allowed_strategy_ids]
        for candidate in candidates:
            actual = _actual_outcome(row)
            profit = _profit(candidate.outcome, candidate.selected_sp, actual)
            selections.append({
                "official_match_id": row["official_match_id"],
                "kickoff_time": row["kickoff_time"],
                "observed_at": row["observed_at"],
                "month": _month(row["kickoff_time"]),
                "league": row["league"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "selected_outcome": candidate.outcome,
                "selected_sp": candidate.selected_sp,
                "selected_market_probability": candidate.selected_market_probability,
                "actual_outcome": actual,
                "won": candidate.outcome == actual,
                "profit": round(profit, 2),
                "strategy_id": candidate.strategy_id,
            })
    monthly: list[dict[str, Any]] = []
    for month in sorted({row["month"] for row in selections}):
        rows = [row for row in selections if row["month"] == month]
        profit = round(sum(float(row["profit"]) for row in rows), 2)
        monthly.append({
            "month": month,
            "bets": len(rows),
            "wins": sum(1 for row in rows if row["won"]),
            "staked": float(len(rows)),
            "profit": profit,
            "roi_pct": round(profit / len(rows) * 100, 2) if rows else 0.0,
        })
    profits = [float(row["profit"]) for row in selections]
    wins = sum(1 for row in selections if row["won"])
    total_staked = float(len(selections))
    total_profit = round(sum(profits), 2)
    warnings: list[str] = []
    if len(selections) < 50:
        warnings.append("official SP settled sample is small; keep rule in shadow validation")
    if samples and not selections:
        scope = strategy_id or "any frozen market-bias rule"
        warnings.append(f"no official SP samples matched {scope}")
    if not samples:
        warnings.append("no settled official SP samples found")
    return MarketBiasOfficialValidation(
        strategy_id=strategy_id or "ALL_MARKET_BIAS_SHADOW_CANDIDATES",
        created_at=datetime.now(timezone.utc).isoformat(),
        sample_count=len(samples),
        candidate_count=len(selections),
        settled_candidate_count=len(selections),
        winning_count=wins,
        total_staked=total_staked,
        profit=total_profit,
        roi_pct=round(total_profit / total_staked * 100, 2) if total_staked else 0.0,
        hit_rate=round(wins / len(selections), 4) if selections else None,
        max_drawdown=_max_drawdown(profits),
        positive_months=sum(1 for row in monthly if row["profit"] > 0),
        negative_months=sum(1 for row in monthly if row["profit"] < 0),
        monthly=monthly,
        selections=selections,
        warnings=warnings,
    )
