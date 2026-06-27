from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

import pandas as pd


class OddsTiming(StrEnum):
    PRE_CLOSING = "pre_closing"
    CLOSING = "closing"


ODDS_COLUMNS = {
    OddsTiming.PRE_CLOSING: {
        "home": ("B365H", "PSH", "AvgH", "MaxH"),
        "draw": ("B365D", "PSD", "AvgD", "MaxD"),
        "away": ("B365A", "PSA", "AvgA", "MaxA"),
    },
    OddsTiming.CLOSING: {
        "home": ("B365CH", "PSCH", "AvgCH", "MaxCH"),
        "draw": ("B365CD", "PSCD", "AvgCD", "MaxCD"),
        "away": ("B365CA", "PSCA", "AvgCA", "MaxCA"),
    },
}


@dataclass(frozen=True)
class DatasetAudit:
    files: int
    raw_rows: int
    usable_rows: int
    duplicate_matches: int
    invalid_dates: int
    missing_selected_odds: int
    files_with_closing_odds: int
    first_match_date: str | None
    last_match_date: str | None
    selected_odds_timing: str
    exact_snapshot_timestamps_available: bool
    leakage_safe_for_prematch_features: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _paths(sources: Path | Iterable[Path]) -> list[Path]:
    if isinstance(sources, Path):
        return sorted(sources.rglob("*.csv")) if sources.is_dir() else [sources]
    return sorted(Path(path) for path in sources)


def _first_numeric(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
    result = pd.Series(float("nan"), index=frame.index, dtype=float)
    for name in names:
        if name in frame:
            values = pd.to_numeric(frame[name], errors="coerce")
            result = result.where(result.notna(), values.where(values > 1))
    return result


def _read_files(sources: Path | Iterable[Path]) -> tuple[list[Path], pd.DataFrame]:
    paths = _paths(sources)
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path, low_memory=False)
        required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
        if not required.issubset(frame.columns):
            continue
        frame = frame.copy()
        frame["source_file"] = str(path)
        frame["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        frame["league"] = frame["Div"] if "Div" in frame else path.stem
        frames.append(frame)
    if not frames:
        raise ValueError("No football-data CSV with the required match columns was found")
    return paths, pd.concat(frames, ignore_index=True, sort=False)


def audit_football_data(
    sources: Path | Iterable[Path], odds_timing: OddsTiming = OddsTiming.PRE_CLOSING,
) -> DatasetAudit:
    paths, frame = _read_files(sources)
    dates = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
    selected = pd.DataFrame({
        outcome: _first_numeric(frame, names)
        for outcome, names in ODDS_COLUMNS[odds_timing].items()
    })
    valid = dates.notna() & frame[["HomeTeam", "AwayTeam", "FTHG", "FTAG"]].notna().all(axis=1)
    valid &= selected.notna().all(axis=1)
    duplicate_keys = pd.DataFrame({
        "date": dates,
        "league": frame["league"],
        "home": frame["HomeTeam"],
        "away": frame["AwayTeam"],
    }).duplicated(keep=False)
    files_with_closing = 0
    for path in paths:
        columns = set(pd.read_csv(path, nrows=0).columns)
        if {"B365CH", "B365CD", "B365CA"}.issubset(columns):
            files_with_closing += 1
    warnings = (
        "Provider odds columns do not include exact collection timestamps; call them pre-closing, not opening odds.",
        "Result and post-match columns share each CSV; feature builders must explicitly whitelist pre-match columns.",
    )
    return DatasetAudit(
        files=len(paths), raw_rows=len(frame), usable_rows=int(valid.sum()),
        duplicate_matches=int(duplicate_keys.sum()), invalid_dates=int(dates.isna().sum()),
        missing_selected_odds=int(selected.isna().any(axis=1).sum()),
        files_with_closing_odds=files_with_closing,
        first_match_date=dates.min().date().isoformat() if dates.notna().any() else None,
        last_match_date=dates.max().date().isoformat() if dates.notna().any() else None,
        selected_odds_timing=odds_timing.value,
        exact_snapshot_timestamps_available=False,
        leakage_safe_for_prematch_features=False,
        warnings=warnings,
    )


def load_football_data(
    sources: Path | Iterable[Path], odds_timing: OddsTiming = OddsTiming.PRE_CLOSING,
) -> pd.DataFrame:
    _, frame = _read_files(sources)
    output = pd.DataFrame({
        "match_date": pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce"),
        "league": frame["league"].astype(str),
        "home_team": frame["HomeTeam"].astype(str),
        "away_team": frame["AwayTeam"].astype(str),
        "home_goals": pd.to_numeric(frame["FTHG"], errors="coerce"),
        "away_goals": pd.to_numeric(frame["FTAG"], errors="coerce"),
        "source_file": frame["source_file"],
        "source_sha256": frame["source_sha256"],
    })
    statistic_columns = {
        "home_shots": "HS", "away_shots": "AS",
        "home_shots_on_target": "HST", "away_shots_on_target": "AST",
        "home_corners": "HC", "away_corners": "AC",
    }
    for target, source in statistic_columns.items():
        output[target] = pd.to_numeric(frame[source], errors="coerce") if source in frame else float("nan")
    for outcome, names in ODDS_COLUMNS[odds_timing].items():
        output[f"odds_{outcome}"] = _first_numeric(frame, names)
    for outcome, names in ODDS_COLUMNS[OddsTiming.CLOSING].items():
        output[f"closing_odds_{outcome}"] = _first_numeric(frame, names)
    output["actual_result"] = "draw"
    output.loc[output["home_goals"] > output["away_goals"], "actual_result"] = "home"
    output.loc[output["home_goals"] < output["away_goals"], "actual_result"] = "away"
    required = ["match_date", "home_team", "away_team", "home_goals", "away_goals",
                "odds_home", "odds_draw", "odds_away"]
    output = output.dropna(subset=required)
    output["odds_timing"] = odds_timing.value
    return output.sort_values(["match_date", "league", "home_team", "away_team"]).reset_index(drop=True)
