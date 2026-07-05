from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_diagnostics import build_market_frame, run_diagnostics  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402


def _parse_rule(rule: str) -> tuple[list[str], list[str]]:
    columns, key = rule.split("=", 1)
    return columns.split("|"), key.split("|")


def _filter_rule(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    columns, values = _parse_rule(rule)
    if len(columns) != len(values):
        return frame.iloc[0:0].copy()
    mask = pd.Series(True, index=frame.index)
    for column, value in zip(columns, values):
        if column not in frame.columns:
            return frame.iloc[0:0].copy()
        mask &= frame[column].astype(str) == value
    return frame[mask].copy()


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "bets": 0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "positive_months": 0,
            "negative_months": 0,
            "max_drawdown": 0.0,
        }
    monthly = frame.groupby("month")["unit_profit"].sum().sort_index()
    settlement_days = int(frame["date"].nunique())
    equity = peak = max_drawdown = 0.0
    for profit in frame.sort_values("date")["unit_profit"].astype(float):
        equity += profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    profit = float(frame["unit_profit"].sum())
    return {
        "bets": int(len(frame)),
        "profit": round(profit, 2),
        "roi_pct": round(profit / len(frame) * 100, 2),
        "positive_months": int((monthly > 0).sum()),
        "negative_months": int((monthly < 0).sum()),
        "max_drawdown": round(float(max_drawdown), 2),
        "settlement_days": settlement_days,
    }


def _yearly_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    metrics = _metrics(frame)
    if frame.empty:
        return {**metrics, "positive_years": 0, "negative_years": 0}
    yearly = frame.groupby(pd.to_datetime(frame["date"]).dt.year)["unit_profit"].sum()
    return {
        **metrics,
        "positive_years": int((yearly > 0).sum()),
        "negative_years": int((yearly < 0).sum()),
    }


