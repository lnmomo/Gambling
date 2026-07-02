from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from market_bias_walk_forward import _parse_rule, run_walk_forward_frame  # noqa: E402
from market_bias_candidate_screen import DEFAULT_RULE, load_candidate_rules  # noqa: E402


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    rules: tuple[str, ...]
    seasons: tuple[str, ...]
    first_month: str
    last_month: str


DEFAULT_CANDIDATES = (
    CandidateSpec(
        "market-bias-i2-draw-2.8-3.5-v1",
        ("league|outcome|odds_bucket=I2|draw|[2.8,3.5)",),
        ("2122", "2223", "2324", "2425", "2526"),
        "2022-08",
        "2026-05",
    ),
    CandidateSpec(
        "market-bias-sp1-home-market-prob-0.55-1.00-v1",
        ("league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]",),
        ("2122", "2223", "2324", "2425", "2526"),
        "2022-08",
        "2026-05",
    ),
    CandidateSpec(
        "market-bias-i2-draw-plus-sp1-home-v1",
        (
            "league|outcome|odds_bucket=I2|draw|[2.8,3.5)",
            "league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]",
        ),
        ("2122", "2223", "2324", "2425", "2526"),
        "2022-08",
        "2026-05",
    ),
)


def _parse_rules(raw_rules: tuple[str, ...] | list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    parsed = []
    for raw in raw_rules:
        columns_raw, key_raw = raw.split("=", 1)
        parsed.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    return parsed


def _month_windows(first_month: str, last_month: str, window_months: int, step_months: int) -> list[tuple[str, str]]:
    periods = list(pd.period_range(first_month, last_month, freq="M"))
    windows = []
    for start_idx in range(0, len(periods), step_months):
        end_idx = start_idx + window_months - 1
        if end_idx >= len(periods):
            break
        windows.append((str(periods[start_idx]), str(periods[end_idx])))
    return windows


def _window_passes(row: dict[str, Any], min_bets: int, min_roi_pct: float,
                   min_positive_month_edge: int, max_drawdown_to_profit: float) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    profit = float(row["profit"])
    drawdown = float(row["max_drawdown"])
    positive_months = int(row["positive_months"])
    negative_months = int(row["negative_months"])
    drawdown_to_profit = drawdown / profit if profit > 0 else None
    if int(row["bets"]) < min_bets:
        reasons.append("bets<minimum")
    if profit <= 0:
        reasons.append("profit<=0")
    if float(row["roi_pct"]) < min_roi_pct:
        reasons.append("roi<minimum")
    if positive_months - negative_months < min_positive_month_edge:
        reasons.append("positive_month_edge<minimum")
    if drawdown_to_profit is None or drawdown_to_profit > max_drawdown_to_profit:
        reasons.append("drawdown_to_profit>maximum")
    return not reasons, reasons


def summarize_candidate_windows(rows: list[dict[str, Any]], *,
                                min_pass_rate: float = 0.6,
                                min_source_pass_rate: float = 0.5,
                                min_active_windows: int = 6) -> dict[str, Any]:
    if not rows:
        return {
            "window_count": 0,
            "passed_windows": 0,
            "pass_rate": 0.0,
            "active_window_count": 0,
            "active_passed_windows": 0,
            "active_pass_rate": 0.0,
            "source_count": 0,
            "source_passes": 0,
            "source_pass_rate": 0.0,
            "total_bets": 0,
            "total_staked": 0.0,
            "total_profit": 0.0,
            "combined_roi_pct": 0.0,
            "worst_window_roi_pct": 0.0,
            "worst_source_roi_pct": 0.0,
            "decision": "REJECT_NO_WINDOWS",
        }
    frame = pd.DataFrame(rows)
    passed_windows = int(frame["passes_window"].sum())
    window_count = int(len(frame))
    active_frame = frame[frame["bets"] > 0]
    active_window_count = int(len(active_frame))
    active_passed_windows = int(active_frame["passes_window"].sum()) if active_window_count else 0
    source_rows = []
    for source, group in frame.groupby("odds_source"):
        active_group = group[group["bets"] > 0]
        staked = float(group["total_staked"].sum())
        profit = float(group["profit"].sum())
        source_rows.append({
            "odds_source": source,
            "windows": int(len(group)),
            "active_windows": int(len(active_group)),
            "passed_windows": int(group["passes_window"].sum()),
            "active_passed_windows": int(active_group["passes_window"].sum()) if not active_group.empty else 0,
            "profit": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        })
    source_passes = sum(row["passed_windows"] > 0 and row["profit"] > 0 and row["roi_pct"] > 0 for row in source_rows)
    source_count = len(source_rows)
    total_staked = float(frame["total_staked"].sum())
    total_profit = float(frame["profit"].sum())
    pass_rate = passed_windows / window_count if window_count else 0.0
    active_pass_rate = active_passed_windows / active_window_count if active_window_count else 0.0
    source_pass_rate = source_passes / source_count if source_count else 0.0
    calendar_stable = pass_rate >= min_pass_rate
    active_stable = active_window_count >= min_active_windows and active_pass_rate >= min_pass_rate
    if (calendar_stable or active_stable) and source_pass_rate >= min_source_pass_rate and total_profit > 0:
        decision = "MULTI_WINDOW_SHADOW_CANDIDATE"
    elif total_profit > 0 and passed_windows > 0:
        decision = "RESEARCH_ONLY_UNSTABLE_WINDOWS"
    else:
        decision = "REJECT_UNSTABLE"
    return {
        "window_count": window_count,
        "passed_windows": passed_windows,
        "pass_rate": round(pass_rate, 4),
        "active_window_count": active_window_count,
        "active_passed_windows": active_passed_windows,
        "active_pass_rate": round(active_pass_rate, 4),
        "min_active_windows": min_active_windows,
        "source_count": source_count,
        "source_passes": int(source_passes),
        "source_pass_rate": round(source_pass_rate, 4),
        "total_bets": int(frame["bets"].sum()),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "combined_roi_pct": round(total_profit / total_staked * 100, 2) if total_staked else 0.0,
        "worst_window_roi_pct": round(float(frame["roi_pct"].min()), 2),
        "worst_source_roi_pct": round(min((row["roi_pct"] for row in source_rows), default=0.0), 2),
        "source_summary": source_rows,
        "decision": decision,
    }


def _evaluate_window(unit_bets: pd.DataFrame, candidate: CandidateSpec, odds_source: str, start_month: str,
                     end_month: str, args: argparse.Namespace) -> dict[str, Any]:
    if unit_bets.empty:
        window_bets = unit_bets
    else:
        month_values = pd.to_datetime(unit_bets["date"]).dt.to_period("M").astype(str)
        window_bets = unit_bets[(month_values >= start_month) & (month_values <= end_month)].copy()
    portfolio, _, placed_bets = simulate_settlement_portfolio(
        window_bets,
        daily_limit=args.daily_limit,
        max_single_stake=args.max_single_stake,
        settlement_delay_days=args.settlement_delay_days,
        stop_after_losing_settlement_days=args.stop_after_losing_settlement_days,
        cooldown_days=args.cooldown_days,
    )
    overall = portfolio["overall"]
    row = {
        "candidate_id": candidate.candidate_id,
        "odds_source": odds_source,
        "window_start": start_month,
        "window_end": end_month,
        "bets": int(overall["bets"]),
        "total_staked": float(overall["total_staked"]),
        "profit": float(overall["profit"]),
        "roi_pct": float(overall["roi_pct"]),
        "max_drawdown": float(overall["max_drawdown"]),
        "active_bet_days": int(overall["active_bet_days"]),
        "positive_months": int(portfolio.get("positive_months") or 0),
        "negative_months": int(portfolio.get("negative_months") or 0),
        "walk_forward_active_months": int(window_bets["month"].nunique()) if "month" in window_bets else 0,
    }
    if not placed_bets.empty and "rule_label" in placed_bets:
        contributions = []
        for label, group in placed_bets.groupby("rule_label"):
            profit = float(group["profit"].sum())
            staked = float(group["stake"].sum()) if "stake" in group else float(len(group))
            contributions.append({
                "rule_label": str(label),
                "bets": int(len(group)),
                "profit": round(profit, 2),
                "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
            })
        contributions.sort(key=lambda item: (item["profit"], item["bets"]), reverse=True)
        row["rule_contributions"] = contributions
        row["active_rules"] = len(contributions)
    else:
        row["rule_contributions"] = []
        row["active_rules"] = 0
    passes, reasons = _window_passes(
        row,
        args.validation_min_bets,
        args.validation_min_roi_pct,
        args.min_positive_month_edge,
        args.max_drawdown_to_profit,
    )
    row["passes_window"] = passes
    row["fail_reasons"] = reasons
    return row


def run_multi_window_optimizer(candidates: tuple[CandidateSpec, ...], odds_sources: tuple[str, ...],
                               args: argparse.Namespace) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    unit_bet_frames: list[pd.DataFrame] = []
    for candidate in candidates:
        windows = _month_windows(candidate.first_month, candidate.last_month, args.window_months, args.step_months)
        for odds_source in odds_sources:
            frame = build_market_frame(candidate.seasons, odds_source)
            _, _, unit_bets = run_walk_forward_frame(
                frame,
                candidate.seasons,
                candidate.first_month,
                candidate.last_month,
                _parse_rules(candidate.rules),
                args.lookback_months,
                args.min_active_months,
                args.selection_min_bets,
                args.selection_min_roi,
                args.max_rules,
                args.daily_limit,
                odds_source,
            )
            if not unit_bets.empty:
                unit_bet_frames.append(unit_bets.assign(
                    candidate_id=candidate.candidate_id,
                    odds_source=odds_source,
                ))
            for start_month, end_month in windows:
                rows.append(_evaluate_window(unit_bets, candidate, odds_source, start_month, end_month, args))
    summaries = []
    for candidate in candidates:
        candidate_rows = [row for row in rows if row["candidate_id"] == candidate.candidate_id]
        summaries.append({
            "candidate_id": candidate.candidate_id,
            "rules": list(candidate.rules),
            **summarize_candidate_windows(
                candidate_rows,
                min_pass_rate=args.min_pass_rate,
                min_source_pass_rate=args.min_source_pass_rate,
                min_active_windows=args.min_active_windows,
            ),
        })
    summaries.sort(key=lambda row: (
        row["decision"] == "MULTI_WINDOW_SHADOW_CANDIDATE",
        row["pass_rate"],
        row["source_pass_rate"],
        row["combined_roi_pct"],
        row["total_profit"],
    ), reverse=True)
    return {
        "method": "market-bias multi-window walk-forward optimizer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "odds_sources": list(odds_sources),
            "window_months": args.window_months,
            "step_months": args.step_months,
            "lookback_months": args.lookback_months,
            "selection_min_active_months": args.min_active_months,
            "selection_min_bets": args.selection_min_bets,
            "selection_min_roi": args.selection_min_roi,
            "daily_limit": args.daily_limit,
            "max_single_stake": args.max_single_stake,
            "validation_min_bets": args.validation_min_bets,
            "validation_min_roi_pct": args.validation_min_roi_pct,
            "min_positive_month_edge": args.min_positive_month_edge,
            "max_drawdown_to_profit": args.max_drawdown_to_profit,
            "min_pass_rate": args.min_pass_rate,
            "min_source_pass_rate": args.min_source_pass_rate,
            "min_active_windows": args.min_active_windows,
            "window_evaluation_mode": "slice_full_no_lookahead_walk_forward_bets",
        },
        "candidate_summaries": summaries,
        "rows": rows,
        "unit_bets": pd.concat(unit_bet_frames, ignore_index=True) if unit_bet_frames else pd.DataFrame(),
        "next_step": "Only candidates with MULTI_WINDOW_SHADOW_CANDIDATE should proceed to official-SP prospective validation.",
    }


