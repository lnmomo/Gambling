from __future__ import annotations

import argparse
import itertools
import json
import math
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

from market_bias_portfolio_simulation import simulate_settlement_portfolio
from rule_exposure_grid_search import _summarize_windows, _window_rows


@dataclass(frozen=True)
class QualityConfig:
    key_columns: tuple[str, ...]
    lookback_months: int
    min_samples: int
    min_roi: float
    min_edge: float
    min_conservative_edge: float
    cold_start: str = "enabled"

    @property
    def config_id(self) -> str:
        key = "_".join(self.key_columns)
        roi = str(self.min_roi).replace("-", "neg").replace(".", "p")
        edge = str(self.min_edge).replace("-", "neg").replace(".", "p")
        conservative = str(self.min_conservative_edge).replace("-", "neg").replace(".", "p")
        return f"{key}_lb{self.lookback_months}_n{self.min_samples}_roi{roi}_edge{edge}_cedge{conservative}_{self.cold_start}"


def _wilson_lower_bound(wins: int, trials: int, z: float = 1.96) -> float:
    if trials <= 0:
        return 0.0
    p_hat = wins / trials
    denom = 1 + z * z / trials
    centre = p_hat + z * z / (2 * trials)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * trials)) / trials)
    return max(0.0, (centre - margin) / denom)


def _history_summary(history: pd.DataFrame, key_columns: tuple[str, ...],
                     key: tuple[str, ...], lookback_months: int) -> dict[str, Any]:
    if history.empty:
        return {"samples": 0, "wins": 0, "roi": 0.0, "edge": 0.0, "conservative_edge": 0.0}
    selected = history.copy()
    for column, value in zip(key_columns, key):
        selected = selected[selected[column].astype(str) == str(value)]
    if selected.empty:
        return {"samples": 0, "wins": 0, "roi": 0.0, "edge": 0.0, "conservative_edge": 0.0}
    months = sorted(selected["month"].astype(str).unique())[-lookback_months:]
    selected = selected[selected["month"].astype(str).isin(months)].copy()
    if selected.empty:
        return {"samples": 0, "wins": 0, "roi": 0.0, "edge": 0.0, "conservative_edge": 0.0}
    wins = int(selected["won_bool"].sum())
    samples = int(len(selected))
    hit_rate = wins / samples
    implied = float((1.0 / selected["odds"].astype(float)).mean())
    staked = float(selected["stake"].sum())
    profit = float(selected["profit"].sum())
    wilson = _wilson_lower_bound(wins, samples)
    return {
        "samples": samples,
        "wins": wins,
        "hit_rate": round(hit_rate, 6),
        "wilson_lower": round(wilson, 6),
        "avg_implied_probability": round(implied, 6),
        "profit": round(profit, 6),
        "roi": profit / staked if staked else 0.0,
        "edge": hit_rate - implied,
        "conservative_edge": wilson - implied,
    }


def _row_key(row: pd.Series, columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row[column]) for column in columns)


def row_passes_quality(history: pd.DataFrame, row: pd.Series,
                       config: QualityConfig) -> tuple[bool, dict[str, Any]]:
    summary = _history_summary(history, config.key_columns, _row_key(row, config.key_columns), config.lookback_months)
    if summary["samples"] < config.min_samples:
        return config.cold_start == "enabled", {**summary, "reason": "cold_start"}
    passed = (
        summary["roi"] >= config.min_roi
        and summary["edge"] >= config.min_edge
        and summary["conservative_edge"] >= config.min_conservative_edge
    )
    return passed, {**summary, "reason": "quality_pass" if passed else "quality_fail"}


