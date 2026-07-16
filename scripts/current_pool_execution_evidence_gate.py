from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_PRICE_SOURCES = ("AVG_CLOSE", "PS_CLOSE")


@dataclass(frozen=True)
class EvidenceThresholds:
    min_bets: int = 200
    min_active_windows: int = 5
    min_active_pass_rate: float = 0.5
    min_roi_pct: float = 3.0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_source(
    source: str,
    rolling: dict[str, Any],
    statistical: dict[str, Any],
    calibration: dict[str, Any],
    thresholds: EvidenceThresholds,
) -> dict[str, Any]:
    summary = rolling.get("summary") or {}
    reasons: list[str] = []
    if rolling.get("selection_uses_validation_data") is not False:
        reasons.append("validation_selection_is_not_proven_no_lookahead")
    if rolling.get("validation_windows_overlap") is not False:
        reasons.append("validation_windows_overlap")
    if int(summary.get("bets") or 0) < thresholds.min_bets:
        reasons.append("bets<minimum")
    if int(summary.get("active_window_count") or 0) < thresholds.min_active_windows:
        reasons.append("active_windows<minimum")
    if float(summary.get("active_pass_rate") or 0) < thresholds.min_active_pass_rate:
        reasons.append("active_pass_rate<minimum")
    if float(summary.get("profit") or 0) <= 0:
        reasons.append("profit<=0")
    if float(summary.get("roi_pct") or 0) < thresholds.min_roi_pct:
        reasons.append("roi<minimum")
    if statistical.get("decision") != "STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE":
        reasons.append("statistical_audit_not_supported")
    if calibration.get("decision") != "CALIBRATED_EDGE_CONFIRMED":
        reasons.append("calibrated_edge_not_confirmed")
    return {
        "source": source,
        "passed": not reasons,
        "reasons": reasons,
        "walk_forward": {
            key: summary.get(key)
            for key in (
                "bets", "profit", "roi_pct", "active_window_count",
                "active_passed_windows", "active_pass_rate",
            )
        },
        "statistical_decision": statistical.get("decision"),
        "bootstrap_roi_p05": ((statistical.get("bootstrap") or {}).get("roi_ci_pct") or {}).get("p05"),
        "calibration_decision": calibration.get("decision"),
        "conservative_edge": (calibration.get("overall") or {}).get("conservative_edge_vs_implied"),
    }


def evaluate_domain(
    league: str,
    source_evidence: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    official_quality: dict[str, Any],
    thresholds: EvidenceThresholds = EvidenceThresholds(),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    for source in REQUIRED_PRICE_SOURCES:
        evidence = source_evidence.get(source)
        if evidence is None:
            missing_sources.append(source)
            continue
        rows.append(evaluate_source(source, *evidence, thresholds))
    historical_passed = not missing_sources and len(rows) == len(REQUIRED_PRICE_SOURCES) and all(
        row["passed"] for row in rows
    )
    official_ready = (
        official_quality.get("decision") == "EVIDENCE_READY"
        and official_quality.get("research_usable") is True
    )
    if not historical_passed:
        decision = "REJECTED_HISTORICAL_EVIDENCE"
    elif not official_ready:
        decision = "HISTORICALLY_SUPPORTED_AWAIT_OFFICIAL_SP"
    else:
        decision = "OFFICIAL_SP_SHADOW_CANDIDATE"
    return {
        "league": league,
        "decision": decision,
        "historical_passed": historical_passed,
        "official_sp_evidence_ready": official_ready,
        "missing_sources": missing_sources,
        "sources": rows,
    }


def build_report(root: Path, official_quality_path: Path, thresholds: EvidenceThresholds) -> dict[str, Any]:
    official_quality = _read_json(official_quality_path)
    rolling_root = root / "rolling"
    audit_root = root / "audit"
    leagues = sorted({path.name.rsplit("_", 2)[0].upper() for path in rolling_root.glob("*_avg_close")})
    domains: list[dict[str, Any]] = []
    for league in leagues:
        source_evidence: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
        for source in REQUIRED_PRICE_SOURCES:
            stem = f"{league.lower()}_{source.lower()}"
            rolling_path = rolling_root / stem / "summary.json"
            statistical_path = audit_root / f"{stem}_statistical" / "summary.json"
            calibration_path = audit_root / f"{stem}_calibration" / "summary.json"
            if all(path.exists() for path in (rolling_path, statistical_path, calibration_path)):
                source_evidence[source] = (
                    _read_json(rolling_path),
                    _read_json(statistical_path),
                    _read_json(calibration_path),
                )
        domains.append(evaluate_domain(league, source_evidence, official_quality, thresholds))
    promoted = [row["league"] for row in domains if row["decision"] == "OFFICIAL_SP_SHADOW_CANDIDATE"]
    awaiting = [
        row["league"] for row in domains
        if row["decision"] == "HISTORICALLY_SUPPORTED_AWAIT_OFFICIAL_SP"
    ]
    return {
        "method": "current-pool representative-price multi-source evidence gate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "required_price_sources": list(REQUIRED_PRICE_SOURCES),
        "excluded_promotion_sources": ["MAX_CLOSE"],
        "historical_price_semantics": (
            "AVG_CLOSE and PS_CLOSE are representative historical market prices, not proof that the official SP "
            "was executable at decision time."
        ),
        "thresholds": asdict(thresholds),
        "official_sp_quality_decision": official_quality.get("decision"),
        "domain_count": len(domains),
        "promoted_domains": promoted,
        "awaiting_official_sp_domains": awaiting,
        "domains": domains,
        "guardrail": (
            "A domain must pass independent AVG_CLOSE and PS_CLOSE no-lookahead, statistical, and calibration "
            "checks before official-SP shadow validation. MAX_CLOSE is never promotion evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gate current official-pool research using representative historical and official-SP evidence."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--official-quality",
        type=Path,
        default=Path("reports/official_sp_evidence_quality/summary.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.root, args.official_quality, EvidenceThresholds())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