def _load_candidates(path: Path | None) -> tuple[CandidateSpec, ...]:
    if path is None:
        return DEFAULT_CANDIDATES
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        CandidateSpec(
            str(item["candidate_id"]),
            tuple(item["rules"]),
            tuple(item["seasons"]),
            str(item["first_month"]),
            str(item["last_month"]),
        )
        for item in payload["candidates"]
    )


def _candidate_id_from_rule(rule: str) -> str:
    normalized = (
        rule.lower()
        .replace("=", "-")
        .replace("|", "-")
        .replace("[", "")
        .replace(")", "")
        .replace(",", "-")
        .replace(".", "p")
    )
    safe = "".join(char if char.isalnum() or char == "-" else "-" for char in normalized)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return f"diagnostic-{safe.strip('-')}"


def load_candidates_from_diagnostics(
    diagnostics_csv: list[Path],
    top_n: int,
    seasons: tuple[str, ...],
    first_month: str,
    last_month: str,
    min_diagnostic_sources: int,
    include_default_rule: bool,
    combo_size: int = 1,
    max_combinations: int | None = None,
) -> tuple[CandidateSpec, ...]:
    if combo_size < 1:
        raise ValueError("combo_size must be >= 1")
    rules = load_candidate_rules(
        diagnostics_csv,
        top_n=top_n,
        include_rule=DEFAULT_RULE if include_default_rule else None,
        min_source_count=min_diagnostic_sources,
    )
    groups = itertools.combinations(rules, combo_size)
    if max_combinations is not None:
        groups = itertools.islice(groups, max_combinations)
    return tuple(
        CandidateSpec(
            "combo-" + "-plus-".join(_candidate_id_from_rule(rule).removeprefix("diagnostic-") for rule in rule_group)
            if combo_size > 1 else _candidate_id_from_rule(rule_group[0]),
            tuple(rule_group),
            seasons,
            first_month,
            last_month,
        )
        for rule_group in groups
    )


