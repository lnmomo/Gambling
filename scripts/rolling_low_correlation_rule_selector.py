from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import pandas as pd

from low_correlation_rule_combo_search import _combo_bets, _evaluate_windows, _max_pairwise_correlation
from market_bias_diagnostics import FEATURE_COLUMNS
from market_bias_walk_forward import _parse_rule


def _feature_combinations(max_combo_size: int) -> list[tuple[str, ...]]:
    columns: list[tuple[str, ...]] = []
    for size in range(1, max_combo_size + 1):
        columns.extend(itertools.combinations(FEATURE_COLUMNS, size))
    return columns


def _rule_label(columns: tuple[str, ...], key: tuple[Any, ...]) -> str:
    return f"{'|'.join(columns)}={'|'.join(str(item) for item in key)}"


def _load_market_candidates(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in paths]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    frame["stake"] = 1.0
    frame["profit"] = frame["unit_profit"].astype(float)
    return frame


def _matches_rule(frame: pd.DataFrame, rule_key: str) -> pd.Series:
    odds_source, rule = rule_key.split("::", 1)
    columns_raw, key_raw = rule.split("=", 1)
    columns = _parse_rule(columns_raw)
    key = _parse_rule(key_raw)
    mask = frame["odds_source"].astype(str).eq(odds_source)
    for column, value in zip(columns, key):
        mask &= frame[column].astype(str).eq(str(value))
    return mask


