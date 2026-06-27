from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from football_agents.models import EloModel, EnsembleModel, PoissonModel
from football_agents.models.ensemble import market_probabilities, market_residual_anchor


OUTCOMES = ("home", "draw", "away")
IMPROVED_CONFIG = {
    "model_blend": 0.60,
    "uncertainty_haircut": 0.05,
    "min_lower_bound_ev": 0.03,
    "min_odds": 1.50,
    "max_odds": 5.00,
    "max_model_market_gap": 0.18,
    "stake_per_pick": 20.0,
    "allowed_outcomes": ("away",),
}
ODDS_COLUMNS = {
    "home": ("B365H", "AvgH", "PSH", "MaxH"),
    "draw": ("B365D", "AvgD", "PSD", "MaxD"),
    "away": ("B365A", "AvgA", "PSA", "MaxA"),
}


def first_valid_odds(row: pd.Series, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = pd.to_numeric(row.get(name), errors="coerce")
        if pd.notna(value) and float(value) > 1:
            return float(value)
    return None


def load_matches(source_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(source_dir.glob("*.csv")):
        frame = pd.read_csv(path, low_memory=False)
        required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
        if not required.issubset(frame.columns):
            continue
        frame = frame.copy()
        frame["league"] = frame.get("Div", path.stem)
        frame["source_file"] = path.name
        frames.append(frame)
    if not frames:
        raise ValueError(f"No usable football-data CSV files found under {source_dir}")
    matches = pd.concat(frames, ignore_index=True, sort=False)
    matches["match_date"] = pd.to_datetime(matches["Date"], dayfirst=True, errors="coerce")
    matches["home_goals"] = pd.to_numeric(matches["FTHG"], errors="coerce")
    matches["away_goals"] = pd.to_numeric(matches["FTAG"], errors="coerce")
    matches = matches.dropna(subset=["match_date", "HomeTeam", "AwayTeam", "home_goals", "away_goals"])
    odds_rows = []
    for _, row in matches.iterrows():
        odds_rows.append({outcome: first_valid_odds(row, columns) for outcome, columns in ODDS_COLUMNS.items()})
    odds = pd.DataFrame(odds_rows, index=matches.index)
    matches = pd.concat([matches, odds.add_prefix("odds_")], axis=1)
    matches = matches.dropna(subset=["odds_home", "odds_draw", "odds_away"])
    return matches.sort_values(["match_date", "league", "HomeTeam"]).reset_index(drop=True)


def actual_outcome(row: pd.Series) -> str:
    home, away = int(row["home_goals"]), int(row["away_goals"])
    return "home" if home > away else "draw" if home == away else "away"


def prediction_for(row: pd.Series, elo: EloModel, poisson: PoissonModel, ensemble: EnsembleModel,
                   strategy: str = "baseline") -> dict:
    home, away = str(row["HomeTeam"]), str(row["AwayTeam"])
    rating_delta = elo.rating(home) - elo.rating(away)
    lambda_home = max(0.45, 1.35 + rating_delta / 700)
    lambda_away = max(0.35, 1.05 - rating_delta / 900)
    opening_odds = {outcome: float(row[f"odds_{outcome}"]) for outcome in OUTCOMES}
    market_probability = market_probabilities(opening_odds)
    raw_probability = ensemble.predict({
        "elo": elo.predict(home, away),
        "poisson": poisson.predict(lambda_home, lambda_away),
        "market": market_probability,
    })
    if strategy == "improved":
        blend = IMPROVED_CONFIG["model_blend"]
        probabilities = {
            outcome: market_probability[outcome] + blend * (raw_probability[outcome] - market_probability[outcome])
            for outcome in OUTCOMES
        }
    else:
        probabilities = raw_probability
    probabilities, anchor_metadata = market_residual_anchor(probabilities, market_probability, reliability=0.85)
    choices = [{
        "outcome": outcome,
        "probability": probabilities[outcome],
        "raw_probability": raw_probability[outcome],
        "market_probability": market_probability[outcome],
        "model_market_gap": abs(raw_probability[outcome] - market_probability[outcome]),
        "anchored": bool(anchor_metadata["capped"]),
        "anchor_max_deviation_before": anchor_metadata["max_deviation_before"],
        "anchor_max_deviation_after": anchor_metadata["max_deviation_after"],
        "odds": opening_odds[outcome],
        "ev": probabilities[outcome] * opening_odds[outcome] - 1,
    } for outcome in OUTCOMES]
    return max(choices, key=lambda item: item["ev"])


def allocate(candidates: list[dict], budget: float, strategy: str = "baseline") -> list[dict]:
    if strategy == "improved":
        eligible: list[dict] = []
        for item in candidates:
            lower_probability = item["probability"] - IMPROVED_CONFIG["uncertainty_haircut"] * item["model_market_gap"]
            item["lower_bound_ev"] = lower_probability * item["odds"] - 1
            if not IMPROVED_CONFIG["min_odds"] <= item["odds"] <= IMPROVED_CONFIG["max_odds"]:
                continue
            if item["outcome"] not in IMPROVED_CONFIG["allowed_outcomes"]:
                continue
            if item["model_market_gap"] > IMPROVED_CONFIG["max_model_market_gap"]:
                continue
            if item["lower_bound_ev"] < IMPROVED_CONFIG["min_lower_bound_ev"]:
                continue
            eligible.append(item)
        selected = sorted(eligible, key=lambda item: item["lower_bound_ev"], reverse=True)[:5]
        remaining = budget
        for item in selected:
            item["stake"] = round(min(IMPROVED_CONFIG["stake_per_pick"], remaining), 2)
            remaining -= item["stake"]
        return [item for item in selected if item["stake"] > 0]

    selected = sorted(candidates, key=lambda item: item["ev"], reverse=True)[:5]
    if not selected or budget < 0.01:
        return []
    for item in selected:
        item["score"] = math.exp(max(-1, min(1, item["ev"] * 5)))
        item["stake"] = 0.0
    remaining, active = budget, selected[:]
    cap = budget * 0.35
    while remaining >= 0.01 and active:
        total_score = sum(item["score"] for item in active)
        distributed = 0.0
        for item in active:
            addition = min(remaining * item["score"] / total_score, cap - item["stake"])
            if addition > 0:
                item["stake"] += addition
                distributed += addition
        remaining -= distributed
        active = [item for item in active if item["stake"] < cap - 0.001]
        if distributed < 0.001:
            break
    rounded = [round(item["stake"], 2) for item in selected]
    rounding_delta = round(budget - sum(rounded), 2)
    if rounded and abs(rounding_delta) <= 0.05 and rounded[0] + rounding_delta <= cap + 0.001:
        rounded[0] += rounding_delta
    for item, stake in zip(selected, rounded):
        item["stake"] = round(stake, 2)
    return [item for item in selected if item["stake"] > 0]


def max_drawdown(equity: list[float]) -> tuple[float, float]:
    peak, worst_amount, worst_pct = equity[0], 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        amount = peak - value
        pct = amount / peak if peak else 0.0
        worst_amount = max(worst_amount, amount)
        worst_pct = max(worst_pct, pct)
    return worst_amount, worst_pct


def run_backtest(matches: pd.DataFrame, month: str, starting_bankroll: float, daily_budget: float,
                 strategy: str = "baseline", unlimited_bankroll: bool = False) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    period = pd.Period(month, freq="M")
    month_start, month_end = period.start_time.normalize(), period.end_time.normalize()
    warmup = matches[matches["match_date"] < month_start]
    test = matches[(matches["match_date"] >= month_start) & (matches["match_date"] <= month_end)]
    if test.empty:
        raise ValueError(f"No eligible matches found for {month}")

    elo, poisson, ensemble = EloModel(), PoissonModel(), EnsembleModel()
    for _, day_matches in warmup.groupby("match_date", sort=True):
        for _, row in day_matches.iterrows():
            elo.update(str(row["HomeTeam"]), str(row["AwayTeam"]), int(row["home_goals"]), int(row["away_goals"]))

    bankroll = 0.0 if unlimited_bankroll else float(starting_bankroll)
    equity = [bankroll]
    bet_rows: list[dict] = []
    day_rows: list[dict] = []
    grouped = {date.normalize(): rows for date, rows in test.groupby("match_date", sort=True)}
    for date in pd.date_range(month_start, month_end, freq="D"):
        day_matches = grouped.get(date, test.iloc[0:0])
        bankroll_before = bankroll
        candidates: list[dict] = []
        # All predictions are frozen before any result from this date is read.
        for index, row in day_matches.iterrows():
            pick = prediction_for(row, elo, poisson, ensemble, strategy)
            candidates.append({
                **pick,
                "row_index": index,
                "date": date.strftime("%Y-%m-%d"),
                "league": str(row["league"]),
                "home_team": str(row["HomeTeam"]),
                "away_team": str(row["AwayTeam"]),
                "source_file": str(row["source_file"]),
            })
        budget = float(daily_budget) if unlimited_bankroll else min(float(daily_budget), bankroll)
        picks = allocate(candidates, budget, strategy)

        day_profit = 0.0
        for pick in picks:
            row = matches.loc[pick["row_index"]]
            result = actual_outcome(row)
            won = pick["outcome"] == result
            profit = pick["stake"] * (pick["odds"] - 1) if won else -pick["stake"]
            day_profit += profit
            bet_rows.append({
                **{key: value for key, value in pick.items() if key not in {"row_index", "score"}},
                "actual_result": result,
                "won": won,
                "profit": round(profit, 2),
            })
        bankroll = bankroll + day_profit if unlimited_bankroll else max(0.0, bankroll + day_profit)
        equity.append(bankroll)
        day_rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "matches_available": len(day_matches),
            "picks": len(picks),
            "bankroll_before": None if unlimited_bankroll else round(bankroll_before, 2),
            "cumulative_profit_before": round(bankroll_before, 2) if unlimited_bankroll else round(bankroll_before - starting_bankroll, 2),
            "staked": round(sum(pick["stake"] for pick in picks), 2),
            "profit": round(day_profit, 2),
            "bankroll_after": None if unlimited_bankroll else round(bankroll, 2),
            "cumulative_profit_after": round(bankroll, 2) if unlimited_bankroll else round(bankroll - starting_bankroll, 2),
        })

        for _, row in day_matches.iterrows():
            elo.update(str(row["HomeTeam"]), str(row["AwayTeam"]), int(row["home_goals"]), int(row["away_goals"]))
    bets, days = pd.DataFrame(bet_rows), pd.DataFrame(day_rows)
    total_staked = float(bets["stake"].sum()) if not bets.empty else 0.0
    net_profit = bankroll if unlimited_bankroll else bankroll - starting_bankroll
    drawdown_amount, drawdown_pct = max_drawdown(equity)
    summary = {
        "method": "daily walk-forward shadow portfolio",
        "strategy": strategy,
        "strategy_config": IMPROVED_CONFIG if strategy == "improved" else None,
        "capital_mode": "UNLIMITED_RESERVE" if unlimited_bankroll else "FINITE_BANKROLL",
        "month": month,
        "source_directory": str(matches.attrs.get("source_directory", "")),
        "odds_timing": "pre_closing_without_exact_snapshot_timestamp",
        "same_day_results_hidden_until_settlement": True,
        "starting_bankroll": None if unlimited_bankroll else round(starting_bankroll, 2),
        "fixed_daily_budget": round(daily_budget, 2),
        "ending_bankroll": None if unlimited_bankroll else round(bankroll, 2),
        "cumulative_profit": round(net_profit, 2),
        "net_profit": round(net_profit, 2),
        "bankroll_growth_pct": None if unlimited_bankroll else round(net_profit / starting_bankroll * 100, 2),
        "calendar_days_simulated": int(len(days)),
        "matches_seen": int(days["matches_available"].sum()) if not days.empty else 0,
        "bets": int(len(bets)),
        "winning_bets": int(bets["won"].sum()) if not bets.empty else 0,
        "win_rate_pct": round(float(bets["won"].mean()) * 100, 2) if not bets.empty else 0.0,
        "total_staked": round(total_staked, 2),
        "roi_pct": round(net_profit / total_staked * 100, 2) if total_staked else 0.0,
        "max_drawdown": round(drawdown_amount, 2),
        "max_drawdown_pct": None if unlimited_bankroll else round(drawdown_pct * 100, 2),
        "ruined": False if unlimited_bankroll else bankroll < 0.01,
    }
    return summary, days, bets


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe monthly shadow portfolio simulation")
    parser.add_argument("--month", default="2025-04", help="Natural month in YYYY-MM format")
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--daily-budget", type=float, default=100.0)
    parser.add_argument("--strategy", choices=("baseline", "improved"), default="improved")
    parser.add_argument("--unlimited-bankroll", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=Path("data/historical_csv/football-data/2425"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/monthly_shadow_backtest"))
    args = parser.parse_args()

    matches = load_matches(args.source_dir)
    matches.attrs["source_directory"] = str(args.source_dir)
    summary, days, bets = run_backtest(matches, args.month, args.bankroll, args.daily_budget, args.strategy, args.unlimited_bankroll)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"shadow_{args.strategy}_{args.month}"
    (args.output_dir / f"{stem}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    days.to_csv(args.output_dir / f"{stem}_daily.csv", index=False, encoding="utf-8-sig")
    bets.to_csv(args.output_dir / f"{stem}_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
