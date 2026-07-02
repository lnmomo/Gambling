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
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402


I2_DRAW_RULE = "league|outcome|odds_bucket=I2|draw|[2.8,3.5)"
SP1_HOME_RULE = "league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]"
DEFAULT_RULES = (I2_DRAW_RULE, SP1_HOME_RULE)


@dataclass(frozen=True)
class ActivationConfig:
    lookback_months: int
    min_history_bets: int
    min_history_roi: float
    min_positive_month_edge: int
    cold_start: str = "enabled"

    @property
    def config_id(self) -> str:
        roi = str(self.min_history_roi).replace("-", "neg").replace(".", "p")
        return (
            f"lb{self.lookback_months}_bets{self.min_history_bets}_"
            f"roi{roi}_edge{self.min_positive_month_edge}_{self.cold_start}"
        )


def _parse_rules(raw_rules: tuple[str, ...]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    parsed = []
    for raw in raw_rules:
        columns_raw, key_raw = raw.split("=", 1)
        parsed.append((_parse_rule(columns_raw), _parse_rule(key_raw)))
    return parsed


def build_unit_bets_for_rules(
    *,
    seasons: tuple[str, ...],
    first_month: str,
    last_month: str,
    odds_sources: tuple[str, ...],
    raw_rules: tuple[str, ...] = DEFAULT_RULES,
    lookback_months: int = 12,
    min_active_months: int = 6,
    min_bets: int = 50,
    min_roi: float = 0.02,
    max_rules: int = 3,
    daily_limit: float = 100.0,
    candidate_id: str = "market-bias-i2-draw-plus-sp1-home-v1",
) -> pd.DataFrame:
    frames = []
    rules = _parse_rules(raw_rules)
    for source in odds_sources:
        frame = build_market_frame(seasons, source)
        _, _, unit_bets = run_walk_forward_frame(
            frame,
            seasons,
            first_month,
            last_month,
            rules,
            lookback_months,
            min_active_months,
            min_bets,
            min_roi,
            max_rules,
            daily_limit,
            source,
        )
        if not unit_bets.empty:
            frames.append(unit_bets.assign(candidate_id=candidate_id, odds_source=source))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _monthly_rule_summary(history: pd.DataFrame, rule_label: str, lookback_months: int) -> dict[str, Any]:
    if history.empty:
        return {"bets": 0, "profit": 0.0, "staked": 0.0, "roi": 0.0, "positive_months": 0, "negative_months": 0}
    rule_history = history[history["rule_label"].astype(str) == rule_label].copy()
    if rule_history.empty:
        return {"bets": 0, "profit": 0.0, "staked": 0.0, "roi": 0.0, "positive_months": 0, "negative_months": 0}
    months = sorted(rule_history["month"].unique())[-lookback_months:]
    recent = rule_history[rule_history["month"].isin(months)]
    monthly_profit = recent.groupby("month")["profit"].sum()
    staked = float(recent["stake"].sum()) if "stake" in recent else float(len(recent))
    profit = float(recent["profit"].sum())
    return {
        "bets": int(len(recent)),
        "profit": round(profit, 2),
        "staked": round(staked, 2),
        "roi": profit / staked if staked else 0.0,
        "positive_months": int((monthly_profit > 0).sum()),
        "negative_months": int((monthly_profit < 0).sum()),
    }


def rule_enabled(history: pd.DataFrame, rule_label: str, config: ActivationConfig) -> tuple[bool, dict[str, Any]]:
    summary = _monthly_rule_summary(history, rule_label, config.lookback_months)
    if summary["bets"] < config.min_history_bets:
        return config.cold_start == "enabled", {**summary, "reason": "cold_start"}
    positive_edge = summary["positive_months"] - summary["negative_months"]
    enabled = (
        summary["profit"] > 0
        and summary["roi"] >= config.min_history_roi
        and positive_edge >= config.min_positive_month_edge
    )
    reason = "enabled" if enabled else "disabled_by_trailing_state"
    return enabled, {**summary, "positive_month_edge": positive_edge, "reason": reason}


def apply_monthly_activation(unit_bets: pd.DataFrame, config: ActivationConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if unit_bets.empty:
        return unit_bets.copy(), pd.DataFrame()
    frame = unit_bets.copy()
    frame["date"] = frame["date"].astype(str)
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    frame["stake"] = 1.0
    frame["profit"] = frame["unit_profit"].astype(float) if "unit_profit" in frame else frame["profit"].astype(float)
    frame = frame.sort_values(["month", "date", "rule_label"]).reset_index(drop=True)
    selected_frames = []
    state_rows = []
    history = pd.DataFrame(columns=frame.columns)
    for month in sorted(frame["month"].unique()):
        current = frame[frame["month"] == month].copy()
        allowed_labels = set()
        for label in sorted(current["rule_label"].astype(str).unique()):
            enabled, state = rule_enabled(history, label, config)
            state_rows.append({
                "month": month,
                "rule_label": label,
                "enabled": enabled,
                **state,
            })
            if enabled:
                allowed_labels.add(label)
        selected = current[current["rule_label"].astype(str).isin(allowed_labels)].copy()
        if not selected.empty:
            selected_frames.append(selected)
        # Shadow-observed outcomes become available after the month, even for disabled rules.
        history = pd.concat([history, current], ignore_index=True)
    selected_bets = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame(columns=frame.columns)
    return selected_bets, pd.DataFrame(state_rows)


def evaluate_activation(unit_bets: pd.DataFrame, config: ActivationConfig,
                        first_month: str, last_month: str) -> dict[str, Any]:
    selected, states = apply_monthly_activation(unit_bets, config)
    portfolio, _, bets = simulate_settlement_portfolio(selected)
    windows = _window_rows(bets, first_month, last_month)
    window_summary = _summarize_windows(windows)
    overall = portfolio["overall"]
    profit = float(overall["profit"])
    staked = float(overall["total_staked"])
    return {
        "config": asdict(config),
        "config_id": config.config_id,
        "overall": overall,
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        "positive_months": int(portfolio.get("positive_months") or 0),
        "negative_months": int(portfolio.get("negative_months") or 0),
        "window_summary": window_summary,
        "windows": windows,
        "states": states,
        "bets": bets,
    }


def run_activation_grid(
    *,
    unit_bets: pd.DataFrame,
    first_month: str,
    last_month: str,
    configs: list[ActivationConfig],
) -> dict[str, Any]:
    rows = []
    artifacts: dict[str, dict[str, Any]] = {}
    for config in configs:
        result = evaluate_activation(unit_bets, config, first_month, last_month)
        overall = result["overall"]
        window = result["window_summary"]
        row = {
            "config_id": result["config_id"],
            **result["config"],
            "bets": int(overall["bets"]),
            "profit": float(overall["profit"]),
            "roi_pct": float(overall["roi_pct"]),
            "max_drawdown": float(overall["max_drawdown"]),
            "positive_months": result["positive_months"],
            "negative_months": result["negative_months"],
            **window,
        }
        rows.append(row)
        artifacts[result["config_id"]] = result
    rows.sort(key=lambda row: (
        row["active_pass_rate"],
        row["passed_windows"],
        row["profit"] > 0,
        row["roi_pct"],
        -row["max_drawdown"],
    ), reverse=True)
    return {
        "method": "monthly prior-state rule activation grid",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "first_month": first_month,
        "last_month": last_month,
        "grid_size": len(rows),
        "rows": rows,
        "best": rows[0] if rows else None,
        "artifacts": artifacts,
    }


def _parse_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Test monthly prior-state activation for I2 draw + SP1 home.")
    parser.add_argument("--unit-bets", type=Path)
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--odds-sources", default="AVG_OPEN,AVG_CLOSE")
    parser.add_argument("--lookback-months", default="3,6,9")
    parser.add_argument("--min-history-bets", default="20,40,60")
    parser.add_argument("--min-history-roi", default="-0.02,0.0,0.02")
    parser.add_argument("--min-positive-month-edge", default="0,1")
    parser.add_argument("--cold-start", default="enabled")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/monthly_rule_activation_i2_sp1"))
    args = parser.parse_args()

    if args.unit_bets:
        unit_bets = pd.read_csv(args.unit_bets)
    else:
        unit_bets = build_unit_bets_for_rules(
            seasons=tuple(item.strip() for item in args.seasons.split(",") if item.strip()),
            first_month=args.first_month,
            last_month=args.last_month,
            odds_sources=tuple(item.strip() for item in args.odds_sources.split(",") if item.strip()),
        )
    configs = [
        ActivationConfig(lookback, min_bets, min_roi, edge, args.cold_start)
        for lookback, min_bets, min_roi, edge in itertools.product(
            _parse_ints(args.lookback_months),
            _parse_ints(args.min_history_bets),
            _parse_floats(args.min_history_roi),
            _parse_ints(args.min_positive_month_edge),
        )
    ]
    result = run_activation_grid(
        unit_bets=unit_bets,
        first_month=args.first_month,
        last_month=args.last_month,
        configs=configs,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = result.pop("artifacts")
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["rows"]).to_csv(args.output_dir / "grid.csv", index=False, encoding="utf-8-sig")
    unit_bets.to_csv(args.output_dir / "unit_bets.csv", index=False, encoding="utf-8-sig")
    if result["best"]:
        best_id = result["best"]["config_id"]
        best = artifacts[best_id]
        pd.DataFrame(best["windows"]).to_csv(args.output_dir / "best_windows.csv", index=False, encoding="utf-8-sig")
        best["states"].to_csv(args.output_dir / "best_states.csv", index=False, encoding="utf-8-sig")
        best["bets"].to_csv(args.output_dir / "best_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
