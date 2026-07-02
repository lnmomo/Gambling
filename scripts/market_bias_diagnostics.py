from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import DEFAULT_SEASONS, load_seasons  # noqa: E402
from monthly_shadow_backtest import OUTCOMES, actual_outcome  # noqa: E402
from walk_forward_residual_strategy import _odds_bucket  # noqa: E402


ODDS_SOURCE_COLUMNS = {
    "B365_OPEN": {"home": "B365H", "draw": "B365D", "away": "B365A"},
    "AVG_OPEN": {"home": "AvgH", "draw": "AvgD", "away": "AvgA"},
    "PS_OPEN": {"home": "PSH", "draw": "PSD", "away": "PSA"},
    "MAX_OPEN": {"home": "MaxH", "draw": "MaxD", "away": "MaxA"},
    "B365_CLOSE": {"home": "B365CH", "draw": "B365CD", "away": "B365CA"},
    "AVG_CLOSE": {"home": "AvgCH", "draw": "AvgCD", "away": "AvgCA"},
    "PS_CLOSE": {"home": "PSCH", "draw": "PSCD", "away": "PSCA"},
    "MAX_CLOSE": {"home": "MaxCH", "draw": "MaxCD", "away": "MaxCA"},
}


FEATURE_COLUMNS = (
    "league",
    "outcome",
    "odds_bucket",
    "market_prob_bucket",
    "favorite_relation",
)


def _prob_bucket(probability: float) -> str:
    value = float(probability)
    if value < 0.20:
        return "[0.00,0.20)"
    if value < 0.28:
        return "[0.20,0.28)"
    if value < 0.34:
        return "[0.28,0.34)"
    if value < 0.42:
        return "[0.34,0.42)"
    if value < 0.55:
        return "[0.42,0.55)"
    return "[0.55,1.00]"


def market_probability(row: pd.Series, outcome: str) -> float:
    inverse = {key: 1 / float(row[f"odds_{key}"]) for key in OUTCOMES}
    total = sum(inverse.values())
    return inverse[outcome] / total


def build_market_frame(seasons: tuple[str, ...], odds_source: str = "B365_OPEN") -> pd.DataFrame:
    if odds_source not in ODDS_SOURCE_COLUMNS:
        raise ValueError(f"Unknown odds_source {odds_source}. Valid: {', '.join(ODDS_SOURCE_COLUMNS)}")
    matches = load_seasons(seasons)
    source_columns = ODDS_SOURCE_COLUMNS[odds_source]
    rows = []
    for _, row in matches.iterrows():
        actual = actual_outcome(row)
        odds_values = {}
        for outcome in OUTCOMES:
            value = pd.to_numeric(row.get(source_columns[outcome]), errors="coerce")
            if pd.isna(value) or float(value) <= 1:
                odds_values = {}
                break
            odds_values[outcome] = float(value)
        if not odds_values:
            continue
        overround = sum(1 / odds_values[outcome] for outcome in OUTCOMES)
        market_probs = {outcome: (1 / odds_values[outcome]) / overround for outcome in OUTCOMES}
        favorite = max(market_probs, key=market_probs.get)
        for outcome in OUTCOMES:
            odds = odds_values[outcome]
            won = outcome == actual
            rows.append({
                "date": row["match_date"].strftime("%Y-%m-%d"),
                "month": row["match_date"].to_period("M").strftime("%Y-%m"),
                "league": str(row["league"]),
                "home_team": str(row["HomeTeam"]),
                "away_team": str(row["AwayTeam"]),
                "outcome": outcome,
                "actual_result": actual,
                "odds": odds,
                "odds_bucket": _odds_bucket(odds),
                "market_probability": market_probs[outcome],
                "market_prob_bucket": _prob_bucket(market_probs[outcome]),
                "favorite_relation": "market_favorite" if outcome == favorite else "market_non_favorite",
                "odds_source": odds_source,
                "won": won,
                "unit_profit": odds - 1 if won else -1.0,
            })
    return pd.DataFrame(rows)


def summarize_group(frame: pd.DataFrame, columns: tuple[str, ...], min_samples: int,
                    min_active_months: int) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(list(columns), dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        bets = int(len(group))
        months = group.groupby("month")["unit_profit"].sum()
        active_months = int(group["month"].nunique())
        if bets < min_samples or active_months < min_active_months:
            continue
        profit = float(group["unit_profit"].sum())
        roi = profit / bets if bets else 0.0
        positive_months = int((months > 0).sum())
        negative_months = int((months < 0).sum())
        latest_month = str(group["month"].max())
        latest_profit = float(group[group["month"] == latest_month]["unit_profit"].sum())
        if profit <= 0 or positive_months <= negative_months:
            continue
        rows.append({
            "columns": "|".join(columns),
            "key": "|".join(str(item) for item in key),
            "bets": bets,
            "profit": round(profit, 2),
            "roi_pct": round(roi * 100, 2),
            "active_months": active_months,
            "positive_months": positive_months,
            "negative_months": negative_months,
            "latest_month": latest_month,
            "latest_profit": round(latest_profit, 2),
            "score": round((positive_months - negative_months) * 2 + roi * 10 + profit / max(bets, 1), 4),
        })
    return pd.DataFrame(rows)


def run_diagnostics(frame: pd.DataFrame, min_samples: int, min_active_months: int,
                    max_combo_size: int) -> pd.DataFrame:
    outputs = []
    for size in range(1, max_combo_size + 1):
        for columns in itertools.combinations(FEATURE_COLUMNS, size):
            result = summarize_group(frame, columns, min_samples, min_active_months)
            if not result.empty:
                outputs.append(result)
    if not outputs:
        return pd.DataFrame()
    return pd.concat(outputs, ignore_index=True).sort_values(
        ["score", "profit", "bets"], ascending=[False, False, False]
    ).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--odds-source", choices=tuple(ODDS_SOURCE_COLUMNS), default="B365_OPEN")
    parser.add_argument("--min-samples", type=int, default=150)
    parser.add_argument("--min-active-months", type=int, default=18)
    parser.add_argument("--max-combo-size", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/market_bias_diagnostics"))
    args = parser.parse_args()
    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    frame = build_market_frame(seasons, args.odds_source)
    diagnostics = run_diagnostics(frame, args.min_samples, args.min_active_months, args.max_combo_size)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_dir / "market_candidates.csv", index=False, encoding="utf-8-sig")
    diagnostics.to_csv(args.output_dir / "market_bias.csv", index=False, encoding="utf-8-sig")
    summary = {
        "method": "market odds bias diagnostics",
        "seasons": seasons,
        "odds_source": args.odds_source,
        "candidate_count": int(len(frame)),
        "diagnostic_rows": int(len(diagnostics)),
        "top": diagnostics.head(30).to_dict(orient="records") if not diagnostics.empty else [],
        "notes": [
            "This is market-bias discovery only. Any pattern must be converted into no-lookahead walk-forward rules.",
        ],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
