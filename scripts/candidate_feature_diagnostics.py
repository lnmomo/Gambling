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

from cross_league_rule_search import (  # noqa: E402
    DEFAULT_SEASONS,
    ResidualProbabilityModel,
    build_feature_history,
    load_seasons,
    month_candidates,
)


FEATURE_COLUMNS = (
    "league",
    "outcome",
    "odds_bucket",
    "fav_relation",
    "market_shape",
    "model_delta_bucket",
    "pure_delta_bucket",
    "strength_gap",
    "goal_env",
    "league_draw_rate_bucket",
    "draw_market_prob_bucket",
)


def load_candidate_frame(first_month: str, last_month: str, seasons: tuple[str, ...],
                         training_months: int, min_lower_ev: float, max_odds: float) -> pd.DataFrame:
    matches = load_seasons(seasons)
    features = build_feature_history(matches)
    frames: list[pd.DataFrame] = []
    for period in pd.period_range(first_month, last_month, freq="M"):
        start, end = period.start_time.normalize(), period.end_time.normalize()
        train = features[(features.match_date >= start - pd.DateOffset(months=training_months)) & (features.match_date < start)]
        test = features[(features.match_date >= start) & (features.match_date <= end)]
        if len(train) < 300 or test.empty:
            continue
        predicted = ResidualProbabilityModel(uncertainty_scale=0.85).fit(train).predict(test.reset_index(drop=True))
        candidates = month_candidates(predicted, min_lower_ev, max_odds)
        if candidates.empty:
            continue
        frames.append(candidates.assign(month=str(period)))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def summarize_group(frame: pd.DataFrame, columns: tuple[str, ...], min_samples: int,
                    min_active_months: int) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(list(columns), dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        months = group.groupby("month")["unit_profit"].sum()
        bets = int(len(group))
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
        row = {
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
        }
        rows.append(row)
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
    output = pd.concat(outputs, ignore_index=True)
    return output.sort_values(["score", "profit", "bets"], ascending=[False, False, False]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-month", default="2022-08")
    parser.add_argument("--last-month", default="2026-05")
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--training-months", type=int, default=18)
    parser.add_argument("--min-lower-ev", type=float, default=-0.02)
    parser.add_argument("--max-odds", type=float, default=7.0)
    parser.add_argument("--min-samples", type=int, default=50)
    parser.add_argument("--min-active-months", type=int, default=8)
    parser.add_argument("--max-combo-size", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/candidate_feature_diagnostics"))
    args = parser.parse_args()

    seasons = tuple(item.strip() for item in args.seasons.split(",") if item.strip())
    frame = load_candidate_frame(args.first_month, args.last_month, seasons, args.training_months, args.min_lower_ev, args.max_odds)
    diagnostics = run_diagnostics(frame, args.min_samples, args.min_active_months, args.max_combo_size)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_dir / "candidates.csv", index=False, encoding="utf-8-sig")
    diagnostics.to_csv(args.output_dir / "feature_diagnostics.csv", index=False, encoding="utf-8-sig")
    summary = {
        "method": "candidate feature diagnostics",
        "first_month": args.first_month,
        "last_month": args.last_month,
        "training_months": args.training_months,
        "candidate_count": int(len(frame)),
        "diagnostic_rows": int(len(diagnostics)),
        "top": diagnostics.head(25).to_dict(orient="records") if not diagnostics.empty else [],
        "notes": [
            "This is discovery only, not proof. Any pattern must be re-tested with no-lookahead walk-forward rules.",
        ],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
