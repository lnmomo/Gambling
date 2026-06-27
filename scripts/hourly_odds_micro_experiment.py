from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from football_agents.repository import Repository


OUTCOMES = ("home", "draw", "away")


def devig(odds: dict[str, float]) -> dict[str, float]:
    inverse = {outcome: 1 / odds[outcome] for outcome in OUTCOMES}
    total = sum(inverse.values())
    return {outcome: inverse[outcome] / total for outcome in OUTCOMES}


def settle(rule: str, sample: dict, outcome: str, odds: float, stake: float = 20.0) -> dict:
    won = outcome == sample["outcome"]
    profit = stake * (odds - 1) if won else -stake
    return {
        "rule": rule, "official_match_id": sample["official_match_id"],
        "home_team": sample["home_team"], "away_team": sample["away_team"],
        "selected_outcome": outcome, "selected_odds": odds,
        "actual_outcome": sample["outcome"], "stake": stake,
        "won": won, "profit": round(profit, 2),
    }


def summarize(rows: list[dict]) -> dict:
    staked = sum(row["stake"] for row in rows)
    profit = sum(row["profit"] for row in rows)
    return {
        "bets": len(rows), "wins": sum(row["won"] for row in rows),
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
    }


def run() -> tuple[dict, list[dict]]:
    repository = Repository()
    samples = repository.list_official_odds_training_samples(10_000)
    observations = repository.list_official_odds_observations(limit=100_000)
    by_match: dict[str, list[dict]] = {}
    for row in observations:
        by_match.setdefault(row["official_match_id"], []).append(row)

    bets: list[dict] = []
    last_minutes: list[float] = []
    for sample in samples:
        opening = {outcome: float(sample[f"opening_{outcome}_sp"]) for outcome in OUTCOMES}
        latest = {outcome: float(sample[f"closing_{outcome}_sp"]) for outcome in OUTCOMES}
        favorite = min(OUTCOMES, key=lambda outcome: opening[outcome])
        bets.append(settle("OPENING_FAVORITE", sample, favorite, opening[favorite]))

        opening_probability, latest_probability = devig(opening), devig(latest)
        movement = {outcome: latest_probability[outcome] - opening_probability[outcome] for outcome in OUTCOMES}
        strongest = max(OUTCOMES, key=lambda outcome: movement[outcome])
        if movement[strongest] >= .002:
            row = settle("HOURLY_MOMENTUM_0_2PP", sample, strongest, latest[strongest])
            row["probability_movement_pp"] = round(movement[strongest] * 100, 4)
            bets.append(row)

        match_observations = [row for row in by_match.get(sample["official_match_id"], []) if row["is_pre_match"]]
        if match_observations:
            last_minutes.append(min(float(row["minutes_to_kickoff"]) for row in match_observations))

    rules = sorted({row["rule"] for row in bets})
    summary = {
        "status": "PRELIMINARY_INSUFFICIENT_SAMPLE" if len(samples) < 30 else "EVALUATED",
        "settled_matches": len(samples), "hourly_observations": len(observations),
        "true_t_minus_1h_coverage": sum(minutes <= 60 for minutes in last_minutes),
        "average_last_snapshot_minutes_to_kickoff": round(sum(last_minutes) / len(last_minutes), 2) if last_minutes else None,
        "rules": {rule: summarize([row for row in bets if row["rule"] == rule]) for rule in rules},
        "warnings": [
            "Fewer than 30 settled matches; results must not be used for parameter tuning or promotion.",
            "The latest available pre-match snapshot is not necessarily the true closing price.",
        ],
    }
    return summary, bets


def main() -> None:
    output_dir = PROJECT_ROOT / "reports" / "hourly_odds_micro_experiment"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, bets = run()
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "bets.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in bets for key in row}))
        writer.writeheader()
        writer.writerows(bets)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
