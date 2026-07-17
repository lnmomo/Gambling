from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from football_agents.independent_model import INDEPENDENT_MODEL_WEIGHTS
from football_agents.models import EloModel, PoissonModel
from football_agents.research.dataset import OddsTiming, audit_football_data, load_football_data


OUTCOMES = ("home", "draw", "away")
DEFAULT_WINDOWS = ("2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-06-01")


def replay_components(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    elo = EloModel()
    poisson = PoissonModel()
    records: list[tuple[np.datetime64, int, list[float], list[float]]] = []
    for date, day in frame.groupby("match_date", sort=True):
        for row in day.itertuples():
            home, away = str(row.home_team), str(row.away_team)
            rating_delta = elo.rating(home) - elo.rating(away)
            elo_probability = elo.predict(home, away)
            poisson_probability = poisson.predict(
                max(0.45, 1.35 + rating_delta / 700),
                max(0.35, 1.05 - rating_delta / 900),
            )
            records.append((
                date.to_datetime64(),
                OUTCOMES.index(str(row.actual_result)),
                [elo_probability[outcome] for outcome in OUTCOMES],
                [poisson_probability[outcome] for outcome in OUTCOMES],
            ))
        for row in day.itertuples():
            elo.update(
                str(row.home_team),
                str(row.away_team),
                int(row.home_goals),
                int(row.away_goals),
            )
    return {
        "dates": np.array([row[0] for row in records]),
        "outcomes": np.array([row[1] for row in records], dtype=int),
        "elo": np.array([row[2] for row in records], dtype=float),
        "poisson": np.array([row[3] for row in records], dtype=float),
    }


def evaluate_weight_grid(
    replay: dict[str, np.ndarray],
    starts: tuple[str, ...] = DEFAULT_WINDOWS,
) -> list[dict[str, object]]:
    identity = np.eye(len(OUTCOMES))
    reports: list[dict[str, object]] = []
    for start in starts:
        mask = replay["dates"] >= np.datetime64(start)
        outcomes = replay["outcomes"][mask]
        elo = replay["elo"][mask]
        poisson = replay["poisson"][mask]
        candidates: list[dict[str, object]] = []
        for elo_weight in np.linspace(0.30, 0.80, 11):
            probability = elo_weight * elo + (1.0 - elo_weight) * poisson
            log_loss = -np.log(np.clip(
                probability[np.arange(len(probability)), outcomes], 1e-15, 1
            ))
            brier = ((probability - identity[outcomes]) ** 2).sum(axis=1) / len(OUTCOMES)
            class_bias = probability.mean(axis=0) - identity[outcomes].mean(axis=0)
            candidates.append({
                "elo_weight": round(float(elo_weight), 2),
                "poisson_weight": round(float(1.0 - elo_weight), 2),
                "log_loss": round(float(log_loss.mean()), 9),
                "brier_score": round(float(brier.mean()), 9),
                "maximum_absolute_class_bias": round(float(np.max(np.abs(class_bias))), 9),
                "class_bias": {
                    outcome: round(float(class_bias[index]), 9)
                    for index, outcome in enumerate(OUTCOMES)
                },
            })
        selected_elo_weight = float(INDEPENDENT_MODEL_WEIGHTS["elo"])
        selected = min(candidates, key=lambda row: abs(float(row["elo_weight"]) - selected_elo_weight))
        current = min(candidates, key=lambda row: abs(float(row["elo_weight"]) - 0.30))
        best = min(candidates, key=lambda row: (float(row["log_loss"]), float(row["brier_score"])))
        reports.append({
            "start": start,
            "matches": int(mask.sum()),
            "best": best,
            "selected": selected,
            "legacy_30_70": current,
            "selected_log_loss_improvement_vs_legacy": round(
                float(current["log_loss"]) - float(selected["log_loss"]), 9
            ),
        })
    return reports


def run(source: Path, output: Path) -> dict[str, object]:
    audit = audit_football_data(source, OddsTiming.PRE_CLOSING)
    raw = load_football_data(source, OddsTiming.PRE_CLOSING)
    frame = raw.drop_duplicates(
        ["match_date", "league", "home_team", "away_team"], keep="last"
    ).sort_values(["match_date", "league", "home_team", "away_team"]).reset_index(drop=True)
    windows = evaluate_weight_grid(replay_components(frame))
    report: dict[str, object] = {
        "method": "daily no-lookahead rolling Elo/Poisson independent-model weight validation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "dataset_audit": audit.to_dict(),
        "loaded_matches": len(raw),
        "deduplicated_matches": len(frame),
        "duplicate_rows_removed": len(raw) - len(frame),
        "first_match_date": frame["match_date"].min().date().isoformat(),
        "last_match_date": frame["match_date"].max().date().isoformat(),
        "candidate_elo_weights": [round(float(value), 2) for value in np.linspace(0.30, 0.80, 11)],
        "selected_weights": INDEPENDENT_MODEL_WEIGHTS,
        "selection_rule": (
            "Choose a rounded, conservative weight that is at or adjacent to the minimum Log Loss "
            "across every registered holdout start; Brier score is the tie-breaker."
        ),
        "windows": windows,
        "decision": (
            "USE_60_ELO_40_POISSON"
            if all(float(window["selected_log_loss_improvement_vs_legacy"]) > 0 for window in windows)
            else "KEEP_LEGACY_PENDING_REVIEW"
        ),
        "guardrails": [
            "All matches on a date are predicted before that date updates Elo ratings.",
            "Weights are selected using probability accuracy, never betting ROI.",
            "Provider odds and match results are not model inputs in this weight experiment.",
            "This validates the independent component blend; official-SP profitability still requires prospective evidence.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/historical_csv/football-data"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/independent_model_weight_validation"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