def apply_quality_filter(unit_bets: pd.DataFrame, config: QualityConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if unit_bets.empty:
        return unit_bets.copy(), pd.DataFrame()
    frame = unit_bets.copy()
    frame["date"] = frame["date"].astype(str)
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    frame["odds"] = frame["odds"].astype(float)
    frame["stake"] = frame.get("stake", 1.0)
    frame["profit"] = frame["profit"].astype(float)
    frame["won_bool"] = frame["won"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame.sort_values(["month", "date", "rule_label", "odds_source"]).reset_index(drop=True)
    selected_rows = []
    state_rows = []
    history = pd.DataFrame(columns=frame.columns)
    for month in sorted(frame["month"].unique()):
        current = frame[frame["month"] == month].copy()
        for _, row in current.iterrows():
            passed, state = row_passes_quality(history, row, config)
            state_rows.append({
                "month": month,
                "date": row["date"],
                "rule_label": row["rule_label"],
                "odds_source": row.get("odds_source"),
                "key": "|".join(_row_key(row, config.key_columns)),
                "selected": bool(passed),
                **state,
            })
            if passed:
                selected_rows.append(row)
        # All candidate outcomes become historical shadow evidence after the month.
        history = pd.concat([history, current], ignore_index=True)
    selected = pd.DataFrame(selected_rows).drop(columns=["won_bool"], errors="ignore") if selected_rows else pd.DataFrame(columns=frame.columns)
    return selected, pd.DataFrame(state_rows)


def evaluate_quality_filter(unit_bets: pd.DataFrame, config: QualityConfig,
                            first_month: str, last_month: str) -> dict[str, Any]:
    selected, states = apply_quality_filter(unit_bets, config)
    portfolio, _, bets = simulate_settlement_portfolio(selected)
    windows = _window_rows(bets, first_month, last_month)
    overall = portfolio["overall"]
    window_summary = _summarize_windows(windows)
    return {
        "config": asdict(config),
        "config_id": config.config_id,
        "overall": overall,
        "positive_months": int(portfolio.get("positive_months") or 0),
        "negative_months": int(portfolio.get("negative_months") or 0),
        "window_summary": window_summary,
        "windows": windows,
        "states": states,
        "bets": bets,
    }


def run_quality_grid(unit_bets: pd.DataFrame, first_month: str, last_month: str,
                     configs: list[QualityConfig]) -> dict[str, Any]:
    rows = []
    artifacts: dict[str, dict[str, Any]] = {}
    for config in configs:
        result = evaluate_quality_filter(unit_bets, config, first_month, last_month)
        overall = result["overall"]
        window = result["window_summary"]
        row = {
            "config_id": result["config_id"],
            "key_columns": "|".join(config.key_columns),
            "lookback_months": config.lookback_months,
            "min_samples": config.min_samples,
            "min_roi": config.min_roi,
            "min_edge": config.min_edge,
            "min_conservative_edge": config.min_conservative_edge,
            "cold_start": config.cold_start,
            "bets": int(overall["bets"]),
            "profit": float(overall["profit"]),
            "roi_pct": float(overall["roi_pct"]),
            "max_drawdown": float(overall["max_drawdown"]),
            "positive_months": result["positive_months"],
            "negative_months": result["negative_months"],
            **window,
        }
        rows.append(row)
        artifacts[config.config_id] = result
    rows.sort(key=lambda row: (
        row["active_pass_rate"],
        row["passed_windows"],
        row["profit"] > 0,
        row["roi_pct"],
        -row["max_drawdown"],
    ), reverse=True)
    return {
        "method": "per-bet prior price-quality filter grid",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "first_month": first_month,
        "last_month": last_month,
        "grid_size": len(rows),
        "rows": rows,
        "best": rows[0] if rows else None,
        "artifacts": artifacts,
    }


def _parse_key_sets(raw: str) -> list[tuple[str, ...]]:
    return [tuple(part.strip() for part in item.split("|") if part.strip()) for item in raw.split(",") if item.strip()]


def _parse_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter candidate bets by prior per-bucket price-quality.")
    parser.add_argument("--unit-bets", type=Path, default=Path("reports/monthly_rule_activation_i2_sp1_v1/unit_bets.csv"))
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--key-sets", default="rule_label|odds_source,rule_label|odds_source|market_prob_bucket")
    parser.add_argument("--lookbacks", default="6,9")
    parser.add_argument("--min-samples", default="20,40")
    parser.add_argument("--min-rois", default="-0.02,0.0")
    parser.add_argument("--min-edges", default="-0.01,0.0")
    parser.add_argument("--min-conservative-edges", default="-0.05,-0.02")
    parser.add_argument("--cold-start", default="enabled")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/per_bet_price_quality_i2_sp1"))
    args = parser.parse_args()

    unit_bets = pd.read_csv(args.unit_bets)
    configs = [
        QualityConfig(keys, lookback, samples, roi, edge, conservative, args.cold_start)
        for keys, lookback, samples, roi, edge, conservative in itertools.product(
            _parse_key_sets(args.key_sets),
            _parse_ints(args.lookbacks),
            _parse_ints(args.min_samples),
            _parse_floats(args.min_rois),
            _parse_floats(args.min_edges),
            _parse_floats(args.min_conservative_edges),
        )
    ]
    result = run_quality_grid(unit_bets, args.first_month, args.last_month, configs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = result.pop("artifacts")
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["rows"]).to_csv(args.output_dir / "grid.csv", index=False, encoding="utf-8-sig")
    if result["best"]:
        best_id = result["best"]["config_id"]
        best = artifacts[best_id]
        pd.DataFrame(best["windows"]).to_csv(args.output_dir / "best_windows.csv", index=False, encoding="utf-8-sig")
        best["states"].to_csv(args.output_dir / "best_states.csv", index=False, encoding="utf-8-sig")
        best["bets"].to_csv(args.output_dir / "best_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