def _decision(test: dict[str, Any], min_test_bets: int, min_roi_pct: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if test["bets"] < min_test_bets:
        reasons.append("test_bets<minimum")
    if test["profit"] <= 0:
        reasons.append("test_profit<=0")
    if test["roi_pct"] < min_roi_pct:
        reasons.append("test_roi<threshold")
    if test["positive_months"] <= test["negative_months"]:
        reasons.append("positive_months<=negative_months")
    if test.get("positive_years", 1) <= test.get("negative_years", 0):
        reasons.append("positive_years<=negative_years")
    if test["max_drawdown"] > max(test["profit"], 1.0):
        reasons.append("drawdown>profit")
    if reasons:
        return "REJECT_TOURNAMENT_HOLDOUT_WEAK", reasons
    return "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY", []


def _match_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    return int(frame[["date", "home_team", "away_team"]].drop_duplicates().shape[0])


def _flatten_rule_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        flattened = {
            "rule": row["rule"],
            "decision": row["decision"],
            "decision_reasons": ";".join(row["decision_reasons"]),
        }
        if "test_year" in row:
            flattened["test_year"] = row["test_year"]
        if "test_years_with_bets" in row:
            flattened["test_years_with_bets"] = row["test_years_with_bets"]
        for side in ("train", "test"):
            if side not in row:
                continue
            for key, value in row[side].items():
                flattened[f"{side}_{key}"] = value
        output.append(flattened)
    return output


def _portfolio_decision(summary: dict[str, Any], min_bets: int, min_roi_pct: float) -> tuple[str, list[str]]:
    overall = summary.get("overall") or {}
    reasons: list[str] = []
    profit = float(overall.get("profit") or 0.0)
    roi_pct = float(overall.get("roi_pct") or 0.0)
    max_drawdown = float(overall.get("max_drawdown") or 0.0)
    bets = int(overall.get("bets") or 0)
    positive_months = int(summary.get("positive_months") or 0)
    negative_months = int(summary.get("negative_months") or 0)
    positive_years = int(summary.get("positive_years") or 0)
    negative_years = int(summary.get("negative_years") or 0)
    if bets < min_bets:
        reasons.append("portfolio_bets<minimum")
    if profit <= 0:
        reasons.append("portfolio_profit<=0")
    if roi_pct < min_roi_pct:
        reasons.append("portfolio_roi<threshold")
    if positive_months <= negative_months:
        reasons.append("positive_months<=negative_months")
    if positive_years <= negative_years:
        reasons.append("positive_years<=negative_years")
    if max_drawdown > max(profit, 1.0):
        reasons.append("drawdown>profit")
    if reasons:
        return "REJECT_WORLD_CUP_PORTFOLIO_WEAK", reasons
    return "WORLD_CUP_PORTFOLIO_RESEARCH_ONLY", []


def _add_year_summary(summary: dict[str, Any], bets: pd.DataFrame) -> dict[str, Any]:
    if bets.empty:
        return {**summary, "year_summary": [], "positive_years": 0, "negative_years": 0}
    frame = bets.copy()
    frame["year"] = pd.to_datetime(frame["bet_date"]).dt.year
    rows = []
    for year, group in frame.groupby("year"):
        staked = float(group["stake"].sum())
        profit = float(group["profit"].sum())
        rows.append({
            "year": int(year),
            "bets": int(len(group)),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        })
    return {
        **summary,
        "year_summary": rows,
        "positive_years": sum(row["profit"] > 0 for row in rows),
        "negative_years": sum(row["profit"] < 0 for row in rows),
    }


def _rule_score(train_metrics: dict[str, Any], prior_bets: int) -> float:
    bets = int(train_metrics.get("bets") or 0)
    profit = float(train_metrics.get("profit") or 0.0)
    if bets <= 0:
        return -999.0
    raw_roi = profit / bets
    shrink = bets / (bets + max(prior_bets, 1))
    month_edge = int(train_metrics.get("positive_months") or 0) - int(train_metrics.get("negative_months") or 0)
    drawdown = float(train_metrics.get("max_drawdown") or 0.0)
    drawdown_penalty = drawdown / max(profit, 1.0) if profit > 0 else 9.99
    return raw_roi * shrink + 0.01 * month_edge - 0.02 * drawdown_penalty


def validate_world_cup_rolling_portfolio(
    seasons: tuple[str, ...] = ("WORLD_CUP",),
    odds_source: str = "AVG_CLOSE",
    first_test_year: int = 2018,
    last_test_year: int | None = None,
    top_n: int = 20,
    max_rules: int = 3,
    min_train_samples: int = 20,
    min_train_active_months: int = 1,
    min_train_roi_pct: float = 0.0,
    min_test_bets: int = 80,
    min_roi_pct: float = 3.0,
    daily_limit: float = 100.0,
    max_single_stake: float = 10.0,
    settlement_delay_days: int = 1,
    shrink_prior_bets: int = 80,
    allowed_outcomes: tuple[str, ...] = (),
    min_odds: float | None = None,
    max_odds: float | None = None,
    min_market_probability: float | None = None,
    max_market_probability: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = build_market_frame(seasons, odds_source)
    filters: list[str] = []
    if allowed_outcomes:
        allowed = {item.strip().lower() for item in allowed_outcomes if item.strip()}
        frame = frame[frame["outcome"].astype(str).str.lower().isin(allowed)].copy()
        filters.append(f"allowed_outcomes={','.join(sorted(allowed))}")
    if min_odds is not None:
        frame = frame[frame["odds"].astype(float) >= float(min_odds)].copy()
        filters.append(f"odds>={min_odds:g}")
    if max_odds is not None:
        frame = frame[frame["odds"].astype(float) <= float(max_odds)].copy()
        filters.append(f"odds<={max_odds:g}")
    if min_market_probability is not None:
        frame = frame[frame["market_probability"].astype(float) >= float(min_market_probability)].copy()
        filters.append(f"market_probability>={min_market_probability:g}")
    if max_market_probability is not None:
        frame = frame[frame["market_probability"].astype(float) <= float(max_market_probability)].copy()
        filters.append(f"market_probability<={max_market_probability:g}")
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    available_years = sorted(int(year) for year in frame["year"].dropna().unique())
    test_years = [year for year in available_years if year >= first_test_year and (last_test_year is None or year <= last_test_year)]
    fold_rows: list[dict[str, Any]] = []
    selected_parts: list[pd.DataFrame] = []
    skipped_years: list[dict[str, Any]] = []

    for test_year in test_years:
        train = frame[frame["year"] < test_year].copy()
        test = frame[frame["year"] == test_year].copy()
        if train.empty or test.empty:
            skipped_years.append({"year": test_year, "reason": "missing_train_or_test"})
            continue
        diagnostics = run_diagnostics(train, min_train_samples, min_train_active_months, 3)
        if diagnostics.empty:
            skipped_years.append({"year": test_year, "reason": "no_training_rule"})
            continue
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, row in diagnostics.head(top_n).iterrows():
            rule = f"{row['columns']}={row['key']}"
            if rule in seen:
                continue
            seen.add(rule)
            train_selected = _filter_rule(train, rule)
            train_metrics = _yearly_metrics(train_selected)
            train_roi = float(train_metrics["profit"]) / max(int(train_metrics["bets"]), 1) * 100
            if train_metrics["profit"] <= 0 or train_roi < min_train_roi_pct:
                continue
            score = _rule_score(train_metrics, shrink_prior_bets)
            if score <= 0:
                continue
            candidates.append({
                "rule": rule,
                "train": train_metrics,
                "score": score,
                "shrunk_train_roi_pct": round(score * 100, 3),
            })
        candidates.sort(key=lambda item: (item["score"], item["train"]["profit"], item["train"]["bets"]), reverse=True)
        selected_rules = candidates[:max_rules]
        if not selected_rules:
            skipped_years.append({"year": test_year, "reason": "no_positive_shrunk_training_edge"})
            continue
        year_parts = []
        for item in selected_rules:
            selected = _filter_rule(test, item["rule"]).copy()
            if selected.empty:
                continue
            selected["rule_label"] = item["rule"]
            selected["train_edge_score"] = item["score"]
            selected["train_bets"] = item["train"]["bets"]
            selected["train_profit"] = item["train"]["profit"]
            year_parts.append(selected)
        if year_parts:
            year_selected = pd.concat(year_parts, ignore_index=True, sort=False)
            year_selected["bet_key"] = (
                year_selected["date"].astype(str) + "|"
                + year_selected["home_team"].astype(str) + "|"
                + year_selected["away_team"].astype(str) + "|"
                + year_selected["outcome"].astype(str)
            )
            year_selected = (
                year_selected.sort_values(["train_edge_score", "market_probability", "odds"], ascending=[False, False, False])
                .drop_duplicates("bet_key")
                .copy()
            )
            selected_parts.append(year_selected)
            test_metrics = _yearly_metrics(year_selected)
        else:
            test_metrics = _yearly_metrics(test.iloc[0:0].copy())
        fold_rows.append({
            "test_year": test_year,
            "selected_rules": selected_rules,
            "test": test_metrics,
        })

    selected_frame = pd.concat(selected_parts, ignore_index=True, sort=False) if selected_parts else frame.iloc[0:0].copy()
    portfolio, daily, bets = simulate_settlement_portfolio(
        selected_frame,
        daily_limit=daily_limit,
        max_single_stake=max_single_stake,
        settlement_delay_days=settlement_delay_days,
    )
    portfolio = _add_year_summary(portfolio, bets)
    decision, reasons = _portfolio_decision(portfolio, min_test_bets, min_roi_pct)
    summary = {
        "method": "World Cup / qualifiers rolling no-lookahead daily portfolio validation",
        "seasons": seasons,
        "odds_source": odds_source,
        "available_years": available_years,
        "test_years": test_years,
        "top_n": top_n,
        "max_rules": max_rules,
        "min_train_samples": min_train_samples,
        "min_train_active_months": min_train_active_months,
        "min_train_roi_pct": min_train_roi_pct,
        "min_test_bets": min_test_bets,
        "min_roi_pct": min_roi_pct,
        "daily_limit": daily_limit,
        "max_single_stake": max_single_stake,
        "settlement_delay_days": settlement_delay_days,
        "shrink_prior_bets": shrink_prior_bets,
        "candidate_filters": filters,
        "fold_count": len(fold_rows),
        "skipped_years": skipped_years,
        "portfolio": portfolio,
        "decision": decision,
        "decision_reasons": reasons,
        "fold_rows": fold_rows,
        "notes": [
            "Each test year selects rules using only earlier years.",
            "Rule edge is training-window ROI after sample shrinkage and drawdown penalty; no test outcomes are used for selection.",
            "Daily stake allocation is capped by daily_limit and max_single_stake; same-day outcomes are not available until settlement.",
            "A positive result is still research-only until it survives broader international odds and official-SP prospective validation.",
        ],
    }
    return summary, daily, bets, selected_frame


def _parse_float_grid(raw: str, *, allow_none: bool = True) -> tuple[float | None, ...]:
    values: list[float | None] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if allow_none and item.lower() in {"none", "null", "all", "*"}:
            values.append(None)
        else:
            values.append(float(item))
    return tuple(values)


def _parse_outcome_grid(raw: str) -> tuple[tuple[str, ...], ...]:
    specs: list[tuple[str, ...]] = []
    for item in (part.strip() for part in raw.split(";")):
        if not item or item.lower() in {"all", "none", "*"}:
            specs.append(())
        else:
            specs.append(tuple(part.strip() for part in item.split(",") if part.strip()))
    return tuple(specs)


def run_world_cup_portfolio_grid(
    seasons: tuple[str, ...] = ("WORLD_CUP",),
    odds_sources: tuple[str, ...] = ("AVG_CLOSE", "MAX_CLOSE"),
    first_test_year: int = 2018,
    last_test_year: int | None = None,
    top_n: int = 20,
    max_rules_values: tuple[int, ...] = (1, 2, 3),
    min_train_samples: int = 20,
    min_train_active_months: int = 1,
    min_train_roi_pct: float = 0.0,
    min_test_bets: int = 40,
    min_roi_pct: float = 1.0,
    daily_limit: float = 100.0,
    max_single_stake: float = 10.0,
    settlement_delay_days: int = 1,
    shrink_prior_bets: int = 80,
    allowed_outcomes_grid: tuple[tuple[str, ...], ...] = ((), ("draw",)),
    max_odds_values: tuple[float | None, ...] = (3.5, 4.0, 5.0, None),
    min_market_probability_values: tuple[float | None, ...] = (None, 0.2, 0.28),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for odds_source in odds_sources:
        for max_rules in max_rules_values:
            for allowed_outcomes in allowed_outcomes_grid:
                for max_odds in max_odds_values:
                    for min_market_probability in min_market_probability_values:
                        report, _daily, _bets, _selected = validate_world_cup_rolling_portfolio(
                            seasons=seasons,
                            odds_source=odds_source,
                            first_test_year=first_test_year,
                            last_test_year=last_test_year,
                            top_n=top_n,
                            max_rules=max_rules,
                            min_train_samples=min_train_samples,
                            min_train_active_months=min_train_active_months,
                            min_train_roi_pct=min_train_roi_pct,
                            min_test_bets=min_test_bets,
                            min_roi_pct=min_roi_pct,
                            daily_limit=daily_limit,
                            max_single_stake=max_single_stake,
                            settlement_delay_days=settlement_delay_days,
                            shrink_prior_bets=shrink_prior_bets,
                            allowed_outcomes=allowed_outcomes,
                            max_odds=max_odds,
                            min_market_probability=min_market_probability,
                        )
                        overall = report["portfolio"]["overall"]
                        rows.append({
                            "odds_source": odds_source,
                            "max_rules": max_rules,
                            "allowed_outcomes": ",".join(allowed_outcomes) if allowed_outcomes else "all",
                            "max_odds": max_odds,
                            "min_market_probability": min_market_probability,
                            "candidate_filters": ";".join(report.get("candidate_filters") or []),
                            "decision": report["decision"],
                            "decision_reasons": ";".join(report["decision_reasons"]),
                            "bets": int(overall["bets"]),
                            "total_staked": float(overall["total_staked"]),
                            "profit": float(overall["profit"]),
                            "roi_pct": float(overall["roi_pct"]),
                            "max_drawdown": float(overall["max_drawdown"]),
                            "positive_months": int(report["portfolio"].get("positive_months") or 0),
                            "negative_months": int(report["portfolio"].get("negative_months") or 0),
                            "positive_years": int(report["portfolio"].get("positive_years") or 0),
                            "negative_years": int(report["portfolio"].get("negative_years") or 0),
                        })
    rows.sort(key=lambda row: (
        row["decision"] == "WORLD_CUP_PORTFOLIO_RESEARCH_ONLY",
        row["profit"],
        row["roi_pct"],
        -row["max_drawdown"],
        row["bets"],
    ), reverse=True)
    best = rows[0] if rows else None
    passed = [row for row in rows if row["decision"] == "WORLD_CUP_PORTFOLIO_RESEARCH_ONLY"]
    if passed:
        decision = "WORLD_CUP_PORTFOLIO_GRID_HAS_RESEARCH_ONLY_CANDIDATE"
    elif best and best["profit"] > 0:
        decision = "REJECT_GRID_BEST_POSITIVE_BUT_UNSTABLE"
    else:
        decision = "REJECT_GRID_NO_POSITIVE_STABLE_EV"
    return {
        "method": "World Cup / qualifiers portfolio grid search",
        "seasons": seasons,
        "odds_sources": odds_sources,
        "first_test_year": first_test_year,
        "last_test_year": last_test_year,
        "top_n": top_n,
        "max_rules_values": max_rules_values,
        "min_train_samples": min_train_samples,
        "min_train_active_months": min_train_active_months,
        "min_test_bets": min_test_bets,
        "min_roi_pct": min_roi_pct,
        "daily_limit": daily_limit,
        "max_single_stake": max_single_stake,
        "settlement_delay_days": settlement_delay_days,
        "shrink_prior_bets": shrink_prior_bets,
        "allowed_outcomes_grid": ["all" if not item else ",".join(item) for item in allowed_outcomes_grid],
        "max_odds_values": max_odds_values,
        "min_market_probability_values": min_market_probability_values,
        "config_count": len(rows),
        "passed_configs": len(passed),
        "decision": decision,
        "best": best,
        "top": rows[:30],
        "rows": rows,
        "notes": [
            "Every grid row is a full no-lookahead yearly portfolio simulation.",
            "The grid can identify near-misses, but a positive row is not production-ready unless it passes the portfolio decision gate.",
        ],
    }


def validate_world_cup_tournament_holdout(
    seasons: tuple[str, ...] = ("WORLD_CUP",),
    odds_source: str = "AVG_CLOSE",
    train_year: int = 2018,
    test_year: int = 2022,
    top_n: int = 12,
    min_train_samples: int = 8,
    min_train_active_months: int = 1,
    min_test_bets: int = 20,
    min_roi_pct: float = 3.0,
) -> dict[str, Any]:
    frame = build_market_frame(seasons, odds_source)
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    available_years = sorted(int(year) for year in frame["year"].dropna().unique())
    train = frame[frame["year"] == train_year].copy()
    test = frame[frame["year"] == test_year].copy()
    diagnostics = run_diagnostics(train, min_train_samples, min_train_active_months, 3)
    rules: list[str] = []
    for _, row in diagnostics.head(top_n).iterrows():
        rule = f"{row['columns']}={row['key']}"
        if rule not in rules:
            rules.append(rule)

    rows: list[dict[str, Any]] = []
    for rule in rules:
        train_selected = _filter_rule(train, rule)
        test_selected = _filter_rule(test, rule)
        train_metrics = _metrics(train_selected)
        test_metrics = _metrics(test_selected)
        decision, reasons = _decision(test_metrics, min_test_bets, min_roi_pct)
        rows.append({
            "rule": rule,
            "train": train_metrics,
            "test": test_metrics,
            "decision": decision,
            "decision_reasons": reasons,
        })
    passed = [row for row in rows if row["decision"] == "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY"]
    overall_decision = "REJECT_NO_REUSABLE_WORLD_CUP_RULE"
    if passed:
        overall_decision = "RESEARCH_ONLY_TOURNAMENT_HOLDOUT_POSITIVE"
    stability_gate = {
        "status": "BLOCKED",
        "reason": "only_two_world_cup_tournaments_with_archived_odds",
        "minimum_tournament_years": 3,
        "available_tournament_years": available_years,
        "note": "Tournament holdout can reject bad rules, but cannot prove a stable live allocation algorithm with only two World Cups.",
    }
    if len(available_years) >= stability_gate["minimum_tournament_years"]:
        stability_gate = {
            **stability_gate,
            "status": "ELIGIBLE_FOR_MULTI_TOURNAMENT_WALK_FORWARD",
            "reason": "minimum_tournament_years_available",
        }
    promotion_decision = (
        "BLOCK_PRODUCTION_WORLD_CUP_SAMPLE_TOO_SMALL"
        if stability_gate["status"] == "BLOCKED"
        else "RESEARCH_ONLY_PENDING_BROADER_GATES"
    )
    return {
        "method": "World Cup tournament holdout validation",
        "seasons": seasons,
        "odds_source": odds_source,
        "train_year": train_year,
        "test_year": test_year,
        "train_market_rows": int(len(train)),
        "test_market_rows": int(len(test)),
        "train_matches": _match_count(train),
        "test_matches": _match_count(test),
        "available_tournament_years": available_years,
        "top_n": top_n,
        "min_train_samples": min_train_samples,
        "min_test_bets": min_test_bets,
        "min_roi_pct": min_roi_pct,
        "candidate_rules": len(rows),
        "passed_rules": len(passed),
        "decision": overall_decision,
        "promotion_decision": promotion_decision,
        "stability_gate": stability_gate,
        "rows": rows,
        "notes": [
            "Rules are discovered only on the training tournament and tested on a later tournament.",
            "A positive tournament holdout is research-only; it is not enough for live allocation without broader multi-period evidence.",
            "World Cup data is sparse; use it to reject fragile ideas, not to promote a standalone money-allocation strategy.",
        ],
    }


def validate_world_cup_rolling_holdout(
    seasons: tuple[str, ...] = ("WORLD_CUP",),
    odds_source: str = "AVG_CLOSE",
    first_test_year: int = 2018,
    last_test_year: int | None = None,
    top_n: int = 20,
    min_train_samples: int = 20,
    min_train_active_months: int = 4,
    min_test_bets: int = 80,
    min_roi_pct: float = 3.0,
) -> dict[str, Any]:
    frame = build_market_frame(seasons, odds_source)
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    available_years = sorted(int(year) for year in frame["year"].dropna().unique())
    test_years = [year for year in available_years if year >= first_test_year and (last_test_year is None or year <= last_test_year)]
    fold_rows: list[dict[str, Any]] = []
    combined_by_rule: dict[str, list[pd.DataFrame]] = {}
    skipped_years: list[dict[str, Any]] = []

    for test_year in test_years:
        train = frame[frame["year"] < test_year].copy()
        test = frame[frame["year"] == test_year].copy()
        if train.empty or test.empty:
            skipped_years.append({"year": test_year, "reason": "missing_train_or_test"})
            continue
        diagnostics = run_diagnostics(train, min_train_samples, min_train_active_months, 3)
        if diagnostics.empty:
            skipped_years.append({"year": test_year, "reason": "no_training_rule"})
            continue
        rules: list[str] = []
        for _, row in diagnostics.head(top_n).iterrows():
            rule = f"{row['columns']}={row['key']}"
            if rule not in rules:
                rules.append(rule)
        for rule in rules:
            train_selected = _filter_rule(train, rule)
            test_selected = _filter_rule(test, rule)
            if not test_selected.empty:
                combined_by_rule.setdefault(rule, []).append(test_selected)
            test_metrics = _yearly_metrics(test_selected)
            fold_decision, fold_reasons = _decision(test_metrics, 1, min_roi_pct)
            fold_rows.append({
                "test_year": test_year,
                "rule": rule,
                "train": _yearly_metrics(train_selected),
                "test": test_metrics,
                "decision": fold_decision,
                "decision_reasons": fold_reasons,
            })

    combined_rows: list[dict[str, Any]] = []
    for rule, parts in combined_by_rule.items():
        selected = pd.concat(parts, ignore_index=True, sort=False)
        metrics_for_rule = _yearly_metrics(selected)
        decision, reasons = _decision(metrics_for_rule, min_test_bets, min_roi_pct)
        combined_rows.append({
            "rule": rule,
            "test": metrics_for_rule,
            "decision": decision,
            "decision_reasons": reasons,
            "test_years_with_bets": int(selected["year"].nunique()) if "year" in selected else int(pd.to_datetime(selected["date"]).dt.year.nunique()),
        })
    combined_rows.sort(key=lambda row: (
        row["decision"] == "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY",
        row["test"]["profit"],
        row["test"]["roi_pct"],
        row["test"]["bets"],
    ), reverse=True)
    passed = [row for row in combined_rows if row["decision"] == "TOURNAMENT_HOLDOUT_POSITIVE_RESEARCH_ONLY"]
    promotion_decision = "RESEARCH_ONLY_PENDING_BROADER_GATES" if passed else "REJECT_NO_REUSABLE_WORLD_CUP_ROLLING_RULE"
    return {
        "method": "World Cup / qualifiers rolling no-lookahead holdout validation",
        "seasons": seasons,
        "odds_source": odds_source,
        "available_years": available_years,
        "test_years": test_years,
        "top_n": top_n,
        "min_train_samples": min_train_samples,
        "min_train_active_months": min_train_active_months,
        "min_test_bets": min_test_bets,
        "min_roi_pct": min_roi_pct,
        "fold_count": len({row["test_year"] for row in fold_rows}),
        "candidate_rules": len(combined_rows),
        "passed_rules": len(passed),
        "promotion_decision": promotion_decision,
        "skipped_years": skipped_years,
        "combined_rows": combined_rows,
        "fold_rows": fold_rows,
        "notes": [
            "Each test year uses only earlier years for rule discovery.",
            "This mode is better suited to sparse tournament and qualifier data than monthly league-style walk-forward windows.",
            "Passed rules remain research-only until they survive independent official-SP prospective validation.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate World Cup rules by tournament holdout.")
    parser.add_argument("--seasons", default="WORLD_CUP")
    parser.add_argument("--odds-source", default="AVG_CLOSE")
    parser.add_argument("--odds-sources", default="AVG_CLOSE,MAX_CLOSE")
    parser.add_argument("--mode", choices=("single", "rolling", "portfolio", "portfolio-grid"), default="single")
    parser.add_argument("--train-year", type=int, default=2018)
    parser.add_argument("--test-year", type=int, default=2022)
    parser.add_argument("--first-test-year", type=int, default=2018)
    parser.add_argument("--last-test-year", type=int)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--max-rules", type=int, default=3)
    parser.add_argument("--min-train-samples", type=int, default=8)
    parser.add_argument("--min-train-active-months", type=int, default=1)
    parser.add_argument("--min-train-roi-pct", type=float, default=0.0)
    parser.add_argument("--min-test-bets", type=int, default=20)
    parser.add_argument("--min-roi-pct", type=float, default=3.0)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--settlement-delay-days", type=int, default=1)
    parser.add_argument("--shrink-prior-bets", type=int, default=80)
    parser.add_argument("--allowed-outcomes", default="")
    parser.add_argument("--min-odds", type=float)
    parser.add_argument("--max-odds", type=float)
    parser.add_argument("--min-market-probability", type=float)
    parser.add_argument("--max-market-probability", type=float)
    parser.add_argument("--grid-max-rules", default="1,2,3")
    parser.add_argument("--grid-max-odds", default="3.5,4.0,5.0,none")
    parser.add_argument("--grid-min-market-probabilities", default="none,0.2,0.28")
    parser.add_argument("--grid-allowed-outcomes", default="all;draw")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/world_cup_tournament_validation"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    daily = bets = selected = None
    if args.mode == "portfolio-grid":
        summary = run_world_cup_portfolio_grid(
            seasons=seasons,
            odds_sources=tuple(item.strip() for item in args.odds_sources.split(",") if item.strip()),
            first_test_year=args.first_test_year,
            last_test_year=args.last_test_year,
            top_n=args.top_n,
            max_rules_values=tuple(int(item.strip()) for item in args.grid_max_rules.split(",") if item.strip()),
            min_train_samples=args.min_train_samples,
            min_train_active_months=args.min_train_active_months,
            min_train_roi_pct=args.min_train_roi_pct,
            min_test_bets=args.min_test_bets,
            min_roi_pct=args.min_roi_pct,
            daily_limit=args.daily_limit,
            max_single_stake=args.max_single_stake,
            settlement_delay_days=args.settlement_delay_days,
            shrink_prior_bets=args.shrink_prior_bets,
            allowed_outcomes_grid=_parse_outcome_grid(args.grid_allowed_outcomes),
            max_odds_values=_parse_float_grid(args.grid_max_odds),
            min_market_probability_values=_parse_float_grid(args.grid_min_market_probabilities),
        )
    elif args.mode == "portfolio":
        summary, daily, bets, selected = validate_world_cup_rolling_portfolio(
            seasons,
            args.odds_source,
            args.first_test_year,
            args.last_test_year,
            args.top_n,
            args.max_rules,
            args.min_train_samples,
            args.min_train_active_months,
            args.min_train_roi_pct,
            args.min_test_bets,
            args.min_roi_pct,
            args.daily_limit,
            args.max_single_stake,
            args.settlement_delay_days,
            args.shrink_prior_bets,
            tuple(item.strip() for item in args.allowed_outcomes.split(",") if item.strip()),
            args.min_odds,
            args.max_odds,
            args.min_market_probability,
            args.max_market_probability,
        )
    elif args.mode == "rolling":
        summary = validate_world_cup_rolling_holdout(
            seasons,
            args.odds_source,
            args.first_test_year,
            args.last_test_year,
            args.top_n,
            args.min_train_samples,
            args.min_train_active_months,
            args.min_test_bets,
            args.min_roi_pct,
        )
    else:
        summary = validate_world_cup_tournament_holdout(
            seasons,
            args.odds_source,
            args.train_year,
            args.test_year,
            args.top_n,
            args.min_train_samples,
            args.min_train_active_months,
            args.min_test_bets,
            args.min_roi_pct,
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.mode == "portfolio-grid":
        pd.DataFrame(summary["rows"]).to_csv(args.output_dir / "grid.csv", index=False, encoding="utf-8-sig")
    elif args.mode == "portfolio":
        pd.DataFrame(_flatten_rule_rows([
            {
                "rule": "|".join(item["rule"] for item in row["selected_rules"]),
                "test_year": row["test_year"],
                "test": row["test"],
                "decision": "SELECTED_RULE_SET",
                "decision_reasons": [],
            }
            for row in summary["fold_rows"]
        ])).to_csv(args.output_dir / "fold_rules.csv", index=False, encoding="utf-8-sig")
        if daily is not None:
            daily.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
        if bets is not None:
            bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
        if selected is not None:
            selected.to_csv(args.output_dir / "selected_candidates.csv", index=False, encoding="utf-8-sig")
    elif args.mode == "rolling":
        pd.DataFrame(_flatten_rule_rows(summary["combined_rows"])).to_csv(args.output_dir / "rules.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(_flatten_rule_rows(summary["fold_rows"])).to_csv(args.output_dir / "fold_rules.csv", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(_flatten_rule_rows(summary["rows"])).to_csv(args.output_dir / "rules.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
