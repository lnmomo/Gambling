from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from feature_enriched_candidate_filter import assess_feature_filter_row, season_summary_from_bets  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402
from rule_exposure_grid_search import _summarize_windows, _window_rows  # noqa: E402


@dataclass(frozen=True)
class RollingQualityConfig:
    train_months: int
    bucket_key: tuple[str, ...]
    min_bucket_samples: int
    min_bucket_profit: float
    min_bucket_roi: float
    min_bucket_positive_months: int
    min_predicted_ev: float
    max_bets_per_day: int = 1

    @property
    def label(self) -> str:
        key = "_".join(self.bucket_key)
        ev = str(self.min_predicted_ev).replace("-", "neg").replace(".", "p")
        roi = str(self.min_bucket_roi).replace(".", "p")
        return (
            f"train{self.train_months}_{key}_n{self.min_bucket_samples}"
            f"_profit{self.min_bucket_profit:g}_roi{roi}_pm{self.min_bucket_positive_months}_ev{ev}"
        )


def add_quality_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["abs_form_points_bucket"] = pd.cut(
        output["abs_form_points_diff"].astype(float),
        bins=[-0.001, 0.6, 1.2, 2.0, 99.0],
        labels=["form_gap_tiny", "form_gap_mid", "form_gap_large", "form_gap_extreme"],
    ).astype(str)
    output["season_points_delta_bucket"] = pd.cut(
        output["abs_season_points_per_match_delta"].astype(float),
        bins=[-0.001, 0.25, 0.55, 0.9, 99.0],
        labels=["season_gap_tiny", "season_gap_mid", "season_gap_large", "season_gap_extreme"],
    ).astype(str)
    output["predicted_ev_bucket"] = pd.cut(
        output["predicted_ev"].astype(float),
        bins=[-99.0, 0.08, 0.12, 0.16, 99.0],
        labels=["ev_low", "ev_mid", "ev_high", "ev_very_high"],
    ).astype(str)
    output["odds_quality_bucket"] = pd.cut(
        output["odds"].astype(float),
        bins=[2.79, 3.0, 3.15, 3.3, 3.51],
        labels=["odds_2p8_3p0", "odds_3p0_3p15", "odds_3p15_3p3", "odds_3p3_3p5"],
    ).astype(str)
    output["lambda_total_bucket"] = pd.cut(
        output["lambda_total"].astype(float),
        bins=[0.0, 2.4, 2.6, 99.0],
        labels=["goals_low_mid", "goals_mid_high", "goals_high"],
    ).astype(str)
    output["lambda_diff_bucket"] = pd.cut(
        output["lambda_diff"].astype(float),
        bins=[-0.001, 0.15, 0.30, 0.50, 99.0],
        labels=["lambda_close", "lambda_mid", "lambda_wide", "lambda_extreme"],
    ).astype(str)
    output["quality_month"] = pd.to_datetime(output["date"]).dt.to_period("M").astype(str)
    return output


def training_window(frame: pd.DataFrame, period: pd.Period, train_months: int) -> pd.DataFrame:
    start = period.start_time.normalize() - pd.DateOffset(months=train_months)
    end = period.start_time.normalize()
    return frame[(frame["bet_date"] >= start) & (frame["bet_date"] < end)].copy()


