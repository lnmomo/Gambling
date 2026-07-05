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

from cross_league_rule_search import DEFAULT_SEASONS  # noqa: E402
from market_bias_diagnostics import build_market_frame, run_diagnostics  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_domains(readiness: dict[str, Any], limit: int, offset: int = 0) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    skipped = 0
    for domain in readiness.get("domains") or readiness.get("top_domains") or []:
        if domain.get("research_priority") not in {"MEDIUM_SEARCH", "HIGH_CURRENT_POOL"}:
            continue
        if not str(domain.get("readiness") or "").startswith("SEARCH_READY"):
            continue
        if domain.get("existing_evidence_status"):
            continue
        if not domain.get("best_odds_source"):
            continue
        if skipped < offset:
            skipped += 1
            continue
        selected.append(domain)
        if len(selected) >= limit:
            break
    return selected


def scan_domain(domain: dict[str, Any], min_samples: int, min_active_months: int,
                max_combo_size: int, output_root: Path) -> dict[str, Any]:
    code = str(domain["code"])
    odds_source = str(domain["best_odds_source"])
    output_dir = output_root / f"{code.lower()}_{odds_source.lower()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        paths = [Path(path) for path in domain.get("paths") or []]
        if any(path.parent.name == "new" for path in paths):
            source_seasons = (code,)
            frame = build_market_frame(source_seasons, odds_source)
        else:
            source_seasons = tuple(
                season for season in DEFAULT_SEASONS
                if any(path.parent.name == season for path in paths)
            )
            frame = build_market_frame(source_seasons, odds_source)
            frame = frame[frame["league"].astype(str) == code].copy()
        diagnostics = run_diagnostics(frame, min_samples, min_active_months, max_combo_size)
        frame_path = output_dir / "market_candidates.csv"
        diagnostics_path = output_dir / "market_bias.csv"
        frame.to_csv(frame_path, index=False, encoding="utf-8-sig")
        diagnostics.to_csv(diagnostics_path, index=False, encoding="utf-8-sig")
        top = diagnostics.head(10).to_dict(orient="records") if not diagnostics.empty else []
        result = {
            "code": code,
            "odds_source": odds_source,
            "status": "success",
            "source_seasons": source_seasons,
            "candidate_count": int(len(frame)),
            "diagnostic_rows": int(len(diagnostics)),
            "top": top,
            "output_dir": str(output_dir),
            "market_candidates_csv": str(frame_path),
            "market_bias_csv": str(diagnostics_path),
        }
    except Exception as exc:
        result = {
            "code": code,
            "odds_source": odds_source,
            "status": "failed",
            "error": str(exc),
            "output_dir": str(output_dir),
        }
    (output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_batch_discovery(readiness_path: Path, output_dir: Path, limit: int,
                        offset: int,
                        min_samples: int, min_active_months: int, max_combo_size: int) -> dict[str, Any]:
    readiness = _read_json(readiness_path)
    domains = select_domains(readiness, limit, offset)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [
        scan_domain(domain, min_samples, min_active_months, max_combo_size, output_dir / "domains")
        for domain in domains
    ]
    successful = [row for row in results if row["status"] == "success"]
    with_hits = [row for row in successful if row.get("diagnostic_rows", 0) > 0]
    ranked = sorted(
        with_hits,
        key=lambda row: (
            int(row.get("diagnostic_rows") or 0),
            float((row.get("top") or [{}])[0].get("score") or 0),
            float((row.get("top") or [{}])[0].get("profit") or 0),
        ),
        reverse=True,
    )
    summary = {
        "method": "batch profit domain first-pass discovery",
        "readiness_path": str(readiness_path),
        "domain_offset": offset,
        "selected_domains": [domain["code"] for domain in domains],
        "domain_count": len(domains),
        "successful_domains": len(successful),
        "domains_with_diagnostic_hits": len(with_hits),
        "min_samples": min_samples,
        "min_active_months": min_active_months,
        "max_combo_size": max_combo_size,
        "ranked_domains": [
            {
                "code": row["code"],
                "odds_source": row["odds_source"],
                "diagnostic_rows": row.get("diagnostic_rows", 0),
                "candidate_count": row.get("candidate_count", 0),
                "top": (row.get("top") or [])[:3],
                "output_dir": row.get("output_dir"),
            }
            for row in ranked
        ],
        "results": results,
        "next_step": (
            "Run market_bias_candidate_screen on the top domains with diagnostic hits, then reject any rule "
            "that fails no-lookahead walk-forward and settlement-aware portfolio gates."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch first-pass discovery over search-ready profit data domains.")
    parser.add_argument("--readiness", type=Path, default=Path("reports/profit_data_domain_readiness/summary.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/batch_profit_domain_discovery"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-samples", type=int, default=150)
    parser.add_argument("--min-active-months", type=int, default=18)
    parser.add_argument("--max-combo-size", type=int, default=3)
    args = parser.parse_args()
    summary = run_batch_discovery(
        args.readiness,
        args.output_dir,
        args.limit,
        args.offset,
        args.min_samples,
        args.min_active_months,
        args.max_combo_size,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
