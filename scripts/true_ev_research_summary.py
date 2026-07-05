from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _screen_status(screen: dict[str, Any]) -> dict[str, Any]:
    summaries = screen.get("rule_summary") or []
    best = summaries[0] if summaries else None
    passed = [row for row in summaries if row.get("passes_all_validation_sources")]
    if passed:
        status = "PASSED_CROSS_SOURCE_SCREEN"
        reason = "at least one rule passed all validation sources"
    elif best:
        status = "REJECTED_BY_CROSS_SOURCE_SCREEN"
        source_results = best.get("source_results") or []
        reason = "; ".join(
            f"{row.get('odds_source')}: {','.join(row.get('fail_reasons') or [])}"
            for row in source_results
        )
    else:
        status = "NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER"
        reason = "diagnostic positives failed recency/specificity filters before validation"
    return {
        "status": status,
        "passed_rules": len(passed),
        "best_rule": best.get("rule") if best else None,
        "best_combined_roi_pct": best.get("combined_roi_pct") if best else 0.0,
        "best_total_bets": best.get("total_portfolio_bets") if best else 0,
        "best_worst_source_roi_pct": best.get("worst_source_roi_pct") if best else 0.0,
        "reason": reason,
    }


def _multi_window_status(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {"available": False}
    summaries = report.get("candidate_summaries") or []
    ranked = sorted(
        summaries,
        key=lambda row: (
            int(row.get("total_bets") or 0) > 0,
            row.get("decision") == "MULTI_WINDOW_SHADOW_CANDIDATE",
            float(row.get("combined_roi_pct") or 0),
            int(row.get("total_bets") or 0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    passed = [row for row in summaries if row.get("decision") == "MULTI_WINDOW_SHADOW_CANDIDATE"]
    return {
        "available": True,
        "passed_candidates": len(passed),
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_decision": best.get("decision") if best else "NO_CANDIDATES",
        "best_total_bets": best.get("total_bets") if best else 0,
        "best_combined_roi_pct": best.get("combined_roi_pct") if best else 0.0,
        "best_active_pass_rate": best.get("active_pass_rate") if best else 0.0,
        "best_source_pass_rate": best.get("source_pass_rate") if best else 0.0,
        "best_worst_source_roi_pct": best.get("worst_source_roi_pct") if best else 0.0,
    }


def summarize_true_ev_search(
    *,
    discovery_path: Path,
    screen_paths: list[Path],
    multi_window_paths: list[Path] | None = None,
) -> dict[str, Any]:
    discovery = _load(discovery_path)
    screens = []
    for path in screen_paths:
        screen = _load(path)
        seasons = screen.get("seasons") or []
        domain = str(seasons[0]) if seasons else path.parent.name
        screens.append({
            "domain": domain,
            "path": str(path),
            "candidate_count": int(screen.get("candidate_count") or 0),
            "passed_count": int(screen.get("passed_count") or 0),
            **_screen_status(screen),
        })
    windows = []
    for path in multi_window_paths or []:
        report = _load(path)
        windows.append({
            "path": str(path),
            **_multi_window_status(report),
        })
    screen_passes = sum(row["passed_rules"] for row in screens)
    window_passes = sum(row.get("passed_candidates", 0) for row in windows)
    if screen_passes and (not windows or window_passes):
        decision = "TRUE_EV_CANDIDATE_REQUIRES_OFFICIAL_SP_VALIDATION"
    elif screen_passes:
        decision = "CROSS_SOURCE_PASS_BUT_MULTI_WINDOW_UNPROVEN"
    else:
        decision = "NO_TRUE_EV_CANDIDATE_FOUND"
    return {
        "method": "true EV research evidence summary",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "discovery_path": str(discovery_path),
        "selected_domains": discovery.get("selected_domains") or [],
        "domain_count": int(discovery.get("domain_count") or 0),
        "domains_with_diagnostic_hits": int(discovery.get("domains_with_diagnostic_hits") or 0),
        "screened_domains": len(screens),
        "screen_passed_rules": screen_passes,
        "multi_window_passed_candidates": window_passes,
        "decision": decision,
        "screens": screens,
        "multi_window": windows,
        "interpretation": (
            "A diagnostic positive is not treated as true EV until it survives cross-source prices, "
            "12-month rolling windows, settlement-aware daily allocation, and later official-SP prospective validation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize true-EV discovery and validation reports.")
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--screen", type=Path, action="append", required=True)
    parser.add_argument("--multi-window", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=Path("reports/true_ev_research_summary/summary.json"))
    args = parser.parse_args()
    summary = summarize_true_ev_search(
        discovery_path=args.discovery,
        screen_paths=args.screen,
        multi_window_paths=args.multi_window or [],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