def select_allowed_buckets(train: pd.DataFrame, config: RollingQualityConfig) -> set[tuple[str, ...]]:
    if train.empty:
        return set()
    rows = []
    for key, group in train.groupby(list(config.bucket_key), dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        monthly = group.groupby("quality_month")["unit_profit"].sum()
        samples = int(len(group))
        profit = float(group["unit_profit"].sum())
        roi = profit / samples if samples else 0.0
        rows.append({
            "key": tuple(str(item) for item in key),
            "samples": samples,
            "profit": profit,
            "roi": roi,
            "positive_months": int((monthly > 0).sum()),
        })
    return {
        row["key"]
        for row in rows
        if row["samples"] >= config.min_bucket_samples
        and row["profit"] >= config.min_bucket_profit
        and row["roi"] >= config.min_bucket_roi
        and row["positive_months"] >= config.min_bucket_positive_months
    }


def rolling_quality_filter(
    candidates: pd.DataFrame,
    config: RollingQualityConfig,
    first_month: str,
    last_month: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = add_quality_buckets(candidates)
    frame["bet_date"] = pd.to_datetime(frame["date"])
    selected_parts: list[pd.DataFrame] = []
    month_reports: list[dict[str, Any]] = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        test = frame[frame["quality_month"] == str(period)].copy()
        if test.empty:
            month_reports.append({"month": str(period), "decision": "ABSTAIN", "reason": "no_candidates"})
            continue
        train = training_window(frame, period, config.train_months)
        allowed = select_allowed_buckets(train, config)
        if not allowed:
            month_reports.append({
                "month": str(period),
                "decision": "ABSTAIN",
                "reason": "no_prior_profitable_bucket",
                "prior_candidates": int(len(train)),
                "candidate_count": int(len(test)),
            })
            continue
        test["_bucket_key"] = [tuple(str(row[column]) for column in config.bucket_key) for _, row in test.iterrows()]
        selected = test[
            test["_bucket_key"].isin(allowed)
            & (test["predicted_ev"].astype(float) >= config.min_predicted_ev)
        ].copy()
        if config.max_bets_per_day > 0 and not selected.empty:
            selected = (
                selected.sort_values(["date", "predicted_ev"], ascending=[True, False])
                .groupby("date", as_index=False, group_keys=False)
                .head(config.max_bets_per_day)
            )
        selected["rule_label"] = config.label + "|" + selected["rule_label"].astype(str)
        selected = selected.drop(columns=["_bucket_key"], errors="ignore")
        selected_parts.append(selected)
        month_reports.append({
            "month": str(period),
            "decision": "INVEST" if not selected.empty else "ABSTAIN",
            "reason": None if not selected.empty else "no_candidate_in_allowed_bucket",
            "prior_candidates": int(len(train)),
            "candidate_count": int(len(test)),
            "allowed_buckets": int(len(allowed)),
            "selected": int(len(selected)),
        })
    selected_all = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
    return {"config": config.__dict__, "months": month_reports, "selected_candidates": int(len(selected_all))}, selected_all


def _config_grid(fast: bool = False) -> list[RollingQualityConfig]:
    bucket_keys = (
        ("abs_form_points_bucket",),
        ("season_points_delta_bucket",),
        ("abs_form_points_bucket", "season_points_delta_bucket"),
        ("abs_form_points_bucket", "predicted_ev_bucket"),
        ("lambda_total_bucket", "lambda_diff_bucket"),
    )
    if fast:
        return [
            RollingQualityConfig(36, ("abs_form_points_bucket",), 20, 1.0, 0.05, 3, 0.02),
            RollingQualityConfig(36, ("abs_form_points_bucket", "season_points_delta_bucket"), 12, 1.0, 0.05, 3, 0.02),
            RollingQualityConfig(48, ("abs_form_points_bucket", "predicted_ev_bucket"), 10, 1.0, 0.05, 3, 0.02),
        ]
    return [
        RollingQualityConfig(train, key, samples, profit, roi, pos_months, ev)
        for train, key, samples, profit, roi, pos_months, ev in itertools.product(
            (24, 36, 48),
            bucket_keys,
            (8, 12, 20),
            (0.0, 1.0),
            (0.0, 0.05, 0.10),
            (2, 3),
            (0.02, 0.08),
        )
    ]


def evaluate_configs(candidates: pd.DataFrame, configs: list[RollingQualityConfig],
                     first_month: str, last_month: str) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    results = []
    artifacts: dict[str, pd.DataFrame] = {}
    for config in configs:
        wf_summary, selected = rolling_quality_filter(candidates, config, first_month, last_month)
        portfolio, daily, bets = simulate_settlement_portfolio(selected, daily_limit=100.0, max_single_stake=10.0)
        windows = _window_rows(bets, first_month, last_month)
        window_summary = _summarize_windows(windows)
        season_rows = season_summary_from_bets(bets)
        latest = season_rows[-1] if season_rows else {}
        row = {
            "label": config.label,
            "selected_candidates": int(len(selected)),
            "bets": int(portfolio["overall"]["bets"]),
            "profit": float(portfolio["overall"]["profit"]),
            "roi_pct": float(portfolio["overall"]["roi_pct"]),
            "max_drawdown": float(portfolio["overall"]["max_drawdown"]),
            "positive_months": int(portfolio.get("positive_months") or 0),
            "negative_months": int(portfolio.get("negative_months") or 0),
            "positive_seasons": sum(float(item["profit"]) > 0 for item in season_rows),
            "negative_seasons": sum(float(item["profit"]) < 0 for item in season_rows),
            "latest_season": latest.get("season"),
            "latest_season_bets": int(latest.get("bets") or 0),
            "latest_season_profit": float(latest.get("profit") or 0.0),
            **window_summary,
        }
        verdict, reasons = assess_feature_filter_row(row, min_bets=120, min_active_pass_rate=0.60)
        row["decision"] = verdict
        row["decision_reasons"] = reasons
        results.append(row)
        artifacts[config.label] = {
            "selected": selected,
            "daily": daily,
            "bets": bets,
            "windows": pd.DataFrame(windows),
            "month_reports": pd.DataFrame(wf_summary["months"]),
        }
    ranked = sorted(
        results,
        key=lambda row: (
            row["decision"] == "SHADOW_READY_RESEARCH_CANDIDATE",
            row["active_pass_rate"],
            row["profit"],
            -row["max_drawdown"],
            row["bets"],
        ),
        reverse=True,
    )
    return {
        "method": "rolling no-leak candidate quality bucket filter",
        "first_month": first_month,
        "last_month": last_month,
        "results": ranked,
        "top": ranked[:20],
        "best_label": ranked[0]["label"] if ranked else None,
        "guardrail": "Research-only. Bucket filters are selected from prior selected-candidate outcomes only; any passing result still needs cross-source and official-SP prospective validation.",
    }, artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--first-month", default="2016-01")
    parser.add_argument("--last-month", default="2026-06")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rolling_candidate_quality_filter"))
    args = parser.parse_args()
    candidates = pd.read_csv(args.input)
    report, artifacts = evaluate_configs(candidates, _config_grid(fast=args.fast), args.first_month, args.last_month)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report["results"]).to_csv(args.output_dir / "grid_results.csv", index=False, encoding="utf-8-sig")
    if report["best_label"]:
        for name, frame in artifacts[report["best_label"]].items():
            frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
