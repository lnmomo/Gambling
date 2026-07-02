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

from football_agents.models.ensemble import market_probabilities  # noqa: E402
from online_calibrated_edge_strategy import (  # noqa: E402
    DEFAULT_BUCKET_COLUMNS,
    _candidate_pool,
    _settle_month,
    load_seasons,
)
from walk_forward_residual_strategy import ResidualProbabilityModel, build_feature_history, metrics  # noqa: E402


CLOSE_COLUMNS = {
    "home": ("AvgCH", "PSCH", "B365CH", "MaxCH"),
    "draw": ("AvgCD", "PSCD", "B365CD", "MaxCD"),
    "away": ("AvgCA", "PSCA", "B365CA", "MaxCA"),
}


def _first_close(row: pd.Series, outcome: str) -> float | None:
    for column in CLOSE_COLUMNS[outcome]:
        value = pd.to_numeric(row.get(column), errors="coerce")
        if pd.notna(value) and float(value) > 1:
            return float(value)
    return None


def _features_with_closing(matches: pd.DataFrame) -> pd.DataFrame:
    features = build_feature_history(matches)
    close_rows = []
    for _, row in matches.sort_values("match_date").iterrows():
        close_rows.append({
            "match_date": row["match_date"],
            "league": str(row["league"]),
            "home_team": str(row["HomeTeam"]),
            "away_team": str(row["AwayTeam"]),
            **{f"closing_odds_{outcome}": _first_close(row, outcome) for outcome in ("home", "draw", "away")},
        })
    close = pd.DataFrame(close_rows)
    return features.merge(close, on=["match_date", "league", "home_team", "away_team"], how="left")


def _attach_clv(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    rows = []
    for _, row in candidates.iterrows():
        outcome = str(row["outcome"])
        close = float(row.get(f"closing_odds_{outcome}") or 0)
        if close <= 1:
            continue
        closing = {
            key: float(row.get(f"closing_odds_{key}") or 0)
            for key in ("home", "draw", "away")
        }
        if any(value <= 1 for value in closing.values()):
            continue
        item = row.to_dict()
        item["closing_odds"] = close
        item["clv"] = float(row["odds"]) / close - 1
        item["closing_edge"] = market_probabilities(closing)[outcome] * float(row["odds"]) - 1
        rows.append(item)
    return pd.DataFrame(rows)


def _clv_bucket_report(
    history: pd.DataFrame,
    *,
    min_samples: int,
    min_avg_clv: float,
    min_avg_closing_edge: float,
    require_positive_profit: bool,
) -> tuple[set[str], list[dict[str, Any]]]:
    if history.empty:
        return set(), []
    rows = []
    for bucket_id, group in history.groupby("bucket_id"):
        profit = float(group["unit_profit"].sum())
        avg_clv = float(group["clv"].mean())
        avg_edge = float(group["closing_edge"].mean())
        samples = int(len(group))
        passes = (
            samples >= min_samples
            and avg_clv >= min_avg_clv
            and avg_edge >= min_avg_closing_edge
            and (profit > 0 or not require_positive_profit)
        )
        rows.append({
            "bucket_id": str(bucket_id),
            "samples": samples,
            "profit": round(profit, 2),
            "roi_pct": round(profit / samples * 100, 2) if samples else 0.0,
            "avg_clv_pct": round(avg_clv * 100, 3),
            "avg_closing_edge_pct": round(avg_edge * 100, 3),
            "passes": passes,
        })
    rows.sort(key=lambda row: (row["passes"], row["avg_clv_pct"], row["avg_closing_edge_pct"], row["profit"]), reverse=True)
    return {row["bucket_id"] for row in rows if row["passes"]}, rows


def run_online_clv_strategy(
    features: pd.DataFrame,
    *,
    first_month: str,
    last_month: str,
    train_months: int,
    min_lower_ev: float,
    min_odds: float,
    max_odds: float,
    bucket_columns: tuple[str, ...],
    min_bucket_samples: int,
    min_avg_clv: float,
    min_avg_closing_edge: float,
    require_positive_profit: bool,
    stake: float,
    league_filter: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate_history: list[pd.DataFrame] = []
    all_days: list[pd.DataFrame] = []
    all_bets: list[pd.DataFrame] = []
    all_candidates: list[pd.DataFrame] = []
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
        candidates = _attach_clv(_candidate_pool(
            predictions,
            min_lower_ev=min_lower_ev,
            min_odds=min_odds,
            max_odds=max_odds,
            bucket_columns=bucket_columns,
        ))
        if not candidates.empty:
            all_candidates.append(candidates)
        history = pd.concat(candidate_history, ignore_index=True) if candidate_history else pd.DataFrame()
        allowed, bucket_rows = _clv_bucket_report(
            history,
            min_samples=min_bucket_samples,
            min_avg_clv=min_avg_clv,
            min_avg_closing_edge=min_avg_closing_edge,
            require_positive_profit=require_positive_profit,
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
            "top_allowed_buckets": [row for row in bucket_rows[:10] if row["passes"]],
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
        "method": "online CLV-filtered residual edge strategy",
        "first_month": first_month,
        "last_month": last_month,
        "uses_only_prior_candidate_clv_for_filtering": True,
        "opening_odds_used_for_settlement": True,
        "closing_odds_reference_only_after_match": True,
        "config": {
            "train_months": train_months,
            "min_lower_ev": min_lower_ev,
            "min_odds": min_odds,
            "max_odds": max_odds,
            "bucket_columns": bucket_columns,
            "min_bucket_samples": min_bucket_samples,
            "min_avg_clv": min_avg_clv,
            "min_avg_closing_edge": min_avg_closing_edge,
            "require_positive_profit": require_positive_profit,
            "stake": stake,
            "league_filter": league_filter,
        },
        "overall": overall,
        "active_months": len(active),
        "positive_months": int(sum(row.get("profit", 0) > 0 for row in active)),
        "negative_months": int(sum(row.get("profit", 0) < 0 for row in active)),
        "monthly": monthly,
    }
    return summary, days, bets, candidates


def _parse_columns(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--seasons", default="2122,2223,2324,2425,2526")
    parser.add_argument("--train-months", type=int, default=18)
    parser.add_argument("--min-lower-ev", type=float, default=-0.02)
    parser.add_argument("--min-odds", type=float, default=1.8)
    parser.add_argument("--max-odds", type=float, default=6.0)
    parser.add_argument("--bucket-columns", default="league,outcome,odds_bucket")
    parser.add_argument("--min-bucket-samples", type=int, default=6)
    parser.add_argument("--min-avg-clv", type=float, default=0.0)
    parser.add_argument("--min-avg-closing-edge", type=float, default=0.0)
    parser.add_argument("--allow-negative-profit", action="store_true")
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--league-filter")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/online_clv_filtered_edge_strategy"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    features = _features_with_closing(load_seasons(seasons))
    summary, days, bets, candidates = run_online_clv_strategy(
        features,
        first_month=args.first_month,
        last_month=args.last_month,
        train_months=args.train_months,
        min_lower_ev=args.min_lower_ev,
        min_odds=args.min_odds,
        max_odds=args.max_odds,
        bucket_columns=_parse_columns(args.bucket_columns),
        min_bucket_samples=args.min_bucket_samples,
        min_avg_clv=args.min_avg_clv,
        min_avg_closing_edge=args.min_avg_closing_edge,
        require_positive_profit=not args.allow_negative_profit,
        stake=args.stake,
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