def _materialize_rule_bets(frame: pd.DataFrame, rule_keys: list[str]) -> pd.DataFrame:
    frames = []
    for rule_key in rule_keys:
        selected = frame[_matches_rule(frame, rule_key)].copy()
        if selected.empty:
            continue
        selected["rule_key"] = rule_key
        selected["rule_label"] = rule_key.split("::", 1)[1]
        selected["candidate_id"] = "rolling-low-correlation-selector"
        frames.append(selected[[
            "date",
            "league",
            "home_team",
            "away_team",
            "outcome",
            "actual_result",
            "odds",
            "odds_bucket",
            "market_prob_bucket",
            "favorite_relation",
            "stake",
            "won",
            "profit",
            "rule_label",
            "month",
            "candidate_id",
            "odds_source",
            "rule_key",
        ]])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _discover_rules(
    train: pd.DataFrame,
    *,
    max_feature_combo_size: int,
    require_outcome: bool = True,
    require_price_bucket: bool = True,
    min_rule_bets: int,
    min_rule_active_months: int,
    min_rule_roi_pct: float,
    require_latest_non_negative: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for odds_source, source_frame in train.groupby("odds_source"):
        for columns in _feature_combinations(max_feature_combo_size):
            column_set = set(columns)
            if "league" not in column_set:
                continue
            if require_outcome and "outcome" not in column_set:
                continue
            if require_price_bucket and not ({"odds_bucket", "market_prob_bucket"} & column_set):
                continue
            for key, group in source_frame.groupby(list(columns), dropna=False):
                if not isinstance(key, tuple):
                    key = (key,)
                bets = int(len(group))
                active_months = int(group["month"].nunique())
                if bets < min_rule_bets or active_months < min_rule_active_months:
                    continue
                staked = float(group["stake"].sum())
                profit = float(group["profit"].sum())
                roi_pct = profit / staked * 100 if staked else 0.0
                months = group.groupby("month")["profit"].sum()
                positive_months = int((months > 0).sum())
                negative_months = int((months < 0).sum())
                latest_month = str(group["month"].max())
                latest_profit = float(group[group["month"] == latest_month]["profit"].sum())
                if profit <= 0 or roi_pct < min_rule_roi_pct or positive_months <= negative_months:
                    continue
                if require_latest_non_negative and latest_profit < 0:
                    continue
                rule = _rule_label(columns, key)
                rows.append({
                    "rule_key": f"{odds_source}::{rule}",
                    "odds_source": str(odds_source),
                    "rule_label": rule,
                    "bets": bets,
                    "profit": round(profit, 2),
                    "roi_pct": round(roi_pct, 2),
                    "active_months": active_months,
                    "positive_months": positive_months,
                    "negative_months": negative_months,
                    "latest_month": latest_month,
                    "latest_profit": round(latest_profit, 2),
                    "score": round((positive_months - negative_months) * 2 + roi_pct + profit / max(bets, 1), 4),
                })
    rows.sort(key=lambda row: (row["score"], row["roi_pct"], row["profit"], row["bets"]), reverse=True)
    return rows


def _profit_matrix(frame: pd.DataFrame, rule_keys: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=rule_keys)
    matrix = frame.pivot_table(index="month", columns="rule_key", values="profit", aggfunc="sum", fill_value=0.0)
    return matrix.reindex(columns=rule_keys, fill_value=0.0)


def _choose_combo(
    train_rule_bets: pd.DataFrame,
    candidate_rules: list[dict[str, Any]],
    *,
    combo_size: int,
    max_rules: int,
    max_pairwise_corr: float,
    train_validation_months: int,
    train_step_months: int,
    min_train_pass_rate: float,
    min_window_bets: int,
    min_window_roi_pct: float,
    min_positive_month_edge: int,
    max_drawdown_to_profit: float,
) -> dict[str, Any] | None:
    rule_keys = [row["rule_key"] for row in candidate_rules[:max_rules]]
    if len(rule_keys) < combo_size:
        return None
    matrix = _profit_matrix(train_rule_bets, rule_keys)
    by_key = {row["rule_key"]: row for row in candidate_rules}
    choices: list[dict[str, Any]] = []
    for combo in itertools.combinations(rule_keys, combo_size):
        corr = _max_pairwise_correlation(matrix, combo)
        if corr > max_pairwise_corr:
            continue
        train_bets = _combo_bets(train_rule_bets[train_rule_bets["rule_key"].isin(combo)].copy(), combo)
        if train_bets.empty:
            continue
        staked = float(train_bets["stake"].sum())
        profit = float(train_bets["profit"].sum())
        roi_pct = profit / staked * 100 if staked else 0.0
        month_profit = train_bets.groupby("month")["profit"].sum()
        train_months = sorted(train_bets["month"].astype(str).unique())
        train_windows = _evaluate_windows(
            train_bets,
            first_month=train_months[0],
            last_month=train_months[-1],
            window_months=train_validation_months,
            step_months=train_step_months,
            min_window_bets=min_window_bets,
            min_window_roi_pct=min_window_roi_pct,
            min_positive_month_edge=min_positive_month_edge,
            max_drawdown_to_profit=max_drawdown_to_profit,
        )
        active_train_windows = [row for row in train_windows if row["bets"] > 0]
        train_active_pass_rate = (
            sum(row["passes_window"] for row in active_train_windows) / len(active_train_windows)
            if active_train_windows else 0.0
        )
        if train_active_pass_rate < min_train_pass_rate:
            continue
        choices.append({
            "rules": list(combo),
            "max_pairwise_monthly_profit_corr": round(corr, 4),
            "train_bets": int(len(train_bets)),
            "train_profit": round(profit, 2),
            "train_roi_pct": round(roi_pct, 2),
            "train_positive_months": int((month_profit > 0).sum()),
            "train_negative_months": int((month_profit < 0).sum()),
            "train_window_count": len(train_windows),
            "train_active_window_count": len(active_train_windows),
            "train_active_passed_windows": int(sum(row["passes_window"] for row in active_train_windows)),
            "train_active_pass_rate": round(train_active_pass_rate, 4),
            "rule_summaries": [by_key[key] for key in combo],
        })
    choices.sort(key=lambda row: (
        row["train_active_pass_rate"],
        row["train_active_passed_windows"],
        row["train_positive_months"] - row["train_negative_months"],
        row["train_roi_pct"],
        row["train_profit"],
        -row["max_pairwise_monthly_profit_corr"],
        row["train_bets"],
    ), reverse=True)
    return choices[0] if choices else None


def _summarize_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in rows if row["bets"] > 0]
    staked = sum(float(row["staked"]) for row in rows)
    profit = sum(float(row["profit"]) for row in rows)
    return {
        "window_count": len(rows),
        "passed_windows": int(sum(row["passes_window"] for row in rows)),
        "active_window_count": len(active),
        "active_passed_windows": int(sum(row["passes_window"] for row in active)),
        "active_pass_rate": round(sum(row["passes_window"] for row in active) / len(active), 4) if active else 0.0,
        "bets": int(sum(row["bets"] for row in rows)),
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
    }


