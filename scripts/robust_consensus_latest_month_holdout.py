"""Two-stage, no-lookahead latest-complete-month robust-consensus replay.

``prepare`` selects one pre-registered strategy using only the six months before
the latest complete data month. ``evaluate`` verifies the sealed manifest before
opening that month. Opening prices have no provider timestamps, so this remains a
research bridge and can never promote a live strategy by itself.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from football_agents.named_book_gap_research import _robust_consensus
from scripts.portfolio_algorithm_optimization import ALL_SEASONS, DATA_BASE, PROJECT_ROOT


OUTCOMES = ("home", "draw", "away")
FTR = {"H": "home", "D": "draw", "A": "away"}
BOOK_PREFIXES = (
    "B365", "BFD", "BMGM", "BV", "BW", "CL", "IW", "LB", "PS", "BFE",
    "BF", "VC", "WH", "1XB",
)


@dataclass(frozen=True)
class Strategy:
    name: str
    minimum_price_ratio: float
    minimum_conservative_ev: float
    dispersion_multiplier: float
    minimum_probability: float
    maximum_odds: float
    minimum_reference_bookmakers: int = 4
    uncertainty_floor: float = 0.005
    slippage_rate: float = 0.02
    exchange_commission_rate: float = 0.05
    daily_budget: float = 100.0
    maximum_single_stake: float = 10.0
    kelly_fraction: float = 0.25
    exchange_bookmaker_keys: tuple[str, ...] = ("BFE",)
    maximum_price_ratio: float | None = None
    execution_price_rank: int = 1
    maximum_execution_quote_advantage_ratio: float | None = None


STRATEGIES = (
    Strategy("RC-A-balanced", 1.01, 0.01, 1.0, 0.20, 6.0),
    Strategy("RC-B-v3-default", 1.02, 0.02, 1.5, 0.20, 6.0),
    Strategy("RC-C-no-longshots", 1.01, 0.01, 1.0, 0.25, 4.0),
    Strategy("RC-D-probability30", 1.01, 0.01, 1.0, 0.30, 4.0),
    Strategy("RC-E-strict-edge", 1.03, 0.03, 1.5, 0.25, 4.0),
)


@dataclass(frozen=True)
class HistoricalMatch:
    match_date: date
    league: str
    home_team: str
    away_team: str
    actual_outcome: str
    books: tuple[dict[str, Any], ...]
    source_file: str
    source_row: int
    closing_books: tuple[dict[str, Any], ...] = ()


def _parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(value)


def _float(value: Any) -> float:
    try:
        parsed = float(str(value).strip())
        return parsed if math.isfinite(parsed) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _book(row: dict[str, Any], prefix: str, closing: bool = False) -> dict[str, Any] | None:
    suffix = {"home": "H", "draw": "D", "away": "A"}
    marker = "C" if closing else ""
    values = {outcome: _float(row.get(f"{prefix}{marker}{ending}")) for outcome, ending in suffix.items()}
    if not all(math.isfinite(value) and value > 1.0 for value in values.values()):
        return None
    return {"bookmaker_key": prefix, **{f"{outcome}_odds": value for outcome, value in values.items()}}


def load_matches(data_base: Path = DATA_BASE, seasons: tuple[str, ...] = tuple(ALL_SEASONS)) -> list[HistoricalMatch]:
    matches: list[HistoricalMatch] = []
    for season in seasons:
        for path in sorted((data_base / season).glob("*.csv")):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row_number, row in enumerate(csv.DictReader(handle), start=2):
                    outcome = FTR.get(str(row.get("FTR") or "").strip())
                    if not outcome:
                        continue
                    try:
                        match_date = _parse_date(str(row.get("Date") or ""))
                    except ValueError:
                        continue
                    books = tuple(value for prefix in BOOK_PREFIXES if (value := _book(row, prefix)) is not None)
                    closing_books = tuple(
                        value for prefix in BOOK_PREFIXES
                        if (value := _book(row, prefix, closing=True)) is not None
                    )
                    if len(books) < 5:
                        continue
                    matches.append(HistoricalMatch(
                        match_date, str(row.get("Div") or path.stem), str(row.get("HomeTeam") or ""),
                        str(row.get("AwayTeam") or ""), outcome, books,
                        str(path.relative_to(PROJECT_ROOT)), row_number, closing_books,
                    ))
    matches.sort(key=lambda item: (item.match_date, item.league, item.home_team, item.away_team))
    return matches


def latest_complete_month(matches: list[HistoricalMatch], minimum_rows: int = 300) -> tuple[date, date]:
    grouped: dict[tuple[int, int], list[date]] = {}
    for match in matches:
        grouped.setdefault((match.match_date.year, match.match_date.month), []).append(match.match_date)
    eligible = [
        (year, month) for (year, month), dates in grouped.items()
        if len(dates) >= minimum_rows and max(dates).day == calendar.monthrange(year, month)[1]
    ]
    if not eligible:
        raise ValueError("no complete month with enough named-book rows")
    year, month = max(eligible)
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def complete_months(matches: list[HistoricalMatch], minimum_rows: int = 300) -> list[tuple[date, date]]:
    grouped: dict[tuple[int, int], list[date]] = {}
    for match in matches:
        grouped.setdefault((match.match_date.year, match.match_date.month), []).append(match.match_date)
    return [
        (date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))
        for year, month in sorted(grouped)
        if len(grouped[(year, month)]) >= minimum_rows
        and max(grouped[(year, month)]).day == calendar.monthrange(year, month)[1]
    ]


def _months_before(start: date, count: int) -> date:
    index = start.year * 12 + start.month - 1 - count
    return date(index // 12, index % 12 + 1, 1)


def _priced_books(books: tuple[dict[str, Any], ...], strategy: Strategy) -> list[dict[str, Any]]:
    priced_books = []
    for source in books:
        row = dict(source)
        cost_rate = (
            strategy.exchange_commission_rate
            if str(row["bookmaker_key"]) in strategy.exchange_bookmaker_keys else 0.0
        )
        row["execution_cost_rate"] = cost_rate
        for outcome in OUTCOMES:
            raw_odds = float(source[f"{outcome}_odds"])
            row[f"raw_{outcome}_odds"] = raw_odds
            row[f"{outcome}_odds"] = 1.0 + (raw_odds - 1.0) * (1.0 - cost_rate)
        priced_books.append(row)
    return priced_books


def _candidates(match: HistoricalMatch, strategy: Strategy) -> list[dict[str, Any]]:
    priced_books = _priced_books(match.books, strategy)
    possible: list[dict[str, Any]] = []
    for outcome in OUTCOMES:
        ranked_execution = sorted(
            priced_books, key=lambda row: float(row[f"{outcome}_odds"]), reverse=True
        )
        execution_index = strategy.execution_price_rank - 1
        if execution_index < 0 or execution_index >= len(ranked_execution):
            continue
        execution = ranked_execution[execution_index]
        references = [row for row in priced_books if row["bookmaker_key"] != execution["bookmaker_key"]]
        if len(references) < strategy.minimum_reference_bookmakers:
            continue
        robust = _robust_consensus(references)
        if robust is None:
            continue
        probabilities, dispersions = robust
        probability = float(probabilities[outcome])
        uncapped_commission_net_price = float(execution[f"{outcome}_odds"])
        comparison_index = execution_index + 1
        second_best_price = (
            float(ranked_execution[comparison_index][f"{outcome}_odds"])
            if comparison_index < len(ranked_execution)
            else uncapped_commission_net_price
        )
        commission_net_price = uncapped_commission_net_price
        if strategy.maximum_execution_quote_advantage_ratio is not None:
            commission_net_price = min(
                commission_net_price,
                second_best_price
                * float(strategy.maximum_execution_quote_advantage_ratio),
            )
        price = 1.0 + (commission_net_price - 1.0) * (1.0 - strategy.slippage_rate)
        conservative_probability = max(
            0.001,
            probability - strategy.uncertainty_floor - strategy.dispersion_multiplier * dispersions[outcome],
        )
        conservative_ev = conservative_probability * price - 1.0
        fair_price = 1.0 / probability
        price_ratio = price * probability
        execution_cost_rate = float(execution["execution_cost_rate"])
        effective_raw_odds = 1.0 + (
            (commission_net_price - 1.0) / max(1.0 - execution_cost_rate, 1e-9)
        )
        raw_execution_implied = {
            key: 1.0 / float(execution[f"raw_{key}_odds"])
            for key in OUTCOMES
        }
        raw_execution_total = sum(raw_execution_implied.values())
        execution_probabilities = {
            key: value / raw_execution_total
            for key, value in raw_execution_implied.items()
        }
        execution_probability_gaps = {
            key: float(probabilities[key]) - execution_probabilities[key]
            for key in OUTCOMES
        }
        nonselected_gaps = [
            abs(value) for key, value in execution_probability_gaps.items()
            if key != outcome
        ]
        if not strategy.minimum_probability <= probability:
            continue
        if not 1.5 <= price <= strategy.maximum_odds:
            continue
        if price < fair_price * strategy.minimum_price_ratio:
            continue
        if (
            strategy.maximum_price_ratio is not None
            and price_ratio > strategy.maximum_price_ratio
        ):
            continue
        if conservative_ev < strategy.minimum_conservative_ev:
            continue
        possible.append({
            "outcome": outcome, "probability": probability,
            "conservative_probability": conservative_probability,
            "odds": price, "raw_odds": effective_raw_odds,
            "uncapped_raw_odds": execution[f"raw_{outcome}_odds"],
            "uncapped_net_odds": uncapped_commission_net_price,
            "execution_cost_rate": execution["execution_cost_rate"],
            "conservative_ev": conservative_ev,
            "price_ratio": price_ratio,
            "execution_bookmaker": execution["bookmaker_key"],
            "reference_bookmakers": sorted(row["bookmaker_key"] for row in references),
            "reference_dispersion": dispersions[outcome],
            "consensus_probabilities": {
                key: float(probabilities[key]) for key in OUTCOMES
            },
            "consensus_dispersions": {
                key: float(dispersions[key]) for key in OUTCOMES
            },
            "execution_quote_advantage_pct": (
                commission_net_price / second_best_price - 1.0
            ) * 100.0,
            "execution_book_overround": raw_execution_total - 1.0,
            "execution_selected_probability_gap": execution_probability_gaps[outcome],
            "execution_nonselected_mean_absolute_gap": sum(nonselected_gaps) / len(nonselected_gaps),
            "execution_selection_specificity": (
                abs(execution_probability_gaps[outcome])
                - sum(nonselected_gaps) / len(nonselected_gaps)
            ),
        })
    return possible


def _candidate(match: HistoricalMatch, strategy: Strategy) -> dict[str, Any] | None:
    possible = _candidates(match, strategy)
    return max(possible, key=lambda row: (row["conservative_ev"], row["odds"])) if possible else None


def _closing_price_quality(
    match: HistoricalMatch, candidate: dict[str, Any], strategy: Strategy,
) -> dict[str, Any]:
    if len(match.closing_books) < strategy.minimum_reference_bookmakers:
        return {"closing_probability": None, "closing_fair_odds": None,
                "closing_edge_pct": None, "positive_clv": None}
    robust = _robust_consensus(_priced_books(match.closing_books, strategy))
    if robust is None:
        return {"closing_probability": None, "closing_fair_odds": None,
                "closing_edge_pct": None, "positive_clv": None}
    probabilities, _dispersion = robust
    probability = float(probabilities[str(candidate["outcome"])])
    edge = float(candidate["odds"]) * probability - 1.0
    return {
        "closing_probability": probability, "closing_fair_odds": 1.0 / probability,
        "closing_edge_pct": edge * 100.0, "positive_clv": edge > 0,
    }


def _odds_band(odds: float) -> str:
    if odds < 2.0:
        return "1.5-2.0"
    if odds < 3.0:
        return "2.0-3.0"
    if odds < 4.0:
        return "3.0-4.0"
    if odds < 5.0:
        return "4.0-5.0"
    return "5.0+"


def _candidate_buckets(candidate: dict[str, Any]) -> tuple[str, str, str]:
    source_type = "exchange" if float(candidate["execution_cost_rate"]) > 0.0 else "sportsbook"
    return (
        f"outcome:{candidate['outcome']}",
        f"odds:{_odds_band(float(candidate['odds']))}",
        f"source:{source_type}",
    )


def _learn_clv_bucket_gate(
    rows: list[HistoricalMatch], strategy: Strategy, start: date, end: date,
    candidate_cache: dict[tuple[str, int], dict[str, Any] | None],
) -> dict[str, Any]:
    boundary = _months_before(end.replace(day=1) + timedelta(days=32), 3)
    observations: dict[str, list[tuple[date, float, bool]]] = {}
    for match in rows:
        if not start <= match.match_date <= end:
            continue
        candidate = candidate_cache.get((match.source_file, match.source_row))
        if candidate is None:
            continue
        quality = _closing_price_quality(match, candidate, strategy)
        edge = quality["closing_edge_pct"]
        if edge is None:
            continue
        for key in _candidate_buckets(candidate):
            observations.setdefault(key, []).append((match.match_date, float(edge), bool(quality["positive_clv"])))

    buckets = []
    for key, values in sorted(observations.items()):
        first = [row for row in values if row[0] < boundary]
        second = [row for row in values if row[0] >= boundary]
        average = sum(row[1] for row in values) / len(values)
        first_average = sum(row[1] for row in first) / len(first) if first else None
        second_average = sum(row[1] for row in second) / len(second) if second else None
        positive_rate = sum(row[2] for row in values) / len(values)
        eligible = (
            len(values) >= 12 and len(first) >= 4 and len(second) >= 4
            and first_average is not None and first_average > 0
            and second_average is not None and second_average > 0
            and positive_rate >= 0.55
        )
        buckets.append({
            "bucket": key, "eligible": eligible, "observations": len(values),
            "first_half_observations": len(first), "second_half_observations": len(second),
            "average_closing_edge_pct": round(average, 4),
            "first_half_closing_edge_pct": round(first_average, 4) if first_average is not None else None,
            "second_half_closing_edge_pct": round(second_average, 4) if second_average is not None else None,
            "positive_clv_rate": round(positive_rate, 4),
        })
    allowed = sorted(row["bucket"] for row in buckets if row["eligible"])
    return {
        "rule": "all outcome, odds-band and source-type buckets need n>=12, each half n>=4 and positive mean CLV; full positive CLV rate>=55%",
        "allowed_buckets": allowed,
        "buckets": buckets,
    }


def _apply_clv_bucket_gate(
    candidate_cache: dict[tuple[str, int], dict[str, Any] | None], allowed_buckets: list[str],
) -> dict[tuple[str, int], dict[str, Any] | None]:
    allowed = set(allowed_buckets)
    return {
        key: candidate if candidate is not None and all(
            bucket in allowed for bucket in _candidate_buckets(candidate)
        ) else None
        for key, candidate in candidate_cache.items()
    }


def build_candidate_cache(
    matches: list[HistoricalMatch], strategy: Strategy,
) -> dict[tuple[str, int], dict[str, Any] | None]:
    return {(match.source_file, match.source_row): _candidate(match, strategy) for match in matches}


def build_candidate_universe_cache(
    matches: list[HistoricalMatch], strategy: Strategy,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Preserve every eligible opening direction for research-only ranking."""
    return {
        (match.source_file, match.source_row): _candidates(match, strategy)
        for match in matches
    }


