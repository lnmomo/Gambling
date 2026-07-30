"""Prospective-only validation of a named Bet365 versus Pinnacle price gap."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import random
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, median
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database, db
from .config import settings
from .clv_ridge_shadow import (
    ADAPTIVE_MARKET_STRUCTURE_MODEL_PATH,
    ADAPTIVE_PROBABILITY_MOVEMENT_MODEL_PATH,
    MONTH_STABLE_MARKET_STRUCTURE_MODEL_PATH,
    MONTH_STABLE_PROBABILITY_MOVEMENT_MODEL_PATH,
    MARKET_STRUCTURE_MODEL_PATH,
    PROBABILITY_MOVEMENT_MODEL_PATH,
    QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH,
    QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH,
    MARKET_CALIBRATED_MODEL_PATH,
    MARKET_CALIBRATED_PROBABILITY_MOVEMENT_MODEL_PATH,
    MULTI_HORIZON_LONG_MODEL_PATH,
    MULTI_HORIZON_LONG_MOVEMENT_MODEL_PATH,
    load_frozen_model,
    market_structure_features,
    odds_band,
    score_opening_features,
)
from .repository import Repository


OUTCOMES = ("home", "draw", "away")
CONTROL_POLICY_CONFIG = {
    "version": "robust-leave-one-book-out-market-residual-prospective-v3.1-cost-aware",
    "reference_method": "normalized_component_median_leave_execution_book_out",
    "minimum_reference_bookmakers": 4,
    "minimum_price_ratio": 1.02,
    "minimum_conservative_ev": 0.02,
    "minimum_odds": 1.50,
    "maximum_odds": 6.00,
    "minimum_reference_probability": 0.0,
    "primary_horizon_minutes": 60,
    "horizon_tolerance_minutes": 60,
    "maximum_snapshot_age_minutes": 15,
    "maximum_bookmaker_last_update_age_minutes": 15,
    "maximum_bookmaker_update_skew_minutes": 10,
    "model_residual_reliability": 0.15,
    "maximum_probability_shift": 0.02,
    "uncertainty_floor": 0.005,
    "dispersion_uncertainty_multiplier": 1.5,
    "model_disagreement_uncertainty_multiplier": 0.25,
    "slippage_rate": 0.02,
    "exchange_commission_rate": settings.exchange_commission_rate,
    "exchange_bookmaker_keys": ["betfair_ex_eu", "betfair_ex_uk", "smarkets", "matchbook"],
    "daily_budget": 100.0,
    "maximum_single_stake": 10.0,
    "kelly_fraction": 0.25,
}

POLICY_CONFIG = {
    **CONTROL_POLICY_CONFIG,
    "version": "robust-consensus-no-longshot-prospective-v4.1-cost-aware",
    "minimum_price_ratio": 1.01,
    "minimum_conservative_ev": 0.01,
    "maximum_odds": 4.00,
    "minimum_reference_probability": 0.25,
    "dispersion_uncertainty_multiplier": 1.0,
}
_CLV_RIDGE_MODEL = load_frozen_model()
CLV_RIDGE_POLICY_CONFIG = {
    **CONTROL_POLICY_CONFIG,
    "version": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
    "decision_model": "frozen_json_clv_ridge",
    "ranker_model_sha256": _CLV_RIDGE_MODEL["model_sha256"],
    "ranker_training_window": _CLV_RIDGE_MODEL["training_window"],
    "live_feature_contract": "unmapped_official_league_uses_zero_coefficient",
    "feature_portability_status": "PROSPECTIVE_VALIDATION_REQUIRED",
    "minimum_price_ratio": 0.97,
    "minimum_conservative_ev": -0.05,
    "minimum_odds": 1.50,
    "maximum_odds": 5.00,
    "minimum_reference_probability": 0.12,
    "model_residual_reliability": 0.0,
    "uncertainty_floor": 0.002,
    "dispersion_uncertainty_multiplier": 1.0,
    "model_disagreement_uncertainty_multiplier": 0.0,
    "minimum_lower_clv_pct": 1.0,
    "maximum_price_ratio": 1.15,
    "daily_budget": 100.0,
    "maximum_single_stake": 5.0,
    "kelly_fraction": 0.10,
}
CLV_RIDGE_HALF_KELLY_POLICY_CONFIG = {
    **CLV_RIDGE_POLICY_CONFIG,
    "version": "clv-ridge-v6.3-fixed-cap5-half-kelly-prospective-shadow",
    "maximum_single_stake": 15.0,
    "kelly_fraction": 0.50,
    "stake_challenger_of": "clv-ridge-v6.2-fixed-cap5-prospective-shadow",
}
_CLV_RIDGE_MARKET_STRUCTURE_MODEL = load_frozen_model(str(MARKET_STRUCTURE_MODEL_PATH))
CLV_RIDGE_MARKET_STRUCTURE_POLICY_CONFIG = {
    **CLV_RIDGE_HALF_KELLY_POLICY_CONFIG,
    "version": "clv-ridge-v6.6-market-structure-half-kelly-prospective-shadow",
    "ranker_model_filename": MARKET_STRUCTURE_MODEL_PATH.name,
    "ranker_model_sha256": _CLV_RIDGE_MARKET_STRUCTURE_MODEL["model_sha256"],
    "ranker_training_window": _CLV_RIDGE_MARKET_STRUCTURE_MODEL["training_window"],
    "live_feature_contract": "league_independent_market_structure_features",
    "feature_portability_status": "PORTABLE_PROSPECTIVE_VALIDATION_REQUIRED",
    "historical_cost_stress_status": "5pct_monthly_bootstrap_lower_95_negative",
    "latest_retraining_gate": "FAILED_FOR_WINDOW_ENDING_2026_05_31",
    "prospective_warning": (
        "v6.6 is paper-only: 5% cost stress and the latest retraining gate failed; "
        "the frozen April model requires new T-1 evidence"
    ),
    "stake_challenger_of": "clv-ridge-v6.6-market-structure-one-tenth-kelly-replay",
}
_CLV_RIDGE_MOVEMENT_MODEL = load_frozen_model(str(PROBABILITY_MOVEMENT_MODEL_PATH))
_CLV_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
    _CLV_RIDGE_MARKET_STRUCTURE_MODEL["model_sha256"],
    _CLV_RIDGE_MOVEMENT_MODEL["model_sha256"],
]), separators=(",", ":")).encode()).hexdigest()
CLV_RIDGE_MODEL_AGREEMENT_POLICY_CONFIG = {
    **CLV_RIDGE_MARKET_STRUCTURE_POLICY_CONFIG,
    "version": "clv-ridge-v7.6-dual-target-agreement-half-kelly-prospective-shadow",
    "decision_model": "frozen_json_clv_agreement",
    "ranker_model_sha256": _CLV_AGREEMENT_HASH,
    "agreement_component_model_sha256": [
        _CLV_RIDGE_MARKET_STRUCTURE_MODEL["model_sha256"],
        _CLV_RIDGE_MOVEMENT_MODEL["model_sha256"],
    ],
    "agreement_model_filename": PROBABILITY_MOVEMENT_MODEL_PATH.name,
    "agreement_rule": "both_lower_clv_at_least_1pct_then_use_minimum",
    "historical_cost_stress_status": "5pct_monthly_bootstrap_lower_95_negative",
    "latest_retraining_gate": "FAILED_FOR_WINDOW_ENDING_2026_05_31",
    "prospective_warning": (
        "v7.6 is paper-only: extended 5% cost bootstrap lower 95% is negative and "
        "latest retraining failed; collect new T-1 settlements"
    ),
}
CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG: dict[str, Any] | None = None
if ADAPTIVE_MARKET_STRUCTURE_MODEL_PATH.exists() and ADAPTIVE_PROBABILITY_MOVEMENT_MODEL_PATH.exists():
    _CLV_RIDGE_ADAPTIVE_DIRECT_MODEL = load_frozen_model(
        str(ADAPTIVE_MARKET_STRUCTURE_MODEL_PATH)
    )
    _CLV_RIDGE_ADAPTIVE_MOVEMENT_MODEL = load_frozen_model(
        str(ADAPTIVE_PROBABILITY_MOVEMENT_MODEL_PATH)
    )
    _CLV_ADAPTIVE_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
        _CLV_RIDGE_ADAPTIVE_DIRECT_MODEL["model_sha256"],
        _CLV_RIDGE_ADAPTIVE_MOVEMENT_MODEL["model_sha256"],
    ]), separators=(",", ":")).encode()).hexdigest()
    CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG = {
        **CLV_RIDGE_MODEL_AGREEMENT_POLICY_CONFIG,
        "version": "clv-ridge-v8.1-9m3m-dual-target-agreement-half-kelly-prospective-shadow",
        "ranker_model_filename": ADAPTIVE_MARKET_STRUCTURE_MODEL_PATH.name,
        "ranker_model_sha256": _CLV_ADAPTIVE_AGREEMENT_HASH,
        "ranker_training_window": _CLV_RIDGE_ADAPTIVE_DIRECT_MODEL["training_window"],
        "agreement_component_model_sha256": [
            _CLV_RIDGE_ADAPTIVE_DIRECT_MODEL["model_sha256"],
            _CLV_RIDGE_ADAPTIVE_MOVEMENT_MODEL["model_sha256"],
        ],
        "agreement_model_filename": ADAPTIVE_PROBABILITY_MOVEMENT_MODEL_PATH.name,
        "training_months": 9,
        "validation_months": 3,
        "historical_cost_stress_status": "5pct_monthly_bootstrap_lower_95_positive",
        "latest_retraining_gate": "PASSED_FOR_WINDOW_ENDING_2026_05_31",
        "prospective_warning": (
            "v8.1 is paper-only: retrospective 5% cost stress and latest retraining passed, "
            "but post-development T-1 settlements are still required before promotion"
        ),
    }
if (
    CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG
    and MONTH_STABLE_MARKET_STRUCTURE_MODEL_PATH.exists()
    and MONTH_STABLE_PROBABILITY_MOVEMENT_MODEL_PATH.exists()
):
    _CLV_RIDGE_MONTH_STABLE_DIRECT_MODEL = load_frozen_model(
        str(MONTH_STABLE_MARKET_STRUCTURE_MODEL_PATH)
    )
    _CLV_RIDGE_MONTH_STABLE_MOVEMENT_MODEL = load_frozen_model(
        str(MONTH_STABLE_PROBABILITY_MOVEMENT_MODEL_PATH)
    )
    _CLV_MONTH_STABLE_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
        _CLV_RIDGE_MONTH_STABLE_DIRECT_MODEL["model_sha256"],
        _CLV_RIDGE_MONTH_STABLE_MOVEMENT_MODEL["model_sha256"],
    ]), separators=(",", ":")).encode()).hexdigest()
    CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG = {
        **CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG,
        "version": "clv-ridge-v8.5-month-stable-depth-discount-prospective-shadow",
        "ranker_model_filename": MONTH_STABLE_MARKET_STRUCTURE_MODEL_PATH.name,
        "ranker_model_sha256": _CLV_MONTH_STABLE_AGREEMENT_HASH,
        "ranker_training_window": _CLV_RIDGE_MONTH_STABLE_DIRECT_MODEL["training_window"],
        "agreement_component_model_sha256": [
            _CLV_RIDGE_MONTH_STABLE_DIRECT_MODEL["model_sha256"],
            _CLV_RIDGE_MONTH_STABLE_MOVEMENT_MODEL["model_sha256"],
        ],
        "agreement_model_filename": MONTH_STABLE_PROBABILITY_MOVEMENT_MODEL_PATH.name,
        "minimum_inner_positive_month_rate": 0.60,
        "minimum_reference_depth": 4,
        "minimum_depth_stake_multiplier": 0.50,
        "stake_challenger_of": (
            "clv-ridge-v8.1-9m3m-dual-target-agreement-half-kelly-prospective-shadow"
        ),
        "historical_cost_stress_status": "5pct_monthly_bootstrap_lower_95_positive_18.54pct",
        "prospective_warning": (
            "v8.5 is paper-only: the inner gate requires 2/3 positive CLV months and "
            "minimum-depth evidence receives a 50% stake discount; "
            "post-development T-1 settlements are required before promotion"
        ),
    }
    CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG = {
        **CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG,
        "version": "clv-ridge-v8.7-min25pct-probability-prospective-shadow",
        "minimum_staking_probability": 0.25,
        "stake_challenger_of": (
            "clv-ridge-v8.5-month-stable-depth-discount-prospective-shadow"
        ),
        "historical_cost_stress_status": "5pct_monthly_bootstrap_lower_95_positive_18.57pct",
        "prospective_warning": (
            "v8.7 is paper-only: conservative outcome probability must reach 25% to "
            "reduce longshot bias; post-development T-1 settlements are required"
        ),
    }
    CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG = {
        **CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG,
        "version": "clv-ridge-v8.8-five-eighths-kelly-prospective-shadow",
        "kelly_fraction": 0.625,
        "maximum_single_stake": 15.0,
        "stake_challenger_of": "clv-ridge-v8.7-min25pct-probability-prospective-shadow",
        "historical_cost_stress_status": "LEGACY_UNFILTERED_QUOTE_EVIDENCE_INVALIDATED",
        "quote_sanity_audit": (
            "v8.10_retrained_max_price_ratio_1.15_5pct_block_lower_95_positive_14.37pct_"
            "but_2.5pct_positive_month_gate_failed"
        ),
        "temporal_dependence_gate": "superseded_by_v8.10_quote_sanity_audit",
        "prospective_warning": (
            "v8.8 is paper-only and now rejects execution quotes over 1.15x consensus; "
            "its earlier unfiltered ROI was inflated by stale or misaligned quotes, and "
            "post-development T-1 settlements are required"
        ),
    }
if (
    CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG
    and QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH.exists()
    and QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH.exists()
):
    _CLV_RIDGE_QUOTE_SANITY_DIRECT_MODEL = load_frozen_model(
        str(QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH)
    )
    _CLV_RIDGE_QUOTE_SANITY_MOVEMENT_MODEL = load_frozen_model(
        str(QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH)
    )
    _CLV_QUOTE_SANITY_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
        _CLV_RIDGE_QUOTE_SANITY_DIRECT_MODEL["model_sha256"],
        _CLV_RIDGE_QUOTE_SANITY_MOVEMENT_MODEL["model_sha256"],
    ]), separators=(",", ":")).encode()).hexdigest()
    CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG = {
        **CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG,
        "version": "clv-ridge-v8.11-quote-sanity-min2pct-clv-prospective-shadow",
        "ranker_model_filename": QUOTE_SANITY_MARKET_STRUCTURE_MODEL_PATH.name,
        "ranker_model_sha256": _CLV_QUOTE_SANITY_AGREEMENT_HASH,
        "ranker_training_window": _CLV_RIDGE_QUOTE_SANITY_DIRECT_MODEL["training_window"],
        "agreement_component_model_sha256": [
            _CLV_RIDGE_QUOTE_SANITY_DIRECT_MODEL["model_sha256"],
            _CLV_RIDGE_QUOTE_SANITY_MOVEMENT_MODEL["model_sha256"],
        ],
        "agreement_model_filename": QUOTE_SANITY_PROBABILITY_MOVEMENT_MODEL_PATH.name,
        "agreement_rule": "both_lower_clv_at_least_2pct_then_use_minimum",
        "minimum_lower_clv_pct": 2.0,
        "maximum_price_ratio": 1.15,
        "latest_retraining_gate": "FAILED_FOR_WINDOW_ENDING_2026_05_31",
        "historical_cost_stress_status": (
            "quote_sanitized_5pct_block_lower_95_positive_17.25pct"
        ),
        "lower_cost_stability_status": "2.5pct_positive_active_months_15_of_24",
        "leave_one_source_gate": "5pct_minimum_block_lower_95_positive_9.79pct",
        "stake_challenger_of": "clv-ridge-v8.8-five-eighths-kelly-prospective-shadow",
        "prospective_warning": (
            "v8.11 is paper-only: quotes above 1.15x consensus are rejected and both "
            "models must clear a 2% conservative CLV margin; retraining through May "
            "failed, so new T-1 settlements are required"
        ),
    }
    CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG = {
        **CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG,
        "version": "clv-ridge-v8.13-quote-sanity-three-quarter-kelly-prospective-shadow",
        "kelly_fraction": 0.75,
        "maximum_single_stake": 15.0,
        "stake_challenger_of": (
            "clv-ridge-v8.11-quote-sanity-min2pct-clv-prospective-shadow"
        ),
        "historical_cost_stress_status": (
            "quote_sanitized_5pct_profit_80.64_block_lower_95_positive_17.22pct"
        ),
        "lower_cost_stability_status": "2.5pct_block_lower_95_positive_10.68pct",
        "leave_one_source_gate": "5pct_minimum_block_lower_95_positive_9.67pct",
        "historical_risk_gate": "max_drawdown_12.84_max_daily_stake_16.77",
        "prospective_warning": (
            "v8.13 is paper-only: 0.75 Kelly raises exposure after all v8.11 quote "
            "and CLV gates; historical drawdown stayed below CNY 15, but retraining "
            "through May failed and prospective T-1 settlements are required"
        ),
    }
if (
    CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG
    and MARKET_CALIBRATED_MODEL_PATH.exists()
    and MARKET_CALIBRATED_PROBABILITY_MOVEMENT_MODEL_PATH.exists()
):
    _CLV_RIDGE_MARKET_CALIBRATED_DIRECT_MODEL = load_frozen_model(
        str(MARKET_CALIBRATED_MODEL_PATH)
    )
    _CLV_RIDGE_MARKET_CALIBRATED_MOVEMENT_MODEL = load_frozen_model(
        str(MARKET_CALIBRATED_PROBABILITY_MOVEMENT_MODEL_PATH)
    )
    _CLV_MARKET_CALIBRATED_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
        _CLV_RIDGE_MARKET_CALIBRATED_DIRECT_MODEL["model_sha256"],
        _CLV_RIDGE_MARKET_CALIBRATED_MOVEMENT_MODEL["model_sha256"],
    ]), separators=(",", ":")).encode()).hexdigest()
    CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG = {
        **CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG,
        "version": "clv-ridge-v8.18-training-market-calibrated-kelly-prospective-shadow",
        "ranker_model_filename": MARKET_CALIBRATED_MODEL_PATH.name,
        "ranker_model_sha256": _CLV_MARKET_CALIBRATED_AGREEMENT_HASH,
        "ranker_training_window": _CLV_RIDGE_MARKET_CALIBRATED_DIRECT_MODEL["training_window"],
        "agreement_component_model_sha256": [
            _CLV_RIDGE_MARKET_CALIBRATED_DIRECT_MODEL["model_sha256"],
            _CLV_RIDGE_MARKET_CALIBRATED_MOVEMENT_MODEL["model_sha256"],
        ],
        "agreement_model_filename": MARKET_CALIBRATED_PROBABILITY_MOVEMENT_MODEL_PATH.name,
        "staking_probability_profile": "training_market_platt",
        "market_probability_training_scope": "all_prior_9m_broad_candidates",
        "stake_challenger_of": (
            "clv-ridge-v8.13-quote-sanity-three-quarter-kelly-prospective-shadow"
        ),
        "historical_cost_stress_status": (
            "5pct_profit_119.44_block_lower_95_positive_21.39pct"
        ),
        "lower_cost_stability_status": "2.5pct_profit_114.24_15_of_24_positive_months",
        "leave_one_source_gate": "2.5pct_minimum_block_lower_95_positive_5.47pct",
        "historical_risk_gate": "max_drawdown_22.29_below_25_max_daily_27.92_below_50",
        "profit_concentration_gate": (
            "FAILED_remove_top5_block_lower_95_negative_8.61pct_2.5cost_"
            "negative_3.19pct_5cost"
        ),
        "prospective_warning": (
            "v8.18 is paper-only: CLV models select positions while an all-candidate "
            "prior-window market calibration sizes Kelly exposure; historical risk "
            "limits passed, but fresh T-1 settlements are required"
        ),
    }
    CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG = {
        **CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG,
        "version": "clv-ridge-v8.21-daily-league-cap15-prospective-shadow",
        "maximum_daily_league_stake": 15.0,
        "stake_challenger_of": (
            "clv-ridge-v8.18-training-market-calibrated-kelly-prospective-shadow"
        ),
        "historical_cost_stress_status": (
            "5pct_profit_123.96_block_lower_95_positive_25.96pct"
        ),
        "lower_cost_stability_status": "2.5pct_profit_118.76_16_of_24_positive_months",
        "leave_one_source_gate": "2.5pct_minimum_block_lower_95_positive_5.47pct",
        "leave_one_league_gate": "2.5pct_minimum_block_lower_95_positive_2.57pct",
        "historical_risk_gate": "max_drawdown_22.29_max_daily_and_league_stake_15.00",
        "profit_concentration_gate": (
            "FAILED_remove_top5_block_lower_95_negative_22.71pct_2.5cost_"
            "negative_15.95pct_5cost"
        ),
        "research_evidence_status": "LEGACY_SURVIVOR_REJECTED_BY_NEW_CONCENTRATION_GATE",
        "prospective_warning": (
            "v8.21 is paper-only: it preserves v8.18 selection and probability models, "
            "then proportionally caps same-day same-league exposure at CNY 15; "
            "the later top-five-winner deletion audit failed, so this policy is "
            "collection-only and cannot be promoted"
        ),
    }
    CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG = {
        **CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG,
        "version": "clv-ridge-v8.27-dual-cost-calibrated-governance-prospective-shadow",
        "staking_probability_profile": "opening_market_consensus",
        "stress_exchange_commission_rate": 0.05,
        "dual_cost_stability_rule": (
            "same_match_same_outcome_passes_2.5pct_and_5pct_cost_models_with_"
            "minimum_frozen_stake_0.10"
        ),
        "governance_gate_profile": "closing_probability_calibrated",
        "profit_concentration_gate": (
            "PASSED_2.5pct_top5_percentile_98.60_top10_percentile_96.70_"
            "positive_month_percentile_91.80"
        ),
        "research_evidence_status": "HISTORICAL_RESEARCH_SURVIVOR_PROSPECTIVE_REQUIRED",
        "stake_challenger_of": (
            "clv-ridge-v8.21-daily-league-cap15-prospective-shadow"
        ),
        "prospective_warning": (
            "v8.27 is paper-only: market consensus sizes Kelly exposure, both 2.5% "
            "and 5% cost assumptions must select the same outcome, and historical "
            "calibrated governance passed; fresh immutable T-1 settlements are still "
            "required before any promotion"
        ),
    }
    CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG = {
        **CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG,
        "version": "clv-ridge-v8.28-restored-calibrated-governance-prospective-shadow",
        "governance_gate_profile": "closing_probability_calibrated",
        "profit_concentration_gate": (
            "PASSED_2.5pct_top5_percentile_93.60_top10_percentile_96.50_"
            "positive_month_percentile_97.65_AND_5pct_top5_percentile_96.75_"
            "top10_percentile_98.25_positive_month_percentile_99.55"
        ),
        "research_evidence_status": "HISTORICAL_RESEARCH_SURVIVOR_PROSPECTIVE_REQUIRED",
        "selection_challenger_of": (
            "clv-ridge-v8.27-dual-cost-calibrated-governance-prospective-shadow"
        ),
        "dual_cost_stability_rule": "removed_after_clv_attribution_audit",
        "historical_clv_attribution": (
            "2.5pct_118_positions_closing_expected_profit_26.38_roi_7.77pct_"
            "late_expected_roi_5.34pct"
        ),
        "historical_cost_stress_status": (
            "5pct_108_positions_profit_123.96_block_lower_95_positive_25.96pct_"
            "closing_expected_profit_24.69_roi_7.86pct"
        ),
        "prospective_warning": (
            "v8.28 is paper-only: it restores the independently valid v8.21 signal "
            "path after the absolute winner-deletion gate was shown to reject 99% "
            "of positive closing-probability simulations; calibrated governance, "
            "CNY 100 daily and CNY 15 league-day caps remain active, and fresh "
            "immutable T-1 settlements are required before any promotion"
        ),
    }
    if (
        MULTI_HORIZON_LONG_MODEL_PATH.exists()
        and MULTI_HORIZON_LONG_MOVEMENT_MODEL_PATH.exists()
    ):
        _CLV_RIDGE_LONG_DIRECT_MODEL = load_frozen_model(
            str(MULTI_HORIZON_LONG_MODEL_PATH)
        )
        _CLV_RIDGE_LONG_MOVEMENT_MODEL = load_frozen_model(
            str(MULTI_HORIZON_LONG_MOVEMENT_MODEL_PATH)
        )
        _CLV_LONG_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
            _CLV_RIDGE_LONG_DIRECT_MODEL["model_sha256"],
            _CLV_RIDGE_LONG_MOVEMENT_MODEL["model_sha256"],
        ]), separators=(",", ":")).encode()).hexdigest()
        CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG = {
            **CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG,
            "version": "clv-ridge-v8.33-multi-horizon-core-satellite-prospective-shadow",
            "decision_model": "frozen_json_clv_multi_horizon",
            "long_horizon_direct_model_filename": MULTI_HORIZON_LONG_MODEL_PATH.name,
            "long_horizon_movement_model_filename": (
                MULTI_HORIZON_LONG_MOVEMENT_MODEL_PATH.name
            ),
            "long_horizon_model_sha256": _CLV_LONG_AGREEMENT_HASH,
            "long_horizon_training_window": _CLV_RIDGE_LONG_DIRECT_MODEL["training_window"],
            "long_horizon_training_months": 18,
            "long_horizon_validation_months": 9,
            "satellite_staking_probability_profile": "lower_clv",
            "satellite_minimum_lower_clv_pct": 2.0,
            "satellite_minimum_staking_probability": 0.0,
            "satellite_kelly_fraction": 0.3125,
            "satellite_rule": (
                "use_18m9m_only_when_9m3m_core_is_ineligible_same_snapshot_"
                "same_outcome_no_reallocation_after_settlement"
            ),
            "selection_challenger_of": (
                "clv-ridge-v8.28-restored-calibrated-governance-prospective-shadow"
            ),
            "historical_clv_attribution": (
                "2.5pct_182_positions_closing_expected_profit_28.89_roi_7.83pct_"
                "late_expected_profit_5.21_roi_5.85pct"
            ),
            "historical_cost_stress_status": (
                "5pct_168_positions_profit_134.89_closing_expected_profit_26.68_"
                "block_lower_95_positive_25.87pct"
            ),
            "historical_risk_gate": (
                "2.5pct_max_drawdown_22.29_source_lower_12.14_league_lower_6.21_"
                "team_lower_14.03"
            ),
            "profit_concentration_gate": (
                "PASSED_2.5pct_top5_percentile_95.05_top10_percentile_96.85_"
                "positive_month_percentile_99.80_AND_5pct_top5_percentile_98.45_"
                "top10_percentile_99.15_positive_month_percentile_100"
            ),
            "prospective_warning": (
                "v8.33 is paper-only: a 9m3m market-calibrated core is supplemented "
                "only when an independently frozen 18m9m lower-CLV model qualifies; "
                "the satellite uses 0.3125 Kelly, total daily exposure is CNY 100, "
                "same-day league exposure is CNY 15, and no real orders are created"
            ),
        }
EXPERIMENT_POLICY_CONFIGS = (
    CONTROL_POLICY_CONFIG,
    POLICY_CONFIG,
    CLV_RIDGE_POLICY_CONFIG,
    CLV_RIDGE_HALF_KELLY_POLICY_CONFIG,
    CLV_RIDGE_MARKET_STRUCTURE_POLICY_CONFIG,
    CLV_RIDGE_MODEL_AGREEMENT_POLICY_CONFIG,
    *((CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG,)
      if CLV_RIDGE_ADAPTIVE_AGREEMENT_POLICY_CONFIG else ()),
    *((CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG,)
      if CLV_RIDGE_MONTH_STABLE_POLICY_CONFIG else ()),
    *((CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG,)
      if CLV_RIDGE_MIN_PROBABILITY_POLICY_CONFIG else ()),
    *((CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG,)
      if CLV_RIDGE_FIVE_EIGHTHS_KELLY_POLICY_CONFIG else ()),
    *((CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG,)
      if CLV_RIDGE_QUOTE_SANITY_POLICY_CONFIG else ()),
    *((CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG,)
      if CLV_RIDGE_THREE_QUARTER_KELLY_POLICY_CONFIG else ()),
    *((CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG,)
      if CLV_RIDGE_MARKET_CALIBRATED_POLICY_CONFIG else ()),
    *((CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG,)
      if CLV_RIDGE_DAILY_LEAGUE_CAP_POLICY_CONFIG else ()),
    *((CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG,)
      if CLV_RIDGE_CALIBRATED_GOVERNANCE_POLICY_CONFIG else ()),
    *((CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG,)
      if CLV_RIDGE_RESTORED_CALIBRATED_POLICY_CONFIG else ()),
    *((CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG,)
      if CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG else ()),
)
EXPERIMENT_NAME = "v3.1-v4.1-market-vs-v6.2-v6.3-v6.6-v7.6-v8.1-v8.5-v8.7-v8.8-v8.11-v8.13-v8.18-v8.21-v8.27-v8.28-v8.33-clv-ridge-shadow"

CHINA_TZ = ZoneInfo("Asia/Shanghai")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_minutes(later: datetime, earlier: str | datetime) -> float:
    return (later - _time(earlier)).total_seconds() / 60.0


def _devig(row: dict[str, Any]) -> dict[str, float] | None:
    try:
        inverse = {outcome: 1.0 / float(row[f"{outcome}_odds"]) for outcome in OUTCOMES}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    total = sum(inverse.values())
    return {outcome: inverse[outcome] / total for outcome in OUTCOMES} if total > 0 else None


def _robust_consensus(rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]] | None:
    probabilities = [value for row in rows if (value := _devig(row)) is not None]
    if not probabilities:
        return None
    centers = {outcome: median(item[outcome] for item in probabilities) for outcome in OUTCOMES}
    total = sum(centers.values())
    consensus = {outcome: centers[outcome] / total for outcome in OUTCOMES}
    dispersion = {
        outcome: 1.4826 * median(abs(item[outcome] - consensus[outcome]) for item in probabilities)
        for outcome in OUTCOMES
    }
    return consensus, dispersion


def _execution_cost_rate(bookmaker_key: str, config: dict[str, Any]) -> float:
    keys = {str(value).lower() for value in config.get("exchange_bookmaker_keys", [])}
    return float(config.get("exchange_commission_rate", 0.0)) if bookmaker_key.lower() in keys else 0.0


def _net_execution_odds(raw_odds: float, cost_rate: float) -> float:
    return 1.0 + (float(raw_odds) - 1.0) * (1.0 - cost_rate)


def _slippage_adjusted_odds(net_odds: float, slippage_rate: float) -> float:
    return 1.0 + (float(net_odds) - 1.0) * (1.0 - slippage_rate)


def _historical_bookmaker_feature(bookmaker_key: str) -> str:
    key = bookmaker_key.lower()
    aliases = {
        "bet365": "B365", "pinnacle": "PS", "williamhill": "WH",
        "betfair_ex_eu": "BFE", "betfair_ex_uk": "BFE",
        "smarkets": "BFE", "matchbook": "BFE",
    }
    return aliases.get(key, bookmaker_key.upper())


def _market_candidates(
    inputs: dict[str, Any], config: dict[str, Any],
    exchange_commission_override: float | None = None,
) -> list[tuple[Any, ...]]:
    books = []
    for source in inputs["books"]:
        row = dict(source)
        if exchange_commission_override is not None:
            keys = {str(value).lower() for value in config.get("exchange_bookmaker_keys", [])}
            cost_rate = (
                exchange_commission_override
                if str(row["bookmaker_key"]).lower() in keys else 0.0
            )
            row["execution_cost_rate"] = cost_rate
            for outcome in OUTCOMES:
                row[f"{outcome}_odds"] = _net_execution_odds(
                    float(row[f"raw_{outcome}_odds"]), cost_rate
                )
        books.append(row)
    possible = []
    for outcome in OUTCOMES:
        execution = max(books, key=lambda row: float(row[f"{outcome}_odds"]))
        references = [
            row for row in books
            if row["bookmaker_key"] != execution["bookmaker_key"]
        ]
        robust = _robust_consensus(references)
        if robust is None or len(references) < int(config["minimum_reference_bookmakers"]):
            continue
        probabilities, dispersions = robust
        price = _slippage_adjusted_odds(
            float(execution[f"{outcome}_odds"]), float(config["slippage_rate"])
        )
        probability = float(probabilities[outcome])
        ref_price = 1.0 / probability
        pure_probability = (
            float(inputs["model_probabilities"][outcome])
            if inputs["model_probabilities"] else probability
        )
        residual_probabilities = _market_residual_probabilities(
            probabilities, inputs["model_probabilities"],
            float(config["model_residual_reliability"]),
            float(config["maximum_probability_shift"]),
        )
        residual_probability = residual_probabilities[outcome]
        disagreement = (
            abs(pure_probability - probability)
            if inputs["model_probabilities"] else 0.0
        )
        uncertainty = (
            float(config["uncertainty_floor"])
            + float(config["dispersion_uncertainty_multiplier"]) * dispersions[outcome]
            + float(config["model_disagreement_uncertainty_multiplier"]) * disagreement
        )
        conservative_probability = max(0.001, residual_probability - uncertainty)
        ev = residual_probability * price - 1.0
        conservative_ev = conservative_probability * price - 1.0
        reasons = []
        if price < float(config["minimum_odds"]) or price > float(config["maximum_odds"]):
            reasons.append("execution_price_outside_range")
        if probability < float(config.get("minimum_reference_probability", 0.0)):
            reasons.append("reference_probability_below_minimum")
        if price < ref_price * float(config["minimum_price_ratio"]):
            reasons.append("execution_price_not_2pct_above_consensus_fair_price")
        maximum_price_ratio = config.get("maximum_price_ratio")
        if maximum_price_ratio is not None and price * probability > float(maximum_price_ratio):
            reasons.append("execution_price_ratio_above_quote_sanity_limit")
        if conservative_ev < float(config["minimum_conservative_ev"]):
            reasons.append("conservative_ev<2pct")
        possible.append((
            outcome, price, ref_price, probability, pure_probability,
            residual_probability, conservative_probability, ev, conservative_ev,
            reasons, execution, references, dispersions[outcome],
        ))
    return possible


def _clv_feature_row(
    selected: tuple[Any, ...], match: dict[str, Any],
) -> dict[str, Any]:
    execution = selected[10]
    row = {
        "probability": selected[3],
        "conservative_probability": selected[6],
        "odds": selected[1],
        "raw_odds": execution[f"raw_{selected[0]}_odds"],
        "conservative_ev_pct": selected[8] * 100.0,
        "reference_dispersion": selected[12],
        "reference_bookmakers": len(selected[11]),
        "execution_cost_rate": execution["execution_cost_rate"],
        "outcome": selected[0],
        "odds_band": odds_band(selected[1]),
        "source_type": (
            "exchange" if execution["execution_cost_rate"] > 0 else "sportsbook"
        ),
        "execution_bookmaker": _historical_bookmaker_feature(
            execution["bookmaker_key"]
        ),
        "league": str(match.get("league") or ""),
    }
    row.update(market_structure_features(row))
    return row


def _score_clv_pair(
    feature_row: dict[str, Any], direct_filename: str | None,
    movement_filename: str | None, model_sha256: str | None,
) -> dict[str, Any]:
    artifact_dir = Path(__file__).with_name("model_artifacts")
    direct_path = artifact_dir / direct_filename if direct_filename else None
    direct = score_opening_features(feature_row, direct_path)
    predicted = float(direct["predicted_closing_edge_pct"])
    lower = float(direct["lower_predicted_closing_edge_pct"])
    market_probabilities = []
    if direct.get("estimated_probability_from_training_market") is not None:
        market_probabilities.append(float(
            direct["estimated_probability_from_training_market"]
        ))
    model_sha = str(direct["model_sha256"])
    if movement_filename:
        agreement_path = artifact_dir / movement_filename
        agreement = score_opening_features(feature_row, agreement_path)
        predicted = (
            predicted + float(agreement["predicted_closing_edge_pct"])
        ) / 2.0
        lower = min(
            lower, float(agreement["lower_predicted_closing_edge_pct"])
        )
        if agreement.get("estimated_probability_from_training_market") is not None:
            market_probabilities.append(float(
                agreement["estimated_probability_from_training_market"]
            ))
        model_sha = str(model_sha256 or model_sha)
    return {
        "predicted_clv": predicted,
        "lower_predicted_clv": lower,
        "market_staking_probabilities": market_probabilities,
        "model_sha256": model_sha,
    }


def _score_clv_agreement(
    feature_row: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    uses_agreement = config.get("decision_model") in {
        "frozen_json_clv_agreement", "frozen_json_clv_multi_horizon",
    }
    return _score_clv_pair(
        feature_row,
        str(config["ranker_model_filename"])
        if config.get("ranker_model_filename") else None,
        str(config["agreement_model_filename"])
        if uses_agreement and config.get("agreement_model_filename") else None,
        str(config["ranker_model_sha256"])
        if config.get("ranker_model_sha256") else None,
    )


def _score_long_horizon_agreement(
    feature_row: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    return _score_clv_pair(
        feature_row,
        str(config["long_horizon_direct_model_filename"]),
        str(config["long_horizon_movement_model_filename"]),
        str(config["long_horizon_model_sha256"]),
    )


def _dual_cost_stability_blockers(
    inputs: dict[str, Any], config: dict[str, Any], match: dict[str, Any],
    selected_outcome: str,
) -> list[str]:
    stress_rate = config.get("stress_exchange_commission_rate")
    if stress_rate is None:
        return []
    possible = _market_candidates(inputs, config, float(stress_rate))
    if not possible:
        return ["stress_cost_no_valid_outcome"]
    selected = max(possible, key=lambda item: (item[8], item[1]))
    if selected[0] != selected_outcome:
        return ["stress_cost_selected_outcome_changed"]
    if selected[9]:
        return ["stress_cost_market_gate_failed"]
    try:
        score = _score_clv_agreement(_clv_feature_row(selected, match), config)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return [f"stress_cost_ranker_unavailable:{type(exc).__name__}"]
    if float(score["lower_predicted_clv"]) < float(config["minimum_lower_clv_pct"]):
        return ["stress_cost_lower_clv_below_policy_minimum"]
    lower_probability = min(
        0.999,
        max(0.001, (1.0 + float(score["lower_predicted_clv"]) / 100.0) / selected[1]),
    )
    if lower_probability < float(config.get("minimum_staking_probability", 0.0)):
        return ["stress_cost_probability_below_policy_minimum"]
    staking_probability = float(selected[3])
    full_kelly = max(
        0.0,
        (staking_probability * float(selected[1]) - 1.0)
        / max(float(selected[1]) - 1.0, 1e-9),
    )
    multiplier = (
        float(config.get("minimum_depth_stake_multiplier", 1.0))
        if len(selected[11]) == int(config.get("minimum_reference_depth", 0))
        else 1.0
    )
    requested = (
        float(config["daily_budget"]) * float(config["kelly_fraction"])
        * full_kelly * multiplier
    )
    return [] if requested >= 0.10 else ["stress_cost_kelly_stake_below_minimum"]


def _market_residual_probabilities(
    reference: dict[str, float],
    model: dict[str, float] | None,
    reliability: float,
    maximum_shift: float,
) -> dict[str, float]:
    if not model:
        return dict(reference)
    lower = {outcome: max(0.001, reference[outcome] - maximum_shift) for outcome in OUTCOMES}
    upper = {outcome: min(0.999, reference[outcome] + maximum_shift) for outcome in OUTCOMES}
    adjusted = {
        outcome: min(upper[outcome], max(
            lower[outcome], reference[outcome] + reliability * (model[outcome] - reference[outcome])
        ))
        for outcome in OUTCOMES
    }
    for _ in range(6):
        remainder = 1.0 - sum(adjusted.values())
        if abs(remainder) < 1e-12:
            break
        eligible = [
            outcome for outcome in OUTCOMES
            if (remainder > 0 and adjusted[outcome] < upper[outcome] - 1e-12)
            or (remainder < 0 and adjusted[outcome] > lower[outcome] + 1e-12)
        ]
        if not eligible:
            break
        share = remainder / len(eligible)
        for outcome in eligible:
            adjusted[outcome] = min(upper[outcome], max(lower[outcome], adjusted[outcome] + share))
    return adjusted


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _settlement_day_bootstrap_roi(
    positions: list[dict[str, Any]], iterations: int = 5000, seed: int = 42,
) -> dict[str, Any]:
    settled = [item for item in positions if item.get("status") == "SETTLED"]
    days = sorted({str(item["settlement_date"]) for item in settled})
    if len(settled) < 30 or len(days) < 10:
        return {
            "status": "INSUFFICIENT_SAMPLE", "settled_bets": len(settled),
            "settlement_days": len(days), "minimum_bets": 30, "minimum_days": 10,
            "lower_95_pct": None, "median_pct": None, "upper_95_pct": None,
        }
    groups = [[item for item in settled if item["settlement_date"] == day] for day in days]
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample = [groups[rng.randrange(len(groups))] for _ in groups]
        flat = [item for group in sample for item in group]
        stake = sum(float(item["stake"]) for item in flat)
        estimates.append(sum(float(item["profit"]) for item in flat) / stake if stake else 0.0)
    return {
        "status": "READY", "settled_bets": len(settled), "settlement_days": len(days),
        "iterations": iterations, "seed": seed,
        "lower_95_pct": round(float(_quantile(estimates, 0.025)) * 100, 4),
        "median_pct": round(float(_quantile(estimates, 0.5)) * 100, 4),
        "upper_95_pct": round(float(_quantile(estimates, 0.975)) * 100, 4),
    }


class NamedBookGapResearchService:
    """Stores immutable, timestamp-aligned market-gap observations; never allocates capital."""

    def __init__(self, database: Database = db, repository: Repository | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)

    def ensure_policy(self, policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        registered_config = policy_config or POLICY_CONFIG
        source = "\n".join((inspect.getsource(self.capture), inspect.getsource(self._inputs),
                             inspect.getsource(self.report), inspect.getsource(self._paper_portfolio),
                             inspect.getsource(_devig), inspect.getsource(_robust_consensus),
                             inspect.getsource(score_opening_features), inspect.getsource(odds_band),
                             inspect.getsource(market_structure_features),
                             inspect.getsource(_historical_bookmaker_feature),
                             inspect.getsource(_market_candidates),
                             inspect.getsource(_clv_feature_row),
                             inspect.getsource(_score_clv_pair),
                             inspect.getsource(_score_clv_agreement),
                             inspect.getsource(_score_long_horizon_agreement),
                             inspect.getsource(_dual_cost_stability_blockers),
                             inspect.getsource(_market_residual_probabilities),
                             inspect.getsource(_settlement_day_bootstrap_roi)))
        source_sha = hashlib.sha256(source.encode()).hexdigest()
        policy_hash = hashlib.sha256(_canonical({"config": registered_config, "source_sha256": source_sha}).encode()).hexdigest()
        policy_id = f"named-book-gap-{policy_hash[:20]}"
        with self.db.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO named_book_gap_policies
                (policy_id,policy_hash,config_json,source_sha256,registered_at) VALUES(?,?,?,?,?)""", (
                policy_id, policy_hash, _canonical(registered_config), source_sha, _now().isoformat(),
            ))
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        return {**dict(row), "config": json.loads(row["config_json"])}

    def _inputs(self, match_id: int, decided_at: datetime, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with self.db.connect() as connection:
            fetched_at = connection.execute("""SELECT MAX(captured_at) value
                FROM prospective_external_odds_snapshots
                WHERE match_id=? AND capture_window='T_MINUS_1H'
                  AND datetime(captured_at)<=datetime(?)""", (match_id, decided_at.isoformat())).fetchone()["value"]
            rows = connection.execute("""SELECT * FROM prospective_external_odds_snapshots
                WHERE match_id=? AND captured_at=? ORDER BY bookmaker_key""", (match_id, fetched_at)).fetchall() if fetched_at else []
            pure_model = connection.execute("""SELECT * FROM model_predictions
                WHERE match_id=? AND model_name='baseline' AND datetime(predicted_at)<=datetime(?)
                ORDER BY predicted_at DESC,id DESC LIMIT 1""", (
                match_id, fetched_at or decided_at.isoformat(),
            )).fetchone()
        if not fetched_at or not rows:
            return None, "missing_external_snapshot"
        if _age_minutes(decided_at, fetched_at) > float(config["maximum_snapshot_age_minutes"]):
            return None, "stale_external_snapshot"
        books: dict[str, dict[str, Any]] = {}
        for raw in rows:
            row = dict(raw)
            key = str(row.get("bookmaker_key") or "").lower().strip()
            quote_age = _age_minutes(decided_at, row["bookmaker_last_update"])
            if key and _devig(row) is not None and -2 <= quote_age <= float(
                config["maximum_bookmaker_last_update_age_minutes"]
            ):
                books.setdefault(key, row)
        minimum_books = int(config["minimum_reference_bookmakers"]) + 1
        if len(books) < minimum_books:
            return None, f"fresh_bookmakers<{minimum_books}"
        updates = [_time(row["bookmaker_last_update"]) for row in books.values()]
        newest = max(updates)
        books = {
            key: row for key, row in books.items()
            if (newest - _time(row["bookmaker_last_update"])).total_seconds() / 60.0
            <= float(config["maximum_bookmaker_update_skew_minutes"])
        }
        if len(books) < minimum_books:
            return None, f"aligned_bookmakers<{minimum_books}"
        adjusted_books = []
        for row in books.values():
            adjusted = dict(row)
            cost_rate = _execution_cost_rate(str(row["bookmaker_key"]), config)
            adjusted["execution_cost_rate"] = cost_rate
            for outcome in OUTCOMES:
                raw_odds = float(row[f"{outcome}_odds"])
                adjusted[f"raw_{outcome}_odds"] = raw_odds
                adjusted[f"{outcome}_odds"] = _net_execution_odds(raw_odds, cost_rate)
            adjusted_books.append(adjusted)
        model_probabilities = None
        if pure_model:
            model_probabilities = {outcome: float(pure_model[f"p_{outcome}"]) for outcome in OUTCOMES}
        return {"fetched_at": fetched_at, "books": adjusted_books,
                "model_probabilities": model_probabilities}, ""

    def capture(self, limit: int = 100, as_of: str | datetime | None = None,
                policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        decided_at = _time(as_of or _now())
        policy = self.ensure_policy(policy_config)
        config = policy["config"]
        counters: Counter[str] = Counter()
        inserted = candidates = 0
        for match in self.repository.list_active_official_matches(max(1, min(limit, 500))):
            kickoff = _time(match["kickoff_time"])
            minutes = (kickoff - decided_at).total_seconds() / 60.0
            lower = float(config["primary_horizon_minutes"])
            upper = lower + float(config["horizon_tolerance_minutes"])
            if not lower <= minutes <= upper:
                counters["outside_primary_horizon"] += 1
                continue
            inputs, blocker = self._inputs(int(match["id"]), decided_at, config)
            if inputs is None:
                counters[blocker] += 1
                continue
            possible = _market_candidates(inputs, config)
            if not possible:
                counters["insufficient_valid_outcomes"] += 1
                continue
            selected = max(possible, key=lambda item: (item[8], item[1]))
            predicted_clv = lower_predicted_clv = ranker_model_sha = None
            horizon_role = "single_horizon"
            effective_kelly_fraction = float(config["kelly_fraction"])
            stored_expected_ev = selected[7]
            stored_conservative_ev = selected[8]
            stored_conservative_probability = selected[6]
            if config.get("decision_model") in {
                "frozen_json_clv_ridge", "frozen_json_clv_agreement",
                "frozen_json_clv_multi_horizon",
            }:
                feature_row = _clv_feature_row(selected, match)
                try:
                    ranker = _score_clv_agreement(feature_row, config)
                    core_lower = float(ranker["lower_predicted_clv"])
                    core_probability = min(
                        0.999, max(0.001, (1.0 + core_lower / 100.0) / selected[1])
                    )
                    core_blockers = []
                    if core_lower < float(config["minimum_lower_clv_pct"]):
                        core_blockers.append("predicted_lower_clv_below_policy_minimum")
                    if core_probability < float(config.get("minimum_staking_probability", 0.0)):
                        core_blockers.append("conservative_probability_below_policy_minimum")
                    market_probabilities = list(ranker["market_staking_probabilities"])
                    if config.get("staking_probability_profile") == "training_market_platt":
                        if market_probabilities:
                            core_probability = min(market_probabilities)
                        else:
                            core_blockers.append("training_market_probability_unavailable")
                    elif config.get("staking_probability_profile") == "opening_market_consensus":
                        core_probability = float(selected[3])

                    chosen = ranker
                    chosen_probability = core_probability
                    if (
                        config.get("decision_model") == "frozen_json_clv_multi_horizon"
                        and core_blockers
                    ):
                        long_ranker = _score_long_horizon_agreement(feature_row, config)
                        long_lower = float(long_ranker["lower_predicted_clv"])
                        long_probability = min(
                            0.999,
                            max(0.001, (1.0 + long_lower / 100.0) / selected[1]),
                        )
                        long_blockers = []
                        if long_lower < float(config["satellite_minimum_lower_clv_pct"]):
                            long_blockers.append("predicted_lower_clv_below_policy_minimum")
                        if long_probability < float(
                            config.get("satellite_minimum_staking_probability", 0.0)
                        ):
                            long_blockers.append("conservative_probability_below_policy_minimum")
                        if not long_blockers:
                            chosen = long_ranker
                            chosen_probability = long_probability
                            horizon_role = "18m9m_satellite"
                            effective_kelly_fraction = float(config["satellite_kelly_fraction"])
                        else:
                            selected[9].extend(
                                f"core_horizon:{reason}" for reason in core_blockers
                            )
                            selected[9].extend(
                                f"long_horizon:{reason}" for reason in long_blockers
                            )
                    else:
                        selected[9].extend(core_blockers)
                        if config.get("decision_model") == "frozen_json_clv_multi_horizon":
                            horizon_role = "9m3m_core"

                    predicted_clv = float(chosen["predicted_clv"])
                    lower_predicted_clv = float(chosen["lower_predicted_clv"])
                    ranker_model_sha = str(chosen["model_sha256"])
                    stored_expected_ev = predicted_clv / 100.0
                    stored_conservative_ev = lower_predicted_clv / 100.0
                    stored_conservative_probability = chosen_probability
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    selected[9].append(f"clv_ranker_unavailable:{type(exc).__name__}")
            if not selected[9]:
                selected[9].extend(_dual_cost_stability_blockers(
                    inputs, config, match, str(selected[0])
                ))
            action = "CANDIDATE" if not selected[9] else "NO_BET"
            execution = selected[10]
            references = selected[11]
            reference_keys = sorted(str(row["bookmaker_key"]) for row in references)
            payload = {
                "policy_id": policy["policy_id"], "match_id": match["id"], "external_fetched_at": inputs["fetched_at"],
                "selected_outcome": selected[0], "bet365_odds": selected[1], "pinnacle_odds": selected[2],
                "reference_probability": selected[3], "pure_model_probability": selected[4],
                "residual_probability": selected[5], "conservative_probability": stored_conservative_probability,
                "expected_ev": stored_expected_ev, "conservative_ev": stored_conservative_ev, "action": action,
                "execution_bookmaker_key": execution["bookmaker_key"],
                "reference_bookmakers": reference_keys,
                "snapshot_payload_hash": execution["payload_hash"],
                "raw_execution_odds": execution[f"raw_{selected[0]}_odds"],
                "execution_cost_rate": execution["execution_cost_rate"],
                "predicted_closing_edge_pct": predicted_clv,
                "lower_predicted_closing_edge_pct": lower_predicted_clv,
                "ranker_model_sha256": ranker_model_sha,
                "horizon_role": horizon_role,
                "effective_kelly_fraction": effective_kelly_fraction,
            }
            payload_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
            try:
                with self.db.connect() as connection:
                    connection.execute("""INSERT INTO named_book_gap_decisions
                        (decision_id,policy_id,match_id,official_match_id,external_fetched_at,bet365_last_update,pinnacle_last_update,
                         decided_at,kickoff_time,minutes_to_kickoff,selected_outcome,bet365_odds,pinnacle_odds,reference_probability,
                         expected_ev,action,blockers_json,payload_hash,created_at,pure_model_probability,
                         residual_probability,conservative_probability,conservative_ev,slippage_rate,
                         execution_bookmaker,execution_bookmaker_key,reference_method,reference_bookmakers_json,
                         reference_dispersion,snapshot_payload_hash,raw_execution_odds,execution_cost_rate,
                         predicted_closing_edge_pct,lower_predicted_closing_edge_pct,ranker_model_sha256,
                         horizon_role,effective_kelly_fraction)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        str(uuid.uuid4()), policy["policy_id"], match["id"], match["official_match_id"], inputs["fetched_at"],
                        execution["bookmaker_last_update"], max(row["bookmaker_last_update"] for row in references),
                        decided_at.isoformat(), match["kickoff_time"], minutes,
                        selected[0], selected[1], selected[2], selected[3], stored_expected_ev, action,
                        _canonical(selected[9]), payload_hash, _now().isoformat(), selected[4], selected[5],
                        stored_conservative_probability, stored_conservative_ev,
                        float(config["slippage_rate"]), execution["bookmaker"],
                        execution["bookmaker_key"], config["reference_method"], _canonical(reference_keys),
                        selected[12], execution["payload_hash"], execution[f"raw_{selected[0]}_odds"],
                        execution["execution_cost_rate"], predicted_clv, lower_predicted_clv, ranker_model_sha,
                        horizon_role, effective_kelly_fraction,
                    ))
                inserted += 1
                candidates += int(action == "CANDIDATE")
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    counters["duplicate_decision"] += 1
                else:
                    raise
        report = self.report(policy["policy_id"], decided_at)
        return {"matches": len(self.repository.list_active_official_matches(limit)), "decisions": inserted,
                "predictions": candidates, "blocker_counts": [{"reason": key, "matches": value} for key, value in counters.most_common()],
                "report": report, "warnings": report["decision_reasons"]}

    def capture_experiment(self, limit: int = 100, as_of: str | datetime | None = None) -> dict[str, Any]:
        frozen_at = _time(as_of or _now())
        reports = [self.capture(limit, frozen_at, config) for config in EXPERIMENT_POLICY_CONFIGS]
        return {
            "experiment": EXPERIMENT_NAME,
            "matches": max((int(row.get("matches") or 0) for row in reports), default=0),
            "decisions": sum(int(row.get("decisions") or 0) for row in reports),
            "predictions": sum(int(row.get("predictions") or 0) for row in reports),
            "policies": reports,
            "blocker_counts": [
                {"policy_version": row["report"]["policy"]["config"]["version"], **blocker}
                for row in reports for blocker in row.get("blocker_counts", [])
            ],
            "warnings": sorted({warning for row in reports for warning in row.get("warnings", [])}),
        }

    def experiment_report(self) -> dict[str, Any]:
        reports = [self.report(self.ensure_policy(config)["policy_id"]) for config in EXPERIMENT_POLICY_CONFIGS]
        return {
            "experiment": EXPERIMENT_NAME,
            "selection_locked_before_future_results": True,
            "policies": reports,
            "comparison_ready": all(row["settled_selections"] >= 200 for row in reports),
            "guardrail": "All policies consume the same prospective snapshot; none places real orders.",
        }

    def report(
        self, policy_id: str | None = None, as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        policy = self.ensure_policy() if policy_id is None else self._policy(policy_id)
        observed_at = _time(as_of or _now())
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,m.league,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at)
                       AND datetime(r.settled_at)<=datetime(?) THEN r.outcome END actual_outcome,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at)
                       AND datetime(r.settled_at)<=datetime(?) THEN r.settled_at END result_settled_at
                FROM named_book_gap_decisions d
                JOIN matches m ON m.id=d.match_id
                LEFT JOIN results r ON r.match_id=d.match_id
                WHERE d.policy_id=? AND datetime(d.decided_at)<=datetime(?)
                ORDER BY d.decided_at""", (
                    observed_at.isoformat(), observed_at.isoformat(), policy["policy_id"],
                    observed_at.isoformat(),
                )).fetchall()
        decisions = [dict(row) for row in rows]
        candidates = [row for row in decisions if row["action"] == "CANDIDATE"]
        settled = [row for row in candidates if row["actual_outcome"] in {"home", "draw", "away"}]
        profits = [float(row["bet365_odds"]) - 1.0 if row["actual_outcome"] == row["selected_outcome"] else -1.0 for row in settled]
        paper = self._paper_portfolio(candidates, policy["config"], observed_at)
        bootstrap = _settlement_day_bootstrap_roi(paper["positions"])
        months = sorted({str(row["kickoff_time"])[:7] for row in settled})
        mature = len(settled) >= 200 and len(months) >= 6
        brier = fmean(
            (float(row["conservative_probability"]) - float(row["actual_outcome"] == row["selected_outcome"])) ** 2
            for row in settled
        ) if settled else None
        reference_brier = fmean(
            (float(row["reference_probability"]) - float(row["actual_outcome"] == row["selected_outcome"])) ** 2
            for row in settled
        ) if settled else None
        selected_outcomes = Counter(str(row["selected_outcome"]) for row in candidates)
        execution_books = Counter(str(row.get("execution_bookmaker_key") or "unknown") for row in candidates)
        ranked = [row for row in decisions if row.get("ranker_model_sha256")]
        outcome_concentration = max(selected_outcomes.values(), default=0) / len(candidates) if candidates else 0.0
        reasons = []
        if len(settled) < 200: reasons.append("settled_selections<200")
        if len(months) < 6: reasons.append("active_months<6")
        if mature and (bootstrap["lower_95_pct"] is None or float(bootstrap["lower_95_pct"]) <= 0):
            reasons.append("settlement_day_bootstrap_roi_lower_95<=0")
        if mature and brier is not None and reference_brier is not None and brier > reference_brier + 0.002:
            reasons.append("conservative_probability_brier_worse_than_market")
        if mature and outcome_concentration > 0.75:
            reasons.append("selected_outcome_concentration>75pct")
        return {"method": "timestamp-aligned best named-book quote versus robust leave-one-book-out consensus",
                "policy": policy, "decision": "NAMED_BOOK_GAP_PROSPECTIVE_PASS" if mature and not reasons else "NAMED_BOOK_GAP_PROSPECTIVE_COLLECTING",
                "decision_reasons": reasons, "decisions": len(decisions), "candidate_decisions": sum(row["action"] == "CANDIDATE" for row in decisions),
                "settled_selections": len(settled), "active_months": len(months), "profit": round(sum(profits), 2),
                "roi_pct": round(sum(profits) / len(settled) * 100, 2) if settled else 0.0,
                "average_expected_ev": round(fmean(float(row["expected_ev"]) for row in settled), 6) if settled else None,
                "calibration": {
                    "selected_binary_brier": round(brier, 6) if brier is not None else None,
                    "reference_binary_brier": round(reference_brier, 6) if reference_brier is not None else None,
                },
                "selection_diagnostics": {
                    "outcome_counts": dict(selected_outcomes),
                    "horizon_role_counts": dict(Counter(
                        str(row.get("horizon_role") or "single_horizon")
                        for row in decisions if row["action"] == "CANDIDATE"
                    )),
                    "maximum_outcome_concentration_pct": round(outcome_concentration * 100, 2),
                    "execution_bookmaker_counts": dict(execution_books),
                    "ranker_evidence_rows": len(ranked),
                    "average_predicted_closing_edge_pct": round(fmean(
                        float(row["predicted_closing_edge_pct"]) for row in ranked
                    ), 4) if ranked else None,
                    "ranker_model_sha256": policy["config"].get("ranker_model_sha256"),
                },
                "settlement_day_bootstrap_roi": bootstrap,
                "prospective_warnings": (
                    (["historical_league_codes_do_not_match_official_pool_labels; unknown-category fallback is under validation"]
                     if policy["config"].get("feature_portability_status") == "PROSPECTIVE_VALIDATION_REQUIRED" else [])
                    + ([str(policy["config"]["prospective_warning"])]
                       if policy["config"].get("prospective_warning") else [])
                ),
                "paper_portfolio": paper,
                "anti_leakage": (
                    "A decision must exist by as_of; a result is usable only when "
                    "settled_at is after kickoff_time and decided_at and no later than as_of."
                ),
                "guardrail": "Research-only immutable paper simulation. It never creates real orders."}

    @staticmethod
    def _paper_portfolio(candidates: list[dict[str, Any]], config: dict[str, Any],
                         as_of: datetime | None = None) -> dict[str, Any]:
        observed_at = _time(as_of or _now())
        daily_budget = float(config["daily_budget"])
        single_cap = float(config["maximum_single_stake"])
        fraction = float(config["kelly_fraction"])
        daily_used: dict[str, float] = {}
        positions: list[dict[str, Any]] = []
        for row in sorted(candidates, key=lambda item: (str(item["decided_at"]), str(item["decision_id"]))):
            decision_time = _time(row["decided_at"]).astimezone(CHINA_TZ)
            day = decision_time.date().isoformat()
            remaining = max(0.0, daily_budget - daily_used.get(day, 0.0))
            odds = float(row["bet365_odds"])
            probability = float(row.get("conservative_probability") or row["reference_probability"])
            full_kelly = max(0.0, (probability * odds - 1.0) / max(odds - 1.0, 1e-9))
            reference_depth = len(json.loads(str(
                row.get("reference_bookmakers_json") or "[]"
            )))
            stake_multiplier = (
                float(config.get("minimum_depth_stake_multiplier", 1.0))
                if reference_depth == int(config.get("minimum_reference_depth", -1))
                else 1.0
            )
            row_fraction = float(row.get("effective_kelly_fraction") or fraction)
            stake = round(min(
                single_cap, remaining,
                daily_budget * full_kelly * row_fraction * stake_multiplier,
            ), 2)
            if stake <= 0:
                continue
            daily_used[day] = daily_used.get(day, 0.0) + stake
            raw_settled_at = row.get("result_settled_at")
            settled_at = (
                raw_settled_at
                if raw_settled_at and _time(raw_settled_at) <= observed_at else None
            )
            won = str(row.get("actual_outcome")) == str(row["selected_outcome"]) if settled_at else None
            profit = round(stake * (odds - 1.0) if won else -stake, 2) if settled_at else None
            settlement_day = _time(settled_at).astimezone(CHINA_TZ).date().isoformat() if settled_at else None
            positions.append({"decision_date": day, "settlement_date": settlement_day,
                              "match_id": row["match_id"], "outcome": row["selected_outcome"],
                              "league": row.get("league") or "UNKNOWN",
                              "bookmaker": row.get("execution_bookmaker"), "odds": odds,
                              "stake": stake, "stake_multiplier": stake_multiplier,
                              "horizon_role": row.get("horizon_role") or "single_horizon",
                              "effective_kelly_fraction": row_fraction,
                              "reference_depth": reference_depth,
                              "status": "SETTLED" if settled_at else "PENDING",
                              "won": won, "profit": profit})
        maximum_daily_league_stake = float(
            config.get("maximum_daily_league_stake", 0.0)
        )
        if maximum_daily_league_stake > 0:
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for item in positions:
                grouped.setdefault(
                    (str(item["decision_date"]), str(item["league"])), []
                ).append(item)
            for group in grouped.values():
                total = sum(float(item["stake"]) for item in group)
                scale = min(1.0, maximum_daily_league_stake / max(total, 1e-9))
                for item in group:
                    item["stake"] = round(float(item["stake"]) * scale, 2)
                    if item["status"] == "SETTLED":
                        item["profit"] = round(
                            item["stake"] * (float(item["odds"]) - 1.0)
                            if item["won"] else -item["stake"], 2
                        )
            positions = [item for item in positions if float(item["stake"]) >= 0.10]
        daily: list[dict[str, Any]] = []
        equity = peak = max_drawdown = 0.0
        today = observed_at.astimezone(CHINA_TZ).date()
        current = today - timedelta(days=29)
        prior_settlement_days = sorted({
            str(item["settlement_date"])
            for item in positions
            if item["settlement_date"] and str(item["settlement_date"]) < current.isoformat()
        })
        for day_text in prior_settlement_days:
            day_profit = round(sum(
                float(item["profit"] or 0) for item in positions
                if item["settlement_date"] == day_text
            ), 2)
            equity = round(equity + day_profit, 2)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        opening_equity = equity
        while current <= today:
            day_text = current.isoformat()
            day_positions = [item for item in positions if item["decision_date"] == day_text]
            settlements = [item for item in positions if item["settlement_date"] == day_text]
            day_profit = round(sum(float(item["profit"] or 0) for item in settlements), 2)
            equity = round(equity + day_profit, 2)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            daily.append({"date": day_text, "bets": len(day_positions),
                          "staked": round(sum(item["stake"] for item in day_positions), 2),
                          "pending": sum(item["status"] == "PENDING" for item in day_positions),
                          "settlements": len(settlements), "settled_profit": day_profit, "equity": equity,
                          "cash_reserved": round(daily_budget - sum(item["stake"] for item in day_positions), 2)})
            current += timedelta(days=1)
        staked = round(sum(item["stake"] for item in positions), 2)
        settled_staked = round(sum(item["stake"] for item in positions if item["status"] == "SETTLED"), 2)
        profit = round(sum(float(item["profit"] or 0) for item in positions), 2)
        monthly = []
        for month in sorted({item["decision_date"][:7] for item in positions}):
            selected = [item for item in positions if item["decision_date"].startswith(month)]
            month_staked = round(sum(item["stake"] for item in selected), 2)
            month_settled_staked = round(sum(item["stake"] for item in selected if item["status"] == "SETTLED"), 2)
            month_profit = round(sum(float(item["profit"] or 0) for item in selected), 2)
            monthly.append({"month": month, "bets": len(selected),
                            "settled": sum(item["status"] == "SETTLED" for item in selected), "staked": month_staked,
                            "profit": month_profit,
                            "roi_pct": round(month_profit / month_settled_staked * 100, 2) if month_settled_staked else 0.0})
        return {"daily_budget_limit": daily_budget, "maximum_single_stake": single_cap,
                "maximum_daily_league_stake": maximum_daily_league_stake or None,
                "staking": f"{fraction:g}_kelly_with_cash_reserve", "same_day_results_hidden": True,
                "daily_window": "latest_30_calendar_days_Asia/Shanghai",
                "bets": len(positions), "pending_bets": sum(item["status"] == "PENDING" for item in positions),
                "settled_bets": sum(item["status"] == "SETTLED" for item in positions),
                "staked": staked, "settled_staked": settled_staked, "profit": profit,
                "roi_pct": round(profit / settled_staked * 100, 2) if settled_staked else 0.0,
                "opening_equity": opening_equity, "ending_equity": equity,
                "max_drawdown": round(max_drawdown, 2),
                "positive_months": sum(item["profit"] > 0 for item in monthly),
                "negative_months": sum(item["profit"] < 0 for item in monthly),
                "monthly": monthly, "daily": daily, "positions": positions}

    def _policy(self, policy_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM named_book_gap_policies WHERE policy_id=?", (policy_id,)).fetchone()
        if not row:
            raise KeyError(policy_id)
        return {**dict(row), "config": json.loads(row["config_json"])}
