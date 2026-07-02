from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _wilson_lower_bound(wins: int, trials: int, z: float = 1.96) -> float:
    if trials <= 0:
        return 0.0
    p_hat = wins / trials
    denom = 1 + z * z / trials
    centre = p_hat + z * z / (2 * trials)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * trials)) / trials)
    return max(0.0, (centre - margin) / denom)


def _summary(group: pd.DataFrame, label: str, min_bets: int) -> dict[str, Any]:
    bets = int(len(group))
    wins = int(group["won_bool"].sum()) if bets else 0
    staked = float(group["stake"].sum()) if bets else 0.0
    profit = float(group["profit"].sum()) if bets else 0.0
    hit_rate = wins / bets if bets else 0.0
    avg_implied_probability = float((1.0 / group["odds"]).mean()) if bets else 0.0
    avg_odds = float(group["odds"].mean()) if bets else 0.0
    wilson_lower = _wilson_lower_bound(wins, bets)
    edge_vs_implied = hit_rate - avg_implied_probability
    conservative_edge = wilson_lower - avg_implied_probability
    roi_pct = profit / staked * 100 if staked else 0.0
    decision_reasons: list[str] = []
    if bets < min_bets:
        decision_reasons.append("bets<minimum")
    if edge_vs_implied <= 0:
        decision_reasons.append("hit_rate<=average_implied_probability")
    if conservative_edge <= 0:
        decision_reasons.append("wilson_lower<=average_implied_probability")
    if roi_pct <= 0:
        decision_reasons.append("roi<=0")
    decision = "CALIBRATED_EDGE_CONFIRMED" if not decision_reasons else (
        "POSITIVE_EDGE_BUT_NOT_CONSERVATIVE" if edge_vs_implied > 0 and roi_pct > 0 else "NO_CALIBRATED_EDGE"
    )
    return {
        "label": label,
        "bets": bets,
        "wins": wins,
        "hit_rate": round(hit_rate, 4),
        "wilson_hit_rate_lower_95": round(wilson_lower, 4),
        "avg_odds": round(avg_odds, 4),
        "avg_implied_probability": round(avg_implied_probability, 4),
        "edge_vs_implied_probability": round(edge_vs_implied, 4),
        "conservative_edge_vs_implied": round(conservative_edge, 4),
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(roi_pct, 2),
        "decision": decision,
        "decision_reasons": decision_reasons,
    }


def _group_summaries(frame: pd.DataFrame, column: str, min_bets: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if column not in frame.columns:
        return rows
    for value, group in frame.groupby(column):
        rows.append(_summary(group, str(value), min_bets))
    rows.sort(key=lambda item: (item["decision"] == "CALIBRATED_EDGE_CONFIRMED", item["bets"]), reverse=True)
    return rows


def audit_edge_calibration(path: Path | str, min_bets: int = 100) -> dict[str, Any]:
    bets_path = Path(path)
    frame = pd.read_csv(bets_path)
    if frame.empty:
        return {
            "method": "strategy edge calibration against selected-odds implied probability",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bets_path": str(bets_path),
            "config": {"min_bets": min_bets},
            "overall": _summary(frame.assign(won_bool=[]), "overall", min_bets),
            "by_rule": [],
            "by_season": [],
            "by_odds_band": [],
        }
    frame["won_bool"] = frame["won"].map(_as_bool)
    frame["odds"] = pd.to_numeric(frame["odds"], errors="coerce")
    frame["stake"] = pd.to_numeric(frame["stake"], errors="coerce")
    frame["profit"] = pd.to_numeric(frame["profit"], errors="coerce")
    frame = frame.dropna(subset=["odds", "stake", "profit"])
    frame = frame[frame["odds"] > 1].copy()
    frame["odds_band"] = pd.cut(
        frame["odds"],
        bins=[1.0, 1.8, 2.2, 2.8, 3.3, 3.5, 4.0, 100.0],
        right=False,
        labels=["[1.0,1.8)", "[1.8,2.2)", "[2.2,2.8)", "[2.8,3.3)", "[3.3,3.5)", "[3.5,4.0)", "[4.0,+)"],
    ).astype(str)
    overall = _summary(frame, "overall", min_bets)
    return {
        "method": "strategy edge calibration against selected-odds implied probability",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bets_path": str(bets_path),
        "config": {
            "min_bets": min_bets,
            "hit_rate_interval": "Wilson 95% lower bound",
            "selected_side_implied_probability": "mean(1 / selected_decimal_odds)",
        },
        "overall": overall,
        "by_rule": _group_summaries(frame, "rule_label", min_bets),
        "by_season": _group_summaries(frame, "season", max(20, min_bets // 3)),
        "by_odds_band": _group_summaries(frame, "odds_band", max(20, min_bets // 3)),
        "decision": overall["decision"],
        "decision_reasons": overall["decision_reasons"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit whether a bets.csv beats selected-side implied probabilities.")
    parser.add_argument("--bets", required=True, type=Path)
    parser.add_argument("--min-bets", type=int, default=100)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    report = audit_edge_calibration(args.bets, args.min_bets)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(report["by_rule"]).to_csv(args.output_dir / "by_rule.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report["by_season"]).to_csv(args.output_dir / "by_season.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report["by_odds_band"]).to_csv(args.output_dir / "by_odds_band.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
