from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_diagnostics import ODDS_SOURCE_COLUMNS  # noqa: E402
from market_bias_diagnostics import build_market_frame  # noqa: E402
from market_bias_custom_bands import add_i2_draw_band, i2_draw_band_rule  # noqa: E402
from market_bias_walk_forward import _parse_rule, run_walk_forward_frame  # noqa: E402


DEFAULT_RULE = "league|outcome|odds_bucket=I2|draw|[2.8,3.5)"
DEFAULT_SOURCES = (
    "AVG_OPEN",
    "AVG_CLOSE",
    "MAX_OPEN",
    "MAX_CLOSE",
    "B365_OPEN",
    "B365_CLOSE",
    "PS_OPEN",
    "PS_CLOSE",
)


@dataclass(frozen=True)
class GateProfile:
    name: str
    lookback_months: int
    min_active_months: int
    min_bets: int
    min_roi: float
    max_rules: int = 3


PROFILES = (
    GateProfile("default", 12, 6, 50, 0.02),
    GateProfile("lookback18", 18, 6, 50, 0.02),
    GateProfile("stricter_selection", 12, 8, 80, 0.04),
)


def _parse_rules(raw_rules: list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    rules = []
    for raw in raw_rules:
        columns_raw, key_raw = raw.split("=", 1)
        rules.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    return rules


def _latest_season(summary: dict[str, Any]) -> dict[str, Any] | None:
    return (summary.get("stability_assessment") or {}).get("latest_season")


def _season_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return list((summary.get("stability_assessment") or {}).get("season_summary") or [])


def _row_passes(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if row["bets"] < 100:
        reasons.append("bets<100")
    if row["roi_pct"] < 3.0:
        reasons.append("roi<3%")
    if row["profit"] <= 0:
        reasons.append("profit<=0")
    if row["active_months"] < 12:
        reasons.append("active_months<12")
    if row["positive_months"] <= row["negative_months"]:
        reasons.append("positive_months<=negative_months")
    if row["max_drawdown"] > max(row["profit"], 1.0):
        reasons.append("drawdown>profit")
    if row["latest_season_bets"] < 10:
        reasons.append("latest_season_bets<10")
    if row["latest_season_profit"] < 0:
        reasons.append("latest_season_profit<0")
    if row["positive_seasons"] <= row["negative_seasons"]:
        reasons.append("positive_seasons<=negative_seasons")
    return not reasons, reasons


def _summarize_run(odds_source: str, profile: GateProfile, summary: dict[str, Any]) -> dict[str, Any]:
    overall = summary["overall"]
    latest = _latest_season(summary) or {}
    seasons = _season_summary(summary)
    row = {
        "odds_source": odds_source,
        "profile": profile.name,
        "lookback_months": profile.lookback_months,
        "min_active_months": profile.min_active_months,
        "min_bets": profile.min_bets,
        "min_roi": profile.min_roi,
        "bets": int(overall["bets"]),
        "profit": float(overall["profit"]),
        "roi_pct": float(overall["roi_pct"]),
        "max_drawdown": float(overall["max_drawdown"]),
        "active_months": int(summary["active_months"]),
        "positive_months": int(summary["positive_months"]),
        "negative_months": int(summary["negative_months"]),
        "positive_seasons": sum(float(item.get("profit") or 0) > 0 for item in seasons),
        "negative_seasons": sum(float(item.get("profit") or 0) < 0 for item in seasons),
        "latest_season": latest.get("season"),
        "latest_season_bets": int(latest.get("bets") or 0),
        "latest_season_profit": float(latest.get("profit") or 0.0),
        "verdict": (summary.get("stability_assessment") or {}).get("verdict"),
    }
    passes, reasons = _row_passes(row)
    row["passes_gate"] = passes
    row["fail_reasons"] = reasons
    return row


def run_gate(seasons: tuple[str, ...], first_month: str, last_month: str, raw_rules: list[str],
             odds_sources: tuple[str, ...], profiles: tuple[GateProfile, ...], daily_limit: float,
             i2_draw_band: tuple[float, float] | None = None) -> dict[str, Any]:
    rules = _parse_rules(raw_rules)
    rows: list[dict[str, Any]] = []
    monthly_frames = []
    for odds_source in odds_sources:
        frame = build_market_frame(seasons, odds_source)
        if i2_draw_band:
            frame = add_i2_draw_band(frame, i2_draw_band[0], i2_draw_band[1])
        for profile in profiles:
            summary, days, bets = run_walk_forward_frame(
                frame,
                seasons,
                first_month,
                last_month,
                rules,
                profile.lookback_months,
                profile.min_active_months,
                profile.min_bets,
                profile.min_roi,
                profile.max_rules,
                daily_limit,
                odds_source,
            )
            row = _summarize_run(odds_source, profile, summary)
            rows.append(row)
            if not days.empty:
                monthly_frames.append(days.assign(
                    odds_source=odds_source,
                    profile=profile.name,
                ))
    table = pd.DataFrame(rows)
    source_groups = table.groupby("odds_source")["passes_gate"].agg(["sum", "count"]).reset_index()
    profile_groups = table.groupby("profile")["passes_gate"].agg(["sum", "count"]).reset_index()
    passed_rows = int(table["passes_gate"].sum()) if not table.empty else 0
    total_rows = int(len(table))
    source_passes = int((source_groups["sum"] > 0).sum()) if not source_groups.empty else 0
    profile_passes = int((profile_groups["sum"] > 0).sum()) if not profile_groups.empty else 0
    stable_open_avg_or_max = bool(table[
        (table["odds_source"].isin(["AVG_OPEN", "MAX_OPEN"]))
        & (table["profile"] == "default")
        & (table["passes_gate"])
    ].shape[0] >= 1)
    b365_close_warning = bool(table[
        (table["odds_source"] == "B365_CLOSE")
        & (table["latest_season_profit"] < 0)
    ].shape[0] > 0)
    decision = "KEEP_SHADOW_ONLY"
    reasons = [
        "official SP prospective sample is not yet sufficient for production promotion",
    ]
    if passed_rows < 6:
        reasons.append("fewer than 6 source/profile runs passed the robustness gate")
    if source_passes < 4:
        reasons.append("fewer than 4 odds sources passed at least one profile")
    if profile_passes < 2:
        reasons.append("fewer than 2 rolling-selection profiles passed")
    if not stable_open_avg_or_max:
        reasons.append("AVG_OPEN or MAX_OPEN default profile did not pass")
    if b365_close_warning:
        reasons.append("B365_CLOSE has negative latest-season evidence; live price quality remains mandatory")
    if passed_rows >= 6 and source_passes >= 4 and profile_passes >= 2 and stable_open_avg_or_max:
        decision = "RESEARCH_CANDIDATE_SHADOW_VALIDATION"
    return {
        "method": "market-bias robustness gate",
        "seasons": seasons,
        "first_month": first_month,
        "last_month": last_month,
        "rules": raw_rules,
        "custom_i2_draw_band": i2_draw_band,
        "profiles": [asdict(profile) for profile in profiles],
        "odds_sources": odds_sources,
        "total_runs": total_rows,
        "passed_runs": passed_rows,
        "source_passes": source_passes,
        "profile_passes": profile_passes,
        "decision": decision,
        "decision_reasons": reasons,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--rule", action="append", default=None)
    parser.add_argument("--odds-sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--profiles", default=",".join(profile.name for profile in PROFILES))
    parser.add_argument("--daily-limit", type=float, default=100.0)
    parser.add_argument("--i2-draw-band-low", type=float)
    parser.add_argument("--i2-draw-band-high", type=float)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_robustness_gate_i2_draw"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    odds_sources = tuple(item.strip() for item in args.odds_sources.split(",") if item.strip())
    unknown_sources = [source for source in odds_sources if source not in ODDS_SOURCE_COLUMNS]
    if unknown_sources:
        raise SystemExit(f"Unknown odds source(s): {', '.join(unknown_sources)}")
    profile_names = {item.strip() for item in args.profiles.split(",") if item.strip()}
    profiles = tuple(profile for profile in PROFILES if profile.name in profile_names)
    if not profiles:
        raise SystemExit("No matching profiles selected")
    i2_draw_band = None
    if args.i2_draw_band_low is not None or args.i2_draw_band_high is not None:
        if args.i2_draw_band_low is None or args.i2_draw_band_high is None:
            raise SystemExit("--i2-draw-band-low and --i2-draw-band-high must be provided together")
        i2_draw_band = (args.i2_draw_band_low, args.i2_draw_band_high)
    raw_rules = args.rule or ([i2_draw_band_rule(*i2_draw_band)] if i2_draw_band else [DEFAULT_RULE])
    summary = run_gate(seasons, args.first_month, args.last_month, raw_rules, odds_sources, profiles, args.daily_limit, i2_draw_band)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(summary["rows"]).to_csv(args.output_dir / "runs.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