def replay(matches: list[HistoricalMatch], strategy: Strategy, start: date, end: date,
           candidate_cache: dict[tuple[str, int], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    selected = [match for match in matches if start <= match.match_date <= end]
    by_day: dict[date, list[HistoricalMatch]] = {}
    for match in selected:
        by_day.setdefault(match.match_date, []).append(match)
    equity = peak = max_drawdown = 0.0
    positions: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    current = start
    while current <= end:
        # Freeze the complete candidate pool before consulting any result for this date.
        frozen = []
        for match in by_day.get(current, []):
            candidate = (
                candidate_cache.get((match.source_file, match.source_row))
                if candidate_cache is not None else _candidate(match, strategy)
            )
            if candidate is not None:
                frozen.append((match, candidate))
        frozen.sort(key=lambda item: float(item[1]["conservative_ev"]), reverse=True)
        remaining = strategy.daily_budget
        day_positions: list[dict[str, Any]] = []
        for match, candidate in frozen:
            odds = float(candidate["odds"])
            probability = float(candidate["conservative_probability"])
            full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
            stake = round(min(
                strategy.maximum_single_stake, remaining,
                strategy.daily_budget * strategy.kelly_fraction * full_kelly,
            ), 2)
            if stake <= 0:
                continue
            remaining = round(remaining - stake, 2)
            won = match.actual_outcome == candidate["outcome"]
            profit = round(stake * (odds - 1.0) if won else -stake, 2)
            closing_quality = _closing_price_quality(match, candidate, strategy)
            position = {
                "date": current.isoformat(), "league": match.league,
                "match": f"{match.home_team} v {match.away_team}",
                **candidate, **closing_quality, "stake": stake, "actual_outcome": match.actual_outcome,
                "profit": profit, "won": won, "source_file": match.source_file,
                "source_row": match.source_row,
            }
            positions.append(position)
            day_positions.append(position)
        day_profit = round(sum(row["profit"] for row in day_positions), 2)
        day_staked = round(sum(row["stake"] for row in day_positions), 2)
        equity = round(equity + day_profit, 2)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        daily.append({
            "date": current.isoformat(), "bets": len(day_positions), "staked": day_staked,
            "profit": day_profit, "equity_change": day_profit, "cumulative_profit": equity,
            "drawdown": round(peak - equity, 2), "cash_reserved": round(strategy.daily_budget - day_staked, 2),
        })
        current += timedelta(days=1)
    staked = round(sum(row["stake"] for row in positions), 2)
    profit = round(sum(row["profit"] for row in positions), 2)
    outcome_counts = Counter(row["outcome"] for row in positions)
    clv_rows = [row for row in positions if row.get("closing_edge_pct") is not None]
    return {
        "strategy": asdict(strategy), "period_start": start.isoformat(), "period_end": end.isoformat(),
        "matches": len(selected), "bets": len(positions), "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        "win_rate": round(sum(row["won"] for row in positions) / len(positions), 4) if positions else 0.0,
        "max_drawdown": round(max_drawdown, 2), "ending_profit": profit,
        "clv_positions": len(clv_rows),
        "average_closing_edge_pct": round(
            sum(float(row["closing_edge_pct"]) for row in clv_rows) / len(clv_rows), 4
        ) if clv_rows else None,
        "positive_clv_rate": round(
            sum(bool(row["positive_clv"]) for row in clv_rows) / len(clv_rows), 4
        ) if clv_rows else None,
        "outcome_counts": dict(outcome_counts), "daily": daily, "positions": positions,
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {key: report.get(key) for key in (
        "period_start", "period_end", "matches", "bets", "staked", "profit", "roi_pct",
        "win_rate", "max_drawdown", "clv_positions", "average_closing_edge_pct",
        "positive_clv_rate", "outcome_counts",
    )}


def _strategy_hash() -> str:
    payload = json.dumps([asdict(item) for item in STRATEGIES], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _data_hash(matches: list[HistoricalMatch]) -> str:
    digest = hashlib.sha256()
    for match in matches:
        payload = {
            "date": match.match_date.isoformat(), "league": match.league,
            "home": match.home_team, "away": match.away_team,
            "actual": match.actual_outcome, "books": match.books, "closing_books": match.closing_books,
            "source_file": match.source_file, "source_row": match.source_row,
        }
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def _training_selection(
    rows: list[HistoricalMatch], train_start: date, train_end: date,
    caches: dict[str, dict[tuple[str, int], dict[str, Any] | None]] | None = None,
    strategies: tuple[Strategy, ...] = STRATEGIES,
    selection_mode: str = "profit_stability",
) -> tuple[list[dict[str, Any]], Strategy | None]:
    boundary = _months_before(train_end.replace(day=1) + timedelta(days=32), 3)
    candidates = []
    for strategy in strategies:
        cache = (caches or {}).get(strategy.name)
        full = replay(rows, strategy, train_start, train_end, cache)
        first = replay(rows, strategy, train_start, boundary - timedelta(days=1), cache)
        second = replay(rows, strategy, boundary, train_end, cache)
        if selection_mode == "clv_stability":
            eligible = (
                full["clv_positions"] >= 30 and first["clv_positions"] >= 10 and second["clv_positions"] >= 10
                and float(first["average_closing_edge_pct"] or -999) > 0
                and float(second["average_closing_edge_pct"] or -999) > 0
                and float(first["positive_clv_rate"] or 0) >= 0.50
                and float(second["positive_clv_rate"] or 0) >= 0.50
            )
        else:
            eligible = (
                full["bets"] >= 30 and first["bets"] >= 10 and second["bets"] >= 10
                and first["profit"] > 0 and second["profit"] > 0
            )
        candidates.append({
            "name": strategy.name, "eligible": eligible, "train": _summary(full),
            "first_half": _summary(first), "second_half": _summary(second),
        })
    eligible = [row for row in candidates if row["eligible"]]
    if selection_mode == "clv_stability":
        selected = max(
            eligible,
            key=lambda row: (
                min(float(row["first_half"]["average_closing_edge_pct"]),
                    float(row["second_half"]["average_closing_edge_pct"])),
                float(row["train"]["average_closing_edge_pct"]),
                int(row["train"]["clv_positions"]),
            ),
        ) if eligible else None
    else:
        selected = max(
            eligible,
            key=lambda row: (
                min(float(row["first_half"]["roi_pct"]), float(row["second_half"]["roi_pct"])),
                float(row["train"]["profit"]) / max(float(row["train"]["max_drawdown"]), 0.01),
            ),
        ) if eligible else None
    strategy = next((item for item in strategies if selected and item.name == selected["name"]), None)
    return candidates, strategy


def prepare(output_dir: Path, matches: list[HistoricalMatch] | None = None) -> dict[str, Any]:
    rows = matches if matches is not None else load_matches()
    test_start, test_end = latest_complete_month(rows)
    train_start = _months_before(test_start, 6)
    train_end = test_start - timedelta(days=1)
    candidates, selected_strategy = _training_selection(rows, train_start, train_end)
    payload = {
        "stage": "PREPARED_HOLDOUT_SEALED", "prepared_at": datetime.now().astimezone().isoformat(),
        "data_rule": "latest calendar month with >=300 named-book rows and data through month-end",
        "train_window": f"{train_start}..{train_end}", "sealed_test_window": f"{test_start}..{test_end}",
        "strategy_grid_sha256": _strategy_hash(), "dataset_sha256": _data_hash(rows),
        "dataset_matches": len(rows), "candidates": candidates,
        "selected_strategy": selected_strategy.name if selected_strategy else "ABSTAIN",
        "selection_rule": "both 3-month halves profitable with >=10 bets, >=30 total; maximize worst-half ROI then profit/drawdown",
        "holdout_outcomes_used_during_selection": False,
        "research_limitation": "Named opening columns lack quote timestamps; this cannot promote live capital.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sealed_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def evaluate(output_dir: Path, matches: list[HistoricalMatch] | None = None) -> dict[str, Any]:
    manifest_path = output_dir / "sealed_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["stage"] != "PREPARED_HOLDOUT_SEALED" or manifest["strategy_grid_sha256"] != _strategy_hash():
        raise ValueError("sealed manifest does not match the registered strategy grid")
    if (output_dir / "holdout_summary.json").exists():
        raise ValueError("sealed holdout has already been evaluated; create a future holdout instead of retuning it")
    start_text, end_text = manifest["sealed_test_window"].split("..")
    start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    rows = matches if matches is not None else load_matches()
    if manifest.get("dataset_sha256") != _data_hash(rows):
        raise ValueError("historical dataset changed after holdout sealing")
    strategy = next((item for item in STRATEGIES if item.name == manifest["selected_strategy"]), None)
    if strategy is None:
        report = {
            "stage": "HOLDOUT_EVALUATED", "decision": "ABSTAINED_ON_TRAIN",
            "sealed_test_window": manifest["sealed_test_window"], "bets": 0, "staked": 0.0,
            "profit": 0.0, "roi_pct": 0.0, "daily": [], "positions": [],
        }
    else:
        replay_report = replay(rows, strategy, start, end)
        report = {
            "stage": "HOLDOUT_EVALUATED", "decision": "INVESTED_FIXED_TRAIN_SELECTION",
            "selected_strategy": strategy.name, "sealed_test_window": manifest["sealed_test_window"],
            "same_day_results_hidden_until_all_decisions_frozen": True,
            "unlimited_principal_daily_investment_cap": strategy.daily_budget,
            "historical_price_limitation": "Opening fields are named but timestamp-unverified; research-only.",
            **replay_report,
        }
    (output_dir / "holdout_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(report["daily"]).to_csv(output_dir / "holdout_daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report["positions"]).to_csv(output_dir / "holdout_positions.csv", index=False, encoding="utf-8-sig")
    return report


def audit(output_dir: Path) -> dict[str, Any]:
    report = json.loads((output_dir / "holdout_summary.json").read_text(encoding="utf-8"))
    daily = list(report.get("daily") or [])
    positions = list(report.get("positions") or [])
    active_days = sum(int(row.get("bets") or 0) > 0 for row in daily)
    total_capacity = len(daily) * float(report.get("unlimited_principal_daily_investment_cap") or 100.0)
    outcome_counts = Counter(str(row.get("outcome")) for row in positions)
    concentration = max(outcome_counts.values(), default=0) / len(positions) if positions else 0.0
    reasons: list[str] = []
    if len(positions) < 30:
        reasons.append("bets<30")
    if active_days < 10:
        reasons.append("active_betting_days<10")
    if concentration > 0.75:
        reasons.append("selected_outcome_concentration>75pct")
    decision = "INSUFFICIENT_SAMPLE" if any(
        reason in {"bets<30", "active_betting_days<10"} for reason in reasons
    ) else (
        "REJECTED_DIRECTION_CONCENTRATION" if reasons else
        "HISTORICAL_RESEARCH_SURVIVOR" if float(report.get("profit") or 0) > 0
        else "REJECTED_NON_POSITIVE_PROFIT"
    )
    payload = {
        "method": "post-evaluation evidence audit; no strategy parameter is changed and the sealed month is never rerun",
        "sealed_test_window": report["sealed_test_window"],
        "selected_strategy": report.get("selected_strategy"),
        "nominal_result": "POSITIVE" if float(report.get("profit") or 0) > 0 else "NON_POSITIVE",
        "bets": len(positions), "active_betting_days": active_days,
        "staked": float(report.get("staked") or 0), "profit": float(report.get("profit") or 0),
        "nominal_roi_pct": float(report.get("roi_pct") or 0),
        "available_monthly_capacity": round(total_capacity, 2),
        "capital_utilization_pct": round(float(report.get("staked") or 0) / total_capacity * 100, 4) if total_capacity else 0.0,
        "outcome_counts": dict(outcome_counts),
        "maximum_outcome_concentration_pct": round(concentration * 100, 2),
        "evidence_decision": decision, "decision_reasons": reasons,
        "profitability_claim_allowed": decision == "HISTORICAL_RESEARCH_SURVIVOR",
        "next_experiment_rule": "Do not retune or rerun 2026-05; validate a newly registered challenger on future unseen data.",
        "live_promotion_allowed": False,
        "live_blocker": "Historical named opening fields have no quote timestamps; prospective T-1 evidence is mandatory.",
    }
    (output_dir / "evidence_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def _monthly_bootstrap(rows: list[dict[str, Any]], iterations: int = 5000, seed: int = 42) -> dict[str, Any]:
    if len(rows) < 12:
        return {"status": "INSUFFICIENT_FOLDS", "folds": len(rows), "lower_95_pct": None,
                "median_pct": None, "upper_95_pct": None}
    rng = random.Random(seed)
    estimates = []
    for _ in range(iterations):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        staked = sum(float(row["staked"]) for row in sample)
        if staked > 0:
            estimates.append(sum(float(row["profit"]) for row in sample) / staked * 100.0)
    estimates.sort()
    if not estimates:
        return {
            "status": "NO_STAKED_POSITIONS", "folds": len(rows),
            "iterations": iterations, "seed": seed,
            "lower_95_pct": None, "median_pct": None, "upper_95_pct": None,
        }
    def percentile(probability: float) -> float | None:
        if not estimates:
            return None
        position = (len(estimates) - 1) * probability
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return estimates[lower]
        return estimates[lower] + (estimates[upper] - estimates[lower]) * (position - lower)
    return {
        "status": "READY", "folds": len(rows), "iterations": iterations, "seed": seed,
        "lower_95_pct": round(float(percentile(0.025)), 4),
        "median_pct": round(float(percentile(0.5)), 4),
        "upper_95_pct": round(float(percentile(0.975)), 4),
    }


def rolling_nested(output_dir: Path, fold_count: int = 18,
                   matches: list[HistoricalMatch] | None = None,
                   minimum_month_rows: int = 300,
                   exchange_commission_rate: float = 0.05,
                   selection_mode: str = "profit_stability") -> dict[str, Any]:
    rows = matches if matches is not None else load_matches()
    latest_start, _latest_end = latest_complete_month(rows, minimum_month_rows)
    folds = [
        window for window in complete_months(rows, minimum_month_rows) if window[0] < latest_start
    ][-max(1, fold_count):]
    strategies = tuple(replace(strategy, exchange_commission_rate=exchange_commission_rate) for strategy in STRATEGIES)
    caches = {strategy.name: build_candidate_cache(rows, strategy) for strategy in strategies}
    monthly: list[dict[str, Any]] = []
    all_positions: list[dict[str, Any]] = []
    for test_start, test_end in folds:
        train_start, train_end = _months_before(test_start, 6), test_start - timedelta(days=1)
        base_selection_mode = "clv_stability" if selection_mode == "clv_bucket_stability" else selection_mode
        candidates, selected = _training_selection(
            rows, train_start, train_end, caches, strategies, base_selection_mode
        )
        selected_train = next((row for row in candidates if selected and row["name"] == selected.name), None)
        if selected is None:
            monthly.append({
                "month": test_start.strftime("%Y-%m"), "train_window": f"{train_start}..{train_end}",
                "selected_strategy": "ABSTAIN", "selection_reason": f"no candidate passed {selection_mode} in both training halves",
                "matches": sum(test_start <= row.match_date <= test_end for row in rows),
                "bets": 0, "active_days": 0, "staked": 0.0, "profit": 0.0,
                "roi_pct": 0.0, "max_drawdown": 0.0, "outcome_counts": {},
                "available_capacity": (test_end - test_start).days * 100.0 + 100.0,
            })
            continue
        bucket_gate = None
        holdout_cache = caches[selected.name]
        if selection_mode == "clv_bucket_stability":
            bucket_gate = _learn_clv_bucket_gate(
                rows, selected, train_start, train_end, caches[selected.name]
            )
            holdout_cache = _apply_clv_bucket_gate(
                caches[selected.name], bucket_gate["allowed_buckets"]
            )
        holdout = replay(rows, selected, test_start, test_end, holdout_cache)
        all_positions.extend({"test_month": test_start.strftime("%Y-%m"), **row} for row in holdout["positions"])
        monthly.append({
            "month": test_start.strftime("%Y-%m"), "train_window": f"{train_start}..{train_end}",
            "selected_strategy": selected.name, "selection_reason": "fixed prior-six-month two-half rule",
            "selected_train_evidence": selected_train, "matches": holdout["matches"],
            "clv_bucket_gate": bucket_gate,
            "bets": holdout["bets"], "active_days": sum(row["bets"] > 0 for row in holdout["daily"]),
            "staked": holdout["staked"], "profit": holdout["profit"], "roi_pct": holdout["roi_pct"],
            "max_drawdown": holdout["max_drawdown"], "outcome_counts": holdout["outcome_counts"],
            "clv_positions": holdout["clv_positions"],
            "average_closing_edge_pct": holdout["average_closing_edge_pct"],
            "positive_clv_rate": holdout["positive_clv_rate"],
            "available_capacity": len(holdout["daily"]) * selected.daily_budget,
        })
    staked = round(sum(float(row["staked"]) for row in monthly), 2)
    profit = round(sum(float(row["profit"]) for row in monthly), 2)
    capacity = round(sum(float(row["available_capacity"]) for row in monthly), 2)
    outcomes = Counter(str(row["outcome"]) for row in all_positions)
    clv_positions = [row for row in all_positions if row.get("closing_edge_pct") is not None]
    average_clv = (
        sum(float(row["closing_edge_pct"]) for row in clv_positions) / len(clv_positions)
        if clv_positions else None
    )
    positive_clv_rate = (
        sum(bool(row["positive_clv"]) for row in clv_positions) / len(clv_positions)
        if clv_positions else None
    )
    concentration = max(outcomes.values(), default=0) / len(all_positions) if all_positions else 0.0
    active = [row for row in monthly if int(row["bets"]) > 0]
    bootstrap = _monthly_bootstrap(monthly)
    reasons = []
    if len(monthly) < 12: reasons.append("monthly_folds<12")
    if len(active) < 6: reasons.append("active_months<6")
    if len(all_positions) < 100: reasons.append("bets<100")
    if active and sum(float(row["profit"]) > 0 for row in active) / len(active) < 0.60:
        reasons.append("positive_active_month_rate<60pct")
    if profit <= 0: reasons.append("aggregate_profit<=0")
    if bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0:
        reasons.append("monthly_bootstrap_roi_lower_95<=0")
    if concentration > 0.75: reasons.append("selected_outcome_concentration>75pct")
    utilization = staked / capacity * 100.0 if capacity else 0.0
    if utilization < 0.50: reasons.append("capital_utilization<0.5pct")
    if selection_mode in {"clv_stability", "clv_bucket_stability"} and (average_clv is None or average_clv <= 0):
        reasons.append("average_closing_edge<=0")
    if selection_mode in {"clv_stability", "clv_bucket_stability"} and (positive_clv_rate is None or positive_clv_rate < 0.50):
        reasons.append("positive_clv_rate<50pct")
    payload = {
        "method": "nested monthly walk-forward: prior six months select, immediate next complete month evaluate",
        "selection_mode": selection_mode,
        "exchange_commission_rate": exchange_commission_rate,
        "data_cutoff": max(row.match_date for row in rows).isoformat(),
        "latest_sealed_month_excluded": latest_start.strftime("%Y-%m"),
        "folds": len(monthly), "active_months": len(active),
        "abstained_months": sum(row["selected_strategy"] == "ABSTAIN" for row in monthly),
        "positive_active_months": sum(float(row["profit"]) > 0 for row in active),
        "bets": len(all_positions), "staked": staked, "profit": profit,
        "roi_pct": round(profit / staked * 100.0, 2) if staked else 0.0,
        "maximum_fold_drawdown": max((float(row["max_drawdown"]) for row in monthly), default=0.0),
        "available_capacity": capacity, "capital_utilization_pct": round(utilization, 4),
        "outcome_counts": dict(outcomes), "maximum_outcome_concentration_pct": round(concentration * 100.0, 2),
        "clv_positions": len(clv_positions),
        "average_closing_edge_pct": round(average_clv, 4) if average_clv is not None else None,
        "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
        "monthly_bootstrap_roi": bootstrap,
        "decision": "ROLLING_RESEARCH_SURVIVOR" if not reasons else "ROLLING_REJECTED",
        "decision_reasons": reasons, "monthly": monthly,
        "positions_sample": all_positions[:100],
        "guardrail": "Exploratory historical evidence only; 2026-05 remains sealed from all rolling selection and no live order is possible.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rolling_nested_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(monthly).drop(columns=["selected_train_evidence"], errors="ignore").to_csv(
        output_dir / "rolling_monthly.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(all_positions).to_csv(
        output_dir / "rolling_positions.csv", index=False, encoding="utf-8-sig"
    )
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "evaluate", "audit", "rolling"))
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "robust_consensus_latest_month_holdout_v1")
    parser.add_argument("--fold-count", type=int, default=18)
    parser.add_argument("--exchange-commission-rate", type=float, default=0.05)
    parser.add_argument(
        "--selection-mode",
        choices=("profit_stability", "clv_stability", "clv_bucket_stability"),
        default="profit_stability",
    )
    args = parser.parse_args()
    report = (
        prepare(args.output_dir) if args.stage == "prepare" else
        evaluate(args.output_dir) if args.stage == "evaluate" else
        audit(args.output_dir) if args.stage == "audit" else
        rolling_nested(
            args.output_dir, args.fold_count,
            exchange_commission_rate=args.exchange_commission_rate,
            selection_mode=args.selection_mode,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
