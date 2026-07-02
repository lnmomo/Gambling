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

from monthly_shadow_backtest import OUTCOMES  # noqa: E402
from walk_forward_residual_strategy import (  # noqa: E402
    ResidualProbabilityModel,
    _odds_bucket,
    build_feature_history,
    load_matches,
    metrics,
)


DEFAULT_BUCKET_COLUMNS = ("league", "outcome", "odds_bucket")


def load_seasons(seasons: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        path = Path(f"data/historical_csv/football-data/{season}")
        if path.exists():
            frames.append(load_matches(path))
    if not frames:
        raise ValueError("No requested football-data seasons are available")
    return pd.concat(frames, ignore_index=True).sort_values("match_date").reset_index(drop=True)


def _candidate_pool(
    predictions: pd.DataFrame,
    *,
    min_lower_ev: float,
    min_odds: float,
    max_odds: float,
    bucket_columns: tuple[str, ...] = DEFAULT_BUCKET_COLUMNS,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, row in predictions.iterrows():
        choices = []
        for outcome in OUTCOMES:
            odds = float(row[f"odds_{outcome}"])
            if odds < min_odds or odds > max_odds:
                continue
            probability = float(row[f"probability_{outcome}"])
            uncertainty = float(row[f"uncertainty_{outcome}"])
            lower_ev = float(row[f"lower_ev_{outcome}"])
            if lower_ev < min_lower_ev:
                continue
            choices.append({
                "row_index": int(index),
                "date": row["match_date"].strftime("%Y-%m-%d"),
                "month": row["match_date"].to_period("M").strftime("%Y-%m"),
                "league": str(row["league"]),
                "home_team": str(row["home_team"]),
                "away_team": str(row["away_team"]),
                "outcome": outcome,
                "actual_result": str(row["actual_result"]),
                "probability": probability,
                "market_probability": float(row[f"market_{outcome}"]),
                "model_market_delta": probability - float(row[f"market_{outcome}"]),
                "uncertainty": uncertainty,
                "lower_ev": lower_ev,
                "odds": odds,
                "odds_bucket": _odds_bucket(odds),
                **{
                    f"closing_odds_{key}": row.get(f"closing_odds_{key}")
                    for key in OUTCOMES
                    if f"closing_odds_{key}" in row
                },
            })
        if choices:
            best = max(choices, key=lambda item: item["lower_ev"])
            best["won"] = best["outcome"] == best["actual_result"]
            best["unit_profit"] = best["odds"] - 1 if best["won"] else -1.0
            best["bucket_id"] = "|".join(str(best[column]) for column in bucket_columns)
            rows.append(best)
    return pd.DataFrame(rows)


def _bucket_report(history: pd.DataFrame, *, min_samples: int, min_roi: float,
                   min_positive_month_edge: int) -> tuple[set[str], list[dict[str, Any]]]:
    if history.empty:
        return set(), []
    rows: list[dict[str, Any]] = []
    for bucket_id, group in history.groupby("bucket_id"):
        month_profit = group.groupby("month")["unit_profit"].sum()
        profit = float(group["unit_profit"].sum())
        samples = int(len(group))
        roi = profit / samples if samples else 0.0
        positive = int((month_profit > 0).sum())
        negative = int((month_profit < 0).sum())
        passes = (
            samples >= min_samples
            and profit > 0
            and roi >= min_roi
            and positive - negative >= min_positive_month_edge
        )
        rows.append({
            "bucket_id": str(bucket_id),
            "samples": samples,
            "profit": round(profit, 2),
            "roi_pct": round(roi * 100, 2),
            "positive_months": positive,
            "negative_months": negative,
            "passes": passes,
        })
    rows.sort(key=lambda row: (row["passes"], row["roi_pct"], row["profit"], row["samples"]), reverse=True)
    return {row["bucket_id"] for row in rows if row["passes"]}, rows


def _settle_month(candidates: pd.DataFrame, allowed_buckets: set[str], *, stake: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = []
    bets = []
    selected = candidates[candidates["bucket_id"].isin(allowed_buckets)].copy() if not candidates.empty else candidates
    for date in pd.date_range(candidates["date"].min(), candidates["date"].max(), freq="D") if not candidates.empty else []:
        day = selected[selected["date"] == date.strftime("%Y-%m-%d")] if not selected.empty else selected
        day_profit = 0.0
        for _, row in day.sort_values("lower_ev", ascending=False).iterrows():
            profit = stake * (float(row["odds"]) - 1) if bool(row["won"]) else -stake
            day_profit += profit
            bets.append({
                "date": row["date"],
                "month": row["month"],
                "league": row["league"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "outcome": row["outcome"],
                "actual_result": row["actual_result"],
                "bucket_id": row["bucket_id"],
                "probability": round(float(row["probability"]), 6),
                "market_probability": round(float(row["market_probability"]), 6),
                "model_market_delta": round(float(row["model_market_delta"]), 6),
                "lower_ev": round(float(row["lower_ev"]), 6),
                "odds": float(row["odds"]),
                "stake": stake,
                "won": bool(row["won"]),
                "profit": round(profit, 2),
            })
        days.append({
            "date": date.strftime("%Y-%m-%d"),
            "bets": int(len(day)),
            "staked": round(len(day) * stake, 2),
            "profit": round(day_profit, 2),
        })
    return pd.DataFrame(days), pd.DataFrame(bets)


def run_online_calibrated_strategy(
    features: pd.DataFrame,
    *,
    first_month: str,
    last_month: str,
    train_months: int,
    min_lower_ev: float,
    min_odds: float,
    max_odds: float,
    min_bucket_samples: int,
    min_bucket_roi: float,
    min_positive_month_edge: int,
    stake: float,
    bucket_columns: tuple[str, ...] = DEFAULT_BUCKET_COLUMNS,
    league_filter: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []
    all_candidates: list[pd.DataFrame] = []
    candidate_history: list[pd.DataFrame] = []
    monthly: list[dict[str, Any]] = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        start = period.start_time.normalize()
        end = period.end_time.normalize()
        train = features[(features["match_date"] >= start - pd.DateOffset(months=train_months)) & (features["match_date"] < start)]
        test = features[(features["match_date"] >= start) & (features["match_date"] <= end)]
        if league_filter:
            test = test[test["league"] == league_filter]
        if len(train) < 300 or test.empty:
            monthly.append({"month": str(period), "decision": "ABSTAIN", "reason": "insufficient_train_or_test"})
            continue
        predictions = ResidualProbabilityModel(uncertainty_scale=0.75).fit(train).predict(test)
        candidates = _candidate_pool(
            predictions,
            min_lower_ev=min_lower_ev,
            min_odds=min_odds,
            max_odds=max_odds,
            bucket_columns=bucket_columns,
        )
        if not candidates.empty:
            all_candidates.append(candidates)
        history = pd.concat(candidate_history, ignore_index=True) if candidate_history else pd.DataFrame()
        allowed, buckets = _bucket_report(
            history,
            min_samples=min_bucket_samples,
            min_roi=min_bucket_roi,
            min_positive_month_edge=min_positive_month_edge,
        )
        days, bets = _settle_month(candidates, allowed, stake=stake)
        if not days.empty:
            all_days.append(days.assign(month=str(period)))
        if not bets.empty:
            all_bets.append(bets)
        result = metrics(days, bets)
        monthly.append({
            "month": str(period),
            "decision": "INVEST" if result["bets"] else "ABSTAIN",
            "candidate_count": int(len(candidates)),
            "allowed_bucket_count": int(len(allowed)),
            "top_allowed_buckets": [row for row in buckets[:10] if row["passes"]],
            **result,
        })
        if not candidates.empty:
            candidate_history.append(candidates)

    days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(columns=["date", "bets", "staked", "profit", "month"])
    bets = pd.concat(all_bets, ignore_index=True) if all_bets else pd.DataFrame()
    candidates = pd.concat(all_candidates, ignore_index=True) if all_candidates else pd.DataFrame()
    active = [row for row in monthly if row.get("bets", 0) > 0]
    overall = metrics(days, bets)
    summary = {
        "method": "online calibrated residual edge strategy",
        "first_month": first_month,
        "last_month": last_month,
        "same_day_results_hidden_until_settlement": True,
        "uses_only_prior_settled_candidate_history": True,
        "config": {
            "train_months": train_months,
            "min_lower_ev": min_lower_ev,
            "min_odds": min_odds,
            "max_odds": max_odds,
            "min_bucket_samples": min_bucket_samples,
            "min_bucket_roi": min_bucket_roi,
            "min_positive_month_edge": min_positive_month_edge,
            "stake": stake,
            "league_filter": league_filter,
            "bucket_columns": bucket_columns,
        },
        "overall": overall,
        "active_months": len(active),
        "positive_months": int(sum(row.get("profit", 0) > 0 for row in active)),
        "negative_months": int(sum(row.get("profit", 0) < 0 for row in active)),
        "monthly": monthly,
    }
    return summary, days, bets, candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--train-months", type=int, default=18)
    parser.add_argument("--min-lower-ev", type=float, default=-0.01)
    parser.add_argument("--min-odds", type=float, default=1.0)
    parser.add_argument("--max-odds", type=float, default=5.0)
    parser.add_argument("--min-bucket-samples", type=int, default=20)
    parser.add_argument("--min-bucket-roi", type=float, default=0.03)
    parser.add_argument("--min-positive-month-edge", type=int, default=1)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--bucket-columns", default="league,outcome,odds_bucket")
    parser.add_argument("--league-filter")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/online_calibrated_edge_strategy"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    features = build_feature_history(load_seasons(seasons))
    summary, days, bets, candidates = run_online_calibrated_strategy(
        features,
        first_month=args.first_month,
        last_month=args.last_month,
        train_months=args.train_months,
        min_lower_ev=args.min_lower_ev,
        min_odds=args.min_odds,
        max_odds=args.max_odds,
        min_bucket_samples=args.min_bucket_samples,
        min_bucket_roi=args.min_bucket_roi,
        min_positive_month_edge=args.min_positive_month_edge,
        stake=args.stake,
        bucket_columns=tuple(item.strip() for item in args.bucket_columns.split(",") if item.strip()),
        league_filter=args.league_filter,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / "daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / "bets.csv", index=False, encoding="utf-8-sig")
    candidates.to_csv(args.output_dir / "candidates.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({key: summary[key] for key in ("method", "overall", "active_months", "positive_months", "negative_months", "config")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