def run_rolling_selector(
    market_candidates: pd.DataFrame,
    *,
    first_validation_month: str,
    last_validation_month: str,
    train_months: int,
    validation_months: int,
    step_months: int,
    max_feature_combo_size: int,
    require_outcome: bool,
    require_price_bucket: bool,
    max_rules: int,
    combo_size: int,
    min_rule_bets: int,
    min_rule_active_months: int,
    min_rule_roi_pct: float,
    max_pairwise_corr: float,
    require_latest_non_negative: bool,
    train_validation_months: int = 12,
    train_step_months: int = 6,
    min_train_pass_rate: float = 0.0,
    min_window_bets: int,
    min_window_roi_pct: float,
    min_positive_month_edge: int,
    max_drawdown_to_profit: float,
) -> dict[str, Any]:
    periods = list(pd.period_range(first_validation_month, last_validation_month, freq="M"))
    rows: list[dict[str, Any]] = []
    selected_rule_rows: list[dict[str, Any]] = []
    for start_idx in range(0, len(periods), step_months):
        validation_start = periods[start_idx]
        validation_end_idx = start_idx + validation_months - 1
        if validation_end_idx >= len(periods):
            break
        validation_end = periods[validation_end_idx]
        train_end = validation_start - 1
        train_start = validation_start - train_months
        train = market_candidates[
            (market_candidates["month"] >= str(train_start)) & (market_candidates["month"] <= str(train_end))
        ].copy()
        validation = market_candidates[
            (market_candidates["month"] >= str(validation_start)) & (market_candidates["month"] <= str(validation_end))
        ].copy()
        candidate_rules = _discover_rules(
            train,
            max_feature_combo_size=max_feature_combo_size,
            require_outcome=require_outcome,
            require_price_bucket=require_price_bucket,
            min_rule_bets=min_rule_bets,
            min_rule_active_months=min_rule_active_months,
            min_rule_roi_pct=min_rule_roi_pct,
            require_latest_non_negative=require_latest_non_negative,
        )
        train_rule_keys = [row["rule_key"] for row in candidate_rules[:max_rules]]
        train_rule_bets = _materialize_rule_bets(train, train_rule_keys)
        chosen = _choose_combo(
            train_rule_bets,
            candidate_rules,
            combo_size=combo_size,
            max_rules=max_rules,
            max_pairwise_corr=max_pairwise_corr,
            train_validation_months=train_validation_months,
            train_step_months=train_step_months,
            min_train_pass_rate=min_train_pass_rate,
            min_window_bets=min_window_bets,
            min_window_roi_pct=min_window_roi_pct,
            min_positive_month_edge=min_positive_month_edge,
            max_drawdown_to_profit=max_drawdown_to_profit,
        )
        if chosen is None:
            rows.append({
                "validation_start": str(validation_start),
                "validation_end": str(validation_end),
                "train_start": str(train_start),
                "train_end": str(train_end),
                "candidate_rule_count": len(candidate_rules),
                "selected_rules": [],
                "bets": 0,
                "staked": 0.0,
                "profit": 0.0,
                "roi_pct": 0.0,
                "max_drawdown": 0.0,
                "positive_months": 0,
                "negative_months": 0,
                "passes_window": False,
            })
            continue
        rule_keys = list(chosen["rules"])
        validation_bets = _combo_bets(_materialize_rule_bets(validation, rule_keys), tuple(rule_keys))
        window = _evaluate_windows(
            validation_bets,
            first_month=str(validation_start),
            last_month=str(validation_end),
            window_months=validation_months,
            step_months=validation_months,
            min_window_bets=min_window_bets,
            min_window_roi_pct=min_window_roi_pct,
            min_positive_month_edge=min_positive_month_edge,
            max_drawdown_to_profit=max_drawdown_to_profit,
        )[0]
        rows.append({
            "validation_start": str(validation_start),
            "validation_end": str(validation_end),
            "train_start": str(train_start),
            "train_end": str(train_end),
            "candidate_rule_count": len(candidate_rules),
            "selected_rules": rule_keys,
            **{key: value for key, value in chosen.items() if key not in {"rules", "rule_summaries"}},
            **window,
        })
        for rule in chosen["rule_summaries"]:
            selected_rule_rows.append({
                "validation_start": str(validation_start),
                "validation_end": str(validation_end),
                **rule,
            })
    return {
        "method": "rolling low-correlation rule selector",
        "first_validation_month": first_validation_month,
        "last_validation_month": last_validation_month,
        "config": {
            "train_months": train_months,
            "validation_months": validation_months,
            "step_months": step_months,
            "max_feature_combo_size": max_feature_combo_size,
            "require_outcome": require_outcome,
            "require_price_bucket": require_price_bucket,
            "max_rules": max_rules,
            "combo_size": combo_size,
            "min_rule_bets": min_rule_bets,
            "min_rule_active_months": min_rule_active_months,
            "min_rule_roi_pct": min_rule_roi_pct,
            "max_pairwise_corr": max_pairwise_corr,
            "require_latest_non_negative": require_latest_non_negative,
            "train_validation_months": train_validation_months,
            "train_step_months": train_step_months,
            "min_train_pass_rate": min_train_pass_rate,
            "min_window_bets": min_window_bets,
            "min_window_roi_pct": min_window_roi_pct,
            "min_positive_month_edge": min_positive_month_edge,
            "max_drawdown_to_profit": max_drawdown_to_profit,
        },
        "summary": _summarize_validation(rows),
        "windows": rows,
        "selected_rules": selected_rule_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-candidates", type=Path, action="append", required=True)
    parser.add_argument("--first-validation-month", default="2017-01")
    parser.add_argument("--last-validation-month", default="2026-05")
    parser.add_argument("--train-months", type=int, default=48)
    parser.add_argument("--validation-months", type=int, default=12)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--max-feature-combo-size", type=int, default=3)
    parser.add_argument("--allow-no-outcome", action="store_true")
    parser.add_argument("--allow-no-price-bucket", action="store_true")
    parser.add_argument("--max-rules", type=int, default=20)
    parser.add_argument("--combo-size", type=int, default=3)
    parser.add_argument("--min-rule-bets", type=int, default=80)
    parser.add_argument("--min-rule-active-months", type=int, default=18)
    parser.add_argument("--min-rule-roi-pct", type=float, default=2.0)
    parser.add_argument("--max-pairwise-corr", type=float, default=0.35)
    parser.add_argument("--allow-negative-latest", action="store_true")
    parser.add_argument("--train-validation-months", type=int, default=12)
    parser.add_argument("--train-step-months", type=int, default=6)
    parser.add_argument("--min-train-pass-rate", type=float, default=0.0)
    parser.add_argument("--min-window-bets", type=int, default=20)
    parser.add_argument("--min-window-roi-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-month-edge", type=int, default=1)
    parser.add_argument("--max-drawdown-to-profit", type=float, default=1.5)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rolling_low_correlation_rule_selector"))
    args = parser.parse_args()

    result = run_rolling_selector(
        _load_market_candidates(args.market_candidates),
        first_validation_month=args.first_validation_month,
        last_validation_month=args.last_validation_month,
        train_months=args.train_months,
        validation_months=args.validation_months,
        step_months=args.step_months,
        max_feature_combo_size=args.max_feature_combo_size,
        require_outcome=not args.allow_no_outcome,
        require_price_bucket=not args.allow_no_price_bucket,
        max_rules=args.max_rules,
        combo_size=args.combo_size,
        min_rule_bets=args.min_rule_bets,
        min_rule_active_months=args.min_rule_active_months,
        min_rule_roi_pct=args.min_rule_roi_pct,
        max_pairwise_corr=args.max_pairwise_corr,
        require_latest_non_negative=not args.allow_negative_latest,
        train_validation_months=args.train_validation_months,
        train_step_months=args.train_step_months,
        min_train_pass_rate=args.min_train_pass_rate,
        min_window_bets=args.min_window_bets,
        min_window_roi_pct=args.min_window_roi_pct,
        min_positive_month_edge=args.min_positive_month_edge,
        max_drawdown_to_profit=args.max_drawdown_to_profit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(result["windows"]).to_csv(args.output_dir / "windows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(result["selected_rules"]).to_csv(
        args.output_dir / "selected_rules.csv", index=False, encoding="utf-8-sig"
    )
    print(json.dumps({key: result[key] for key in ("method", "summary", "config")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