def load_candidates(args: argparse.Namespace) -> tuple[CandidateSpec, ...]:
    if args.candidates_json and args.diagnostics_csv:
        raise SystemExit("--candidates-json and --diagnostics-csv cannot be used together")
    if args.diagnostics_csv:
        seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
        return load_candidates_from_diagnostics(
            args.diagnostics_csv,
            args.top_n,
            seasons,
            args.first_month,
            args.last_month,
            args.min_diagnostic_sources,
            not args.no_include_default_rule,
            args.combo_size,
            args.max_combinations,
        )
    return _load_candidates(args.candidates_json)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-json", type=Path)
    parser.add_argument("--diagnostics-csv", type=Path, action="append")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-diagnostic-sources", type=int, default=1)
    parser.add_argument("--no-include-default-rule", action="store_true")
    parser.add_argument("--combo-size", type=int, default=1)
    parser.add_argument("--max-combinations", type=int)
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--window-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--min-active-months", type=int, default=6)
    parser.add_argument("--selection-min-bets", type=int, default=50)
    parser.add_argument("--selection-min-roi", type=float, default=0.02)
    parser.add_argument("--max-rules", type=int, default=3)
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--max-single-stake", type=float, default=10.0)
    parser.add_argument("--settlement-delay-days", type=int, default=1)
    parser.add_argument("--stop-after-losing-settlement-days", type=int, default=999)
    parser.add_argument("--cooldown-days", type=int, default=0)
    parser.add_argument("--validation-min-bets", type=int, default=20)
    parser.add_argument("--validation-min-roi-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-month-edge", type=int, default=1)
    parser.add_argument("--max-drawdown-to-profit", type=float, default=1.5)
    parser.add_argument("--min-pass-rate", type=float, default=0.6)
    parser.add_argument("--min-source-pass-rate", type=float, default=0.5)
    parser.add_argument("--min-active-windows", type=int, default=12)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_multi_window_optimizer"))
    args = parser.parse_args()
    odds_sources = tuple(item.strip() for item in args.odds_sources.split(",") if item.strip())
    candidates = load_candidates(args)
    result = run_multi_window_optimizer(candidates, odds_sources, args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    unit_bets = result.pop("unit_bets")
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["rows"]).to_csv(args.output_dir / "windows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result["candidate_summaries"]).to_csv(args.output_dir / "candidate_summaries.csv", index=False, encoding="utf-8-sig")
    unit_bets.to_csv(args.output_dir / "unit_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
