"""Add cross-cost all-outcome selections absent from the frozen base portfolio."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.clv_model_agreement_replay import cap_daily_group_exposure
from scripts.frozen_portfolio_report import write_frozen_portfolio_report
from scripts.multi_horizon_clv_replay import cap_daily_exposure


def cross_cost_incremental_tiers(
    bases: list[pd.DataFrame], candidates: list[pd.DataFrame],
    confirmation_candidates: list[pd.DataFrame] | None = None,
    fallback_candidates: list[pd.DataFrame] | None = None,
    supplemental_candidates: list[pd.DataFrame] | None = None,
) -> list[pd.DataFrame]:
    if len(bases) != len(candidates) or len(bases) < 2:
        raise ValueError("matching base and candidate paths for at least two costs are required")
    required = {"match_key", "outcome", "stake", "odds", "won", "date", "league"}
    for frame in candidates:
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"candidate path is missing columns: {sorted(missing)}")
    effective_candidates = candidates
    if fallback_candidates is not None:
        if len(fallback_candidates) != len(candidates):
            raise ValueError("fallback candidate paths must match candidate path count")
        effective_candidates = []
        for primary, fallback in zip(candidates, fallback_candidates):
            missing = required - set(fallback.columns)
            if missing:
                raise ValueError(
                    f"fallback candidate path is missing columns: {sorted(missing)}"
                )
            primary_months = set(primary["test_month"].astype(str))
            fallback_only = fallback.loc[
                ~fallback["test_month"].astype(str).isin(primary_months)
            ].copy()
            effective_candidates.append(pd.concat(
                [primary, fallback_only], ignore_index=True, sort=False
            ))
    if supplemental_candidates is not None:
        if len(supplemental_candidates) != len(effective_candidates):
            raise ValueError(
                "supplemental candidate paths must match candidate path count"
            )
        supplemented = []
        for primary, supplemental in zip(
            effective_candidates, supplemental_candidates
        ):
            missing = required - set(supplemental.columns)
            if missing:
                raise ValueError(
                    "supplemental candidate path is missing columns: "
                    f"{sorted(missing)}"
                )
            primary_matches = set(primary["match_key"].astype(str))
            additions = supplemental.loc[
                ~supplemental["match_key"].astype(str).isin(primary_matches)
            ].copy()
            supplemented.append(pd.concat(
                [primary, additions], ignore_index=True, sort=False
            ))
        effective_candidates = supplemented
    candidate_sets = [
        set(map(tuple, frame[["match_key", "outcome"]].astype(str).to_numpy()))
        for frame in effective_candidates
    ]
    if confirmation_candidates is not None:
        if len(confirmation_candidates) != len(candidates):
            raise ValueError(
                "confirmation candidate paths must match candidate path count"
            )
        for frame in confirmation_candidates:
            missing = required - set(frame.columns)
            if missing:
                raise ValueError(
                    "confirmation candidate path is missing columns: "
                    f"{sorted(missing)}"
                )
        candidate_sets.extend(
            set(map(tuple, frame[["match_key", "outcome"]].astype(str).to_numpy()))
            for frame in confirmation_candidates
        )
    common = set.intersection(*candidate_sets)
    base_matches = set().union(*[
        set(frame["candidate_id"].astype(str)) for frame in bases
    ])
    incremental_keys = {
        key for key in common if key[0] not in base_matches
    }
    confidence_by_key: dict[tuple[str, str], float] = {}
    if all("predicted_positive_clv_probability" in frame for frame in candidates):
        for key in incremental_keys:
            values = []
            for frame in candidates:
                matched = frame.loc[
                    (frame["match_key"].astype(str) == key[0])
                    & (frame["outcome"].astype(str) == key[1]),
                    "predicted_positive_clv_probability",
                ]
                if len(matched) and pd.notna(matched.iloc[0]):
                    values.append(float(matched.iloc[0]))
            if len(values) == len(candidates):
                confidence_by_key[key] = min(values)
    tiers = []
    for frame in effective_candidates:
        keys = pd.Series(
            list(map(tuple, frame[["match_key", "outcome"]].astype(str).to_numpy())),
            index=frame.index,
        )
        tier = frame.loc[keys.isin(incremental_keys)].copy()
        tier["candidate_id"] = tier["match_key"].astype(str)
        tier["horizon_role"] = "9m3m_all_outcomes_incremental"
        tier["cross_cost_positive_clv_probability"] = [
            confidence_by_key.get((str(match_key), str(outcome)))
            for match_key, outcome in tier[["match_key", "outcome"]].to_numpy()
        ]
        tiers.append(tier)
    return tiers


def combine_incremental_tier(
    base: pd.DataFrame, tier: pd.DataFrame, tier_stake_multiplier: float = 1.0,
    confidence_anchor: float | None = None,
    confidence_maximum_multiplier: float = 1.25,
) -> pd.DataFrame:
    if tier_stake_multiplier <= 0:
        raise ValueError("tier stake multiplier must be positive")
    tier = tier.copy()
    tier["base_stake_before_tier_multiplier"] = tier["stake"].astype(float)
    if confidence_anchor is not None:
        if confidence_anchor <= 0 or confidence_maximum_multiplier < 1.0:
            raise ValueError("confidence sizing parameters are invalid")
        if "cross_cost_positive_clv_probability" not in tier:
            raise ValueError("cross-cost confidence is unavailable")
        confidence = tier["cross_cost_positive_clv_probability"].astype(float)
        tier["tier_confidence_multiplier"] = (
            confidence.div(confidence_anchor).clip(
                lower=1.0, upper=confidence_maximum_multiplier
            )
        )
    else:
        tier["tier_confidence_multiplier"] = 1.0
    tier["stake"] = (
        tier["stake"].astype(float) * tier_stake_multiplier
        * tier["tier_confidence_multiplier"].astype(float)
    ).round(2)
    combined = pd.concat([base, tier], ignore_index=True, sort=False)
    combined = cap_daily_group_exposure(combined, "league", 15.0)
    combined = cap_daily_exposure(combined, 100.0)
    combined["profit"] = combined.apply(
        lambda row: round(
            float(row["stake"]) * (float(row["odds"]) - 1.0)
            if bool(row["won"]) else -float(row["stake"]),
            2,
        ), axis=1,
    )
    return combined


def replay(
    base_dirs: list[Path], candidate_dirs: list[Path], output_dirs: list[Path],
    tier_stake_multiplier: float = 1.0,
    confirmation_candidate_dirs: list[Path] | None = None,
    fallback_candidate_dirs: list[Path] | None = None,
    supplemental_candidate_dirs: list[Path] | None = None,
    confidence_anchor: float | None = None,
    confidence_maximum_multiplier: float = 1.25,
) -> list[dict[str, Any]]:
    if not (len(base_dirs) == len(candidate_dirs) == len(output_dirs)):
        raise ValueError("base, candidate and output path counts must match")
    bases = [pd.read_csv(path / "positions.csv") for path in base_dirs]
    candidates = [pd.read_csv(path / "positions.csv") for path in candidate_dirs]
    confirmations = (
        [pd.read_csv(path / "positions.csv") for path in confirmation_candidate_dirs]
        if confirmation_candidate_dirs else None
    )
    fallbacks = (
        [pd.read_csv(path / "positions.csv") for path in fallback_candidate_dirs]
        if fallback_candidate_dirs else None
    )
    supplements = (
        [pd.read_csv(path / "positions.csv") for path in supplemental_candidate_dirs]
        if supplemental_candidate_dirs else None
    )
    tiers = cross_cost_incremental_tiers(
        bases, candidates, confirmations, fallbacks, supplements
    )
    reports = []
    for base_dir, output_dir, base, tier in zip(
        base_dirs, output_dirs, bases, tiers
    ):
        source = json.loads(
            (base_dir / "summary.json").read_text(encoding="utf-8-sig")
        )
        reports.append(write_frozen_portfolio_report(
            combine_incremental_tier(
                base, tier, tier_stake_multiplier, confidence_anchor,
                confidence_maximum_multiplier,
            ), source, output_dir,
            "cross-cost all-outcomes incremental direction tier",
            "Every eligible 1X2 direction is scored from opening information. A new "
            "match is added only when both execution-cost paths select the same direction; "
            "closing prices and results are attached after freezing.",
            {
                "base_positions": int(len(base)),
                "incremental_positions": int(len(tier)),
                "incremental_horizon_role": "9m3m_all_outcomes_incremental",
                "tier_stake_multiplier": tier_stake_multiplier,
                "confidence_anchor": confidence_anchor,
                "confidence_maximum_multiplier": confidence_maximum_multiplier,
                "confirmation_model_paths": (
                    [str(path) for path in confirmation_candidate_dirs]
                    if confirmation_candidate_dirs else []
                ),
                "fallback_model_paths": (
                    [str(path) for path in fallback_candidate_dirs]
                    if fallback_candidate_dirs else []
                ),
                "fallback_rule": (
                    "use fallback only for test months absent from the primary path"
                    if fallback_candidate_dirs else None
                ),
                "supplemental_model_paths": (
                    [str(path) for path in supplemental_candidate_dirs]
                    if supplemental_candidate_dirs else []
                ),
                "supplemental_rule": (
                    "primary model wins match conflicts; supplemental model adds "
                    "only matches absent from the primary path"
                    if supplemental_candidate_dirs else None
                ),
            },
        ))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, action="append", required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument(
        "--confirmation-candidate", type=Path, action="append",
        help="Optional second model family; every path must retain the same direction.",
    )
    parser.add_argument(
        "--fallback-candidate", type=Path, action="append",
        help="Optional model used only in months absent from the primary path.",
    )
    parser.add_argument(
        "--supplemental-candidate", type=Path, action="append",
        help="Optional model adding matches absent from the primary path.",
    )
    parser.add_argument("--output", type=Path, action="append", required=True)
    parser.add_argument("--tier-stake-multiplier", type=float, default=1.0)
    parser.add_argument("--confidence-anchor", type=float)
    parser.add_argument("--confidence-maximum-multiplier", type=float, default=1.25)
    args = parser.parse_args()
    reports = replay(
        args.base, args.candidate, args.output, args.tier_stake_multiplier,
        args.confirmation_candidate,
        args.fallback_candidate,
        args.supplemental_candidate,
        args.confidence_anchor,
        args.confidence_maximum_multiplier,
    )
    print(json.dumps([{
        "positions": row["positions"],
        "incremental_positions": row["incremental_positions"],
        "closing_expected_profit": row["closing_value"]["all"]["closing_expected_profit"],
        "late_closing_expected_profit": row["closing_value"]["late"]["closing_expected_profit"],
        "maximum_drawdown": row["maximum_drawdown"],
    } for row in reports], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
