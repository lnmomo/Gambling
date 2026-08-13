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
    MULTI_HORIZON_MID_MODEL_PATH,
    MULTI_HORIZON_MID_MOVEMENT_MODEL_PATH,
    WIDE_ALL_OUTCOMES_MODEL_PATHS,
    POSITIVE_CLV_MODEL_PATHS,
    load_frozen_model,
    market_structure_features,
    odds_band,
    score_opening_features,
    score_positive_clv_probability,
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
CLV_RIDGE_THREE_HORIZON_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_ADAPTIVE_CAP_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_DIRECT_ONLY_TIER_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_MATCHED_ADAPTIVE_BUDGET_POLICY_CONFIG: dict[str, Any] | None = None
CLV_RIDGE_WIDE_ALL_OUTCOMES_POLICY_CONFIG: dict[str, Any] | None = None
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
        if (
            MULTI_HORIZON_MID_MODEL_PATH.exists()
            and MULTI_HORIZON_MID_MOVEMENT_MODEL_PATH.exists()
        ):
            _CLV_RIDGE_MID_DIRECT_MODEL = load_frozen_model(
                str(MULTI_HORIZON_MID_MODEL_PATH)
            )
            _CLV_RIDGE_MID_MOVEMENT_MODEL = load_frozen_model(
                str(MULTI_HORIZON_MID_MOVEMENT_MODEL_PATH)
            )
            _CLV_MID_AGREEMENT_HASH = hashlib.sha256(json.dumps(sorted([
                _CLV_RIDGE_MID_DIRECT_MODEL["model_sha256"],
                _CLV_RIDGE_MID_MOVEMENT_MODEL["model_sha256"],
            ]), separators=(",", ":")).encode()).hexdigest()
            CLV_RIDGE_THREE_HORIZON_POLICY_CONFIG = {
                **CLV_RIDGE_MULTI_HORIZON_POLICY_CONFIG,
                "version": "clv-ridge-v8.34-three-horizon-sequential-prospective-shadow",
                "decision_model": "frozen_json_clv_three_horizon",
                "mid_horizon_direct_model_filename": MULTI_HORIZON_MID_MODEL_PATH.name,
                "mid_horizon_movement_model_filename": (
                    MULTI_HORIZON_MID_MOVEMENT_MODEL_PATH.name
                ),
                "mid_horizon_model_sha256": _CLV_MID_AGREEMENT_HASH,
                "mid_horizon_training_window": _CLV_RIDGE_MID_DIRECT_MODEL["training_window"],
                "mid_horizon_training_months": 12,
                "mid_horizon_validation_months": 6,
                "tertiary_minimum_lower_clv_pct": 2.0,
                "tertiary_minimum_staking_probability": 0.0,
                "tertiary_kelly_fraction": 0.3125,
                "tertiary_rule": (
                    "use_12m6m_only_when_9m3m_core_and_18m9m_satellite_are_"
                    "both_ineligible_on_the_same_frozen_snapshot"
                ),
                "selection_challenger_of": (
                    "clv-ridge-v8.33-multi-horizon-core-satellite-prospective-shadow"
                ),
                "historical_clv_attribution": (
                    "2.5pct_193_positions_closing_expected_profit_29.14_roi_7.79pct_"
                    "late_expected_profit_5.40_roi_5.78pct"
                ),
                "historical_cost_stress_status": (
                    "5pct_181_positions_closing_expected_profit_27.07_"
                    "block_lower_95_positive_25.63pct"
                ),
                "historical_risk_gate": (
                    "2.5pct_max_drawdown_22.29_source_lower_12.36_league_lower_6.28_"
                    "team_lower_14.22"
                ),
                "prospective_warning": (
                    "v8.34 is paper-only: 9m3m, 18m9m and 12m6m models are checked "
                    "in that fixed order; the 12m6m tertiary can act only when both "
                    "earlier horizons reject, uses 0.3125 Kelly, and shares the CNY 100 "
                    "daily and CNY 15 league-day caps; no real orders are created"
                ),
            }
            CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG = {
                **CLV_RIDGE_THREE_HORIZON_POLICY_CONFIG,
                "version": "clv-ridge-v8.35-three-horizon-runtime-parity-prospective-shadow",
                "satellite_minimum_staking_probability": 0.25,
                "tertiary_minimum_staking_probability": 0.25,
                "selection_challenger_of": (
                    "clv-ridge-v8.34-three-horizon-sequential-prospective-shadow"
                ),
                "runtime_parity_fix": (
                    "supplemental_horizon_minimum_staking_probability_0.25_"
                    "matches_frozen_historical_replay"
                ),
                "historical_replay_equivalence": (
                    "same_193_positions_at_2.5pct_and_181_positions_at_5pct_as_"
                    "v8.34_replay; only runtime threshold mismatch is corrected"
                ),
                "prospective_warning": (
                    "v8.35 is paper-only: it preserves the frozen v8.34 historical "
                    "portfolio and corrects runtime satellite and tertiary minimum "
                    "staking probabilities from 0.0 to the replayed 0.25; no real "
                    "orders are created"
                ),
            }
if (
    CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG
    and all(
        path.exists()
        for role_paths in POSITIVE_CLV_MODEL_PATHS.values()
        for path in role_paths.values()
    )
):
    _POSITIVE_CLV_MODELS = {
        role: {
            cost: load_frozen_model(str(path))
            for cost, path in role_paths.items()
        }
        for role, role_paths in POSITIVE_CLV_MODEL_PATHS.items()
    }
    _POSITIVE_CLV_COMBINED_HASH = hashlib.sha256(json.dumps(sorted(
        model["model_sha256"]
        for role_models in _POSITIVE_CLV_MODELS.values()
        for model in role_models.values()
    ), separators=(",", ":")).encode()).hexdigest()
    CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG = {
        **CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG,
        "version": "clv-ridge-v8.55-cross-cost-positive-clv-uplift-prospective-shadow",
        "positive_clv_classifier_filenames": {
            role: {cost: path.name for cost, path in role_paths.items()}
            for role, role_paths in POSITIVE_CLV_MODEL_PATHS.items()
        },
        "positive_clv_classifier_sha256": {
            role: {
                cost: model["model_sha256"]
                for cost, model in role_models.items()
            }
            for role, role_models in _POSITIVE_CLV_MODELS.items()
        },
        "positive_clv_combined_sha256": _POSITIVE_CLV_COMBINED_HASH,
        "positive_clv_cost_rates": {"2_5pct": 0.025, "5pct": 0.05},
        "positive_clv_probability_anchor": 0.75,
        "positive_clv_minimum_stake_multiplier": 1.0,
        "positive_clv_maximum_stake_multiplier": 1.05,
        "stake_challenger_of": (
            "clv-ridge-v8.35-three-horizon-runtime-parity-prospective-shadow"
        ),
        "historical_clv_attribution": (
            "matched_48fold_2.5pct_expected_profit_plus_2.6967pct_"
            "5pct_plus_2.7425pct"
        ),
        "historical_risk_gate": (
            "both_costs_max_drawdown_22.80_growth_3.6364pct_below_5pct_limit"
        ),
        "research_evidence_status": (
            "HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.55 is paper-only: each selected horizon receives at most a 5% "
            "Kelly uplift only when independently frozen 2.5% and 5% positive-CLV "
            "classifiers agree; immutable prospective closing evidence is required "
            "and no real orders are created"
        ),
    }
    CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG = {
        **CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG,
        "version": (
            "clv-ridge-v8.57-cross-cost-positive-clv-growth-uplift-"
            "prospective-shadow"
        ),
        "positive_clv_maximum_stake_multiplier": 1.25,
        "stake_challenger_of": (
            "clv-ridge-v8.55-cross-cost-positive-clv-uplift-prospective-shadow"
        ),
        "historical_clv_attribution": (
            "matched_48fold_2.5pct_expected_profit_plus_3.3651pct_"
            "5pct_plus_3.3975pct"
        ),
        "historical_risk_gate": (
            "both_costs_max_drawdown_23.45_growth_2.8509pct_below_5pct_limit"
        ),
        "research_evidence_status": (
            "HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.57 is paper-only: unchanged selections receive at most a 25% "
            "Kelly uplift only when independently frozen 2.5% and 5% positive-CLV "
            "classifiers agree; immutable prospective evidence is required and no "
            "real orders are created"
        ),
    }
    CLV_RIDGE_ADAPTIVE_CAP_POLICY_CONFIG = {
        **CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG,
        "version": (
            "clv-ridge-v8.58-walk-forward-adaptive-confidence-cap-"
            "prospective-shadow"
        ),
        "adaptive_confidence_cap_enabled": True,
        "adaptive_conservative_maximum_multiplier": 1.05,
        "adaptive_growth_maximum_multiplier": 1.25,
        "adaptive_minimum_prior_uplifted_positions": 10,
        "stake_challenger_of": (
            "clv-ridge-v8.55-cross-cost-positive-clv-uplift-prospective-shadow"
        ),
        "historical_clv_attribution": (
            "expanding_walk_forward_2.5pct_expected_profit_27.5242_"
            "5pct_expected_profit_26.8057"
        ),
        "historical_risk_gate": (
            "both_costs_max_drawdown_22.80_no_increase_vs_v8.55"
        ),
        "research_evidence_status": (
            "HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.58 is paper-only: the monthly 1.05 or 1.25 confidence cap is "
            "selected exclusively from immutable closing evidence in prior calendar "
            "months; current-month prices and all match results are excluded"
        ),
    }
    CLV_RIDGE_DIRECT_ONLY_TIER_POLICY_CONFIG = {
        **CLV_RIDGE_ADAPTIVE_CAP_POLICY_CONFIG,
        "version": (
            "clv-ridge-v8.60-cross-cost-direct-only-core-tier-"
            "prospective-shadow"
        ),
        "direct_only_fallback_enabled": True,
        "direct_only_minimum_lower_clv_pct": 1.0,
        "direct_only_minimum_positive_clv_probability": 0.65,
        "direct_only_kelly_fraction": 0.50,
        "incremental_role_gate": "9m3m_direct_only",
        "incremental_role_minimum_closing_observations": 30,
        "incremental_role_minimum_average_closing_edge_pct": 0.0,
        "incremental_role_minimum_positive_clv_rate": 0.50,
        "selection_challenger_of": (
            "clv-ridge-v8.58-walk-forward-adaptive-confidence-cap-"
            "prospective-shadow"
        ),
        "historical_clv_attribution": (
            "incremental_36_at_2.5pct_expected_profit_plus_3.8791pct_"
            "incremental_33_at_5pct_plus_2.6644pct"
        ),
        "historical_risk_gate": (
            "both_costs_max_drawdown_22.80_no_increase_vs_v8.58"
        ),
        "research_evidence_status": (
            "HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.60 is paper-only: a half-Kelly direct-only core candidate is "
            "considered only after all three agreement horizons reject and both cost "
            "classifiers retain at least 0.65 positive-CLV probability"
        ),
    }
    CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG = {
        **CLV_RIDGE_DIRECT_ONLY_TIER_POLICY_CONFIG,
        "version": (
            "clv-ridge-v8.61-discovery-selected-budget-deployment-"
            "prospective-shadow"
        ),
        "budget_deployment_multiplier": 10.0,
        "budget_multiplier_grid": [1.0, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0],
        "budget_multiplier_discovery_end": "2024-05-31",
        "budget_multiplier_discovery_maximum_drawdown": 100.0,
        "stake_challenger_of": (
            "clv-ridge-v8.60-cross-cost-direct-only-core-tier-"
            "prospective-shadow"
        ),
        "historical_clv_attribution": (
            "2.5pct_expected_profit_113.9265_validation_43.7129_"
            "5pct_expected_profit_104.0127_validation_33.7991"
        ),
        "historical_risk_gate": (
            "cross_cost_max_drawdown_90.27_below_cny100_"
            "maximum_active_day_stake_53.40_below_cny100"
        ),
        "research_evidence_status": (
            "HISTORICAL_STAKE_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.61 is paper-only: it preserves every v8.60 selection and direction, "
            "multiplies the already-frozen opening stake by 10, then reapplies the "
            "CNY 15 single and league-day caps and CNY 100 daily cap; no real orders "
            "are created"
        ),
    }
    CLV_RIDGE_MATCHED_ADAPTIVE_BUDGET_POLICY_CONFIG = {
        **CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG,
        "version": (
            "clv-ridge-v8.64-matched-cross-cost-adaptive-budget-"
            "prospective-shadow"
        ),
        "adaptive_budget_deployment_enabled": True,
        "adaptive_budget_base_multiplier": 10.0,
        "adaptive_budget_growth_multiplier": 20.0,
        "adaptive_budget_prior_active_months": 3,
        "adaptive_budget_minimum_prior_matched_positions": 20,
        "adaptive_budget_cost_rates": {"2_5pct": 0.025, "5pct": 0.05},
        "stake_challenger_of": (
            "clv-ridge-v8.61-discovery-selected-budget-deployment-"
            "prospective-shadow"
        ),
        "historical_clv_attribution": (
            "matched_evidence_2.5pct_expected_profit_122.7072_"
            "5pct_expected_profit_110.9568"
        ),
        "historical_risk_gate": (
            "cross_cost_max_drawdown_90.27_maximum_active_day_stake_53.40"
        ),
        "research_evidence_status": (
            "HISTORICAL_STAKE_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
        ),
        "prospective_warning": (
            "v8.64 is paper-only: each month's 10 or 20 multiplier is frozen from "
            "strictly prior settled decisions that retain the same direction under "
            "both cost stresses; no current-month evidence or real orders are used"
        ),
    }
    if all(path.exists() for path in WIDE_ALL_OUTCOMES_MODEL_PATHS.values()):
        _WIDE_ALL_OUTCOMES_MODELS = {
            cost: load_frozen_model(str(path))
            for cost, path in WIDE_ALL_OUTCOMES_MODEL_PATHS.items()
        }
        _WIDE_ALL_OUTCOMES_COMBINED_HASH = hashlib.sha256(json.dumps(sorted(
            model["model_sha256"]
            for model in _WIDE_ALL_OUTCOMES_MODELS.values()
        ), separators=(",", ":")).encode()).hexdigest()
        CLV_RIDGE_WIDE_ALL_OUTCOMES_POLICY_CONFIG = {
            **CLV_RIDGE_MATCHED_ADAPTIVE_BUDGET_POLICY_CONFIG,
            "version": (
                "clv-ridge-v8.74-wide-all-outcomes-incremental-adaptive-"
                "prospective-shadow"
            ),
            "wide_all_outcomes_incremental_enabled": True,
            "wide_all_outcomes_model_filenames": {
                cost: path.name
                for cost, path in WIDE_ALL_OUTCOMES_MODEL_PATHS.items()
            },
            "wide_all_outcomes_model_sha256": {
                cost: model["model_sha256"]
                for cost, model in _WIDE_ALL_OUTCOMES_MODELS.items()
            },
            "wide_all_outcomes_combined_sha256": (
                _WIDE_ALL_OUTCOMES_COMBINED_HASH
            ),
            "wide_all_outcomes_cost_rates": {"2_5pct": 0.025, "5pct": 0.05},
            "wide_all_outcomes_minimum_price_ratio": 0.90,
            "wide_all_outcomes_minimum_conservative_ev": -0.15,
            "wide_all_outcomes_minimum_reference_probability": 0.08,
            "wide_all_outcomes_maximum_price_ratio": 1.20,
            "wide_all_outcomes_minimum_lower_clv_pct": 1.0,
            "wide_all_outcomes_maximum_odds": 5.0,
            "wide_all_outcomes_kelly_fraction": 0.10,
            "wide_all_outcomes_execution_cost_profile": "5pct_conservative",
            "wide_all_outcomes_training_window": "2025-07-01..2026-03-31",
            "selection_challenger_of": (
                "clv-ridge-v8.64-matched-cross-cost-adaptive-budget-"
                "prospective-shadow"
            ),
            "historical_clv_attribution": (
                "v8.73_incremental_46_cross_cost_direction_matched_positions_"
                "v8.74_2.5pct_expected_profit_129.8283_"
                "5pct_expected_profit_117.7982"
            ),
            "historical_risk_gate": (
                "both_costs_max_drawdown_93.06_below_cny100_"
                "relative_growth_3.0907pct"
            ),
            "latest_retraining_gate": (
                "LAST_COMMON_PASSED_WINDOW_ENDING_2026_03_31_"
                "5PCT_LATEST_WINDOW_ENDING_2026_05_31_FAILED"
            ),
            "research_evidence_status": (
                "HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED"
            ),
            "prospective_warning": (
                "v8.74 is paper-only: the wide 1X2 tier runs only after v8.60 "
                "rejects, requires independently frozen 2.5% and 5% models to "
                "select the same direction, executes the 5% cost view, and reuses "
                "the v8.64 strictly-prior adaptive budget; its latest 5% retraining "
                "window failed, so immutable prospective evidence is required and "
                "no real orders are created"
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
    *((CLV_RIDGE_THREE_HORIZON_POLICY_CONFIG,)
      if CLV_RIDGE_THREE_HORIZON_POLICY_CONFIG else ()),
    *((CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG,)
      if CLV_RIDGE_RUNTIME_PARITY_POLICY_CONFIG else ()),
    *((CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG,)
      if CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG else ()),
    *((CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG,)
      if CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG else ()),
    *((CLV_RIDGE_ADAPTIVE_CAP_POLICY_CONFIG,)
      if CLV_RIDGE_ADAPTIVE_CAP_POLICY_CONFIG else ()),
    *((CLV_RIDGE_DIRECT_ONLY_TIER_POLICY_CONFIG,)
      if CLV_RIDGE_DIRECT_ONLY_TIER_POLICY_CONFIG else ()),
    *((CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG,)
      if CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG else ()),
    *((CLV_RIDGE_MATCHED_ADAPTIVE_BUDGET_POLICY_CONFIG,)
      if CLV_RIDGE_MATCHED_ADAPTIVE_BUDGET_POLICY_CONFIG else ()),
    *((CLV_RIDGE_WIDE_ALL_OUTCOMES_POLICY_CONFIG,)
      if CLV_RIDGE_WIDE_ALL_OUTCOMES_POLICY_CONFIG else ()),
)
EXPERIMENT_NAME = "v3.1-v4.1-market-vs-v6.2-v6.3-v6.6-v7.6-v8.1-v8.5-v8.7-v8.8-v8.11-v8.13-v8.18-v8.21-v8.27-v8.28-v8.33-v8.34-v8.35-v8.55-v8.57-v8.58-v8.60-v8.61-v8.64-v8.74-clv-ridge-shadow"

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
        "frozen_json_clv_three_horizon",
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


def _score_wide_all_outcomes_incremental(
    inputs: dict[str, Any], match: dict[str, Any], config: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]] | None:
    """Choose one conservative direction only when both frozen cost views agree."""
    artifact_dir = Path(__file__).with_name("model_artifacts")
    winners: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for cost, cost_rate in config["wide_all_outcomes_cost_rates"].items():
        candidate_config = {
            **config,
            "minimum_price_ratio": config[
                "wide_all_outcomes_minimum_price_ratio"
            ],
            "minimum_conservative_ev": config[
                "wide_all_outcomes_minimum_conservative_ev"
            ],
            "minimum_reference_probability": config[
                "wide_all_outcomes_minimum_reference_probability"
            ],
            "maximum_price_ratio": config[
                "wide_all_outcomes_maximum_price_ratio"
            ],
            "maximum_odds": 8.0,
        }
        eligible: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        model_path = (
            artifact_dir / config["wide_all_outcomes_model_filenames"][cost]
        )
        for candidate in _market_candidates(
            inputs, candidate_config, exchange_commission_override=float(cost_rate)
        ):
            if candidate[9]:
                continue
            score = score_opening_features(
                _clv_feature_row(candidate, match), model_path
            )
            lower = float(score["lower_predicted_closing_edge_pct"])
            if (
                lower >= float(config["wide_all_outcomes_minimum_lower_clv_pct"])
                and float(candidate[1])
                <= float(config["wide_all_outcomes_maximum_odds"])
            ):
                eligible.append((candidate, score))
        if not eligible:
            return None
        eligible.sort(key=lambda row: (
            -float(row[1]["lower_predicted_closing_edge_pct"]),
            str(row[0][0]),
        ))
        winners[cost] = eligible[0]

    if len({str(candidate[0]) for candidate, _score in winners.values()}) != 1:
        return None
    selected, conservative_score = winners["5pct"]
    return selected, {
        "predicted_clv": float(
            conservative_score["predicted_closing_edge_pct"]
        ),
        "lower_predicted_clv": float(
            conservative_score["lower_predicted_closing_edge_pct"]
        ),
        "model_sha256": config["wide_all_outcomes_combined_sha256"],
    }


def _score_long_horizon_agreement(
    feature_row: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    return _score_clv_pair(
        feature_row,
        str(config["long_horizon_direct_model_filename"]),
        str(config["long_horizon_movement_model_filename"]),
        str(config["long_horizon_model_sha256"]),
    )


def _score_mid_horizon_agreement(
    feature_row: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    return _score_clv_pair(
        feature_row,
        str(config["mid_horizon_direct_model_filename"]),
        str(config["mid_horizon_movement_model_filename"]),
        str(config["mid_horizon_model_sha256"]),
    )


def _positive_clv_confidence_uplift(
    inputs: dict[str, Any], match: dict[str, Any], config: dict[str, Any],
    selected_outcome: str, horizon_role: str,
) -> dict[str, Any]:
    filenames = config["positive_clv_classifier_filenames"][horizon_role]
    expected_hashes = config["positive_clv_classifier_sha256"][horizon_role]
    probabilities: list[float] = []
    artifact_dir = Path(__file__).with_name("model_artifacts")
    stable_candidates: list[tuple[str, tuple[Any, ...]]] = []
    for cost, rate in config["positive_clv_cost_rates"].items():
        possible = _market_candidates(inputs, config, float(rate))
        if not possible:
            return {
                "positive_clv_probability": None,
                "stake_confidence_multiplier": 1.0,
                "confidence_model_sha256": config["positive_clv_combined_sha256"],
                "status": f"{cost}_no_valid_candidate",
            }
        candidate = max(possible, key=lambda item: (item[8], item[1]))
        if candidate[0] != selected_outcome or candidate[9]:
            return {
                "positive_clv_probability": None,
                "stake_confidence_multiplier": 1.0,
                "confidence_model_sha256": config["positive_clv_combined_sha256"],
                "status": f"{cost}_candidate_not_cost_stable",
            }
        stable_candidates.append((cost, candidate))

    for cost, candidate in stable_candidates:
        score = score_positive_clv_probability(
            _clv_feature_row(candidate, match), artifact_dir / filenames[cost]
        )
        if score["model_sha256"] != expected_hashes[cost]:
            raise ValueError("positive-CLV policy artifact hash mismatch")
        probabilities.append(float(score["positive_clv_probability"]))
    probability = min(probabilities)
    anchor = float(config["positive_clv_probability_anchor"])
    multiplier = min(
        float(config["positive_clv_maximum_stake_multiplier"]),
        max(
            float(config["positive_clv_minimum_stake_multiplier"]),
            probability / anchor,
        ),
    )
    return {
        "positive_clv_probability": probability,
        "stake_confidence_multiplier": multiplier,
        "confidence_model_sha256": config["positive_clv_combined_sha256"],
        "status": "CROSS_COST_CONSENSUS",
    }


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
                             inspect.getsource(self._adaptive_confidence_cap_state),
                             inspect.getsource(self._adaptive_budget_deployment_state),
                             inspect.getsource(self.report), inspect.getsource(self._paper_portfolio),
                             inspect.getsource(_devig), inspect.getsource(_robust_consensus),
                             inspect.getsource(score_opening_features), inspect.getsource(odds_band),
                             inspect.getsource(market_structure_features),
                             inspect.getsource(_historical_bookmaker_feature),
                             inspect.getsource(_market_candidates),
                             inspect.getsource(_clv_feature_row),
                             inspect.getsource(_score_clv_pair),
                             inspect.getsource(_score_clv_agreement),
                             inspect.getsource(_score_wide_all_outcomes_incremental),
                             inspect.getsource(_score_long_horizon_agreement),
                             inspect.getsource(_score_mid_horizon_agreement),
                             inspect.getsource(score_positive_clv_probability),
                             inspect.getsource(_positive_clv_confidence_uplift),
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

    def _adaptive_confidence_cap_state(
        self, config: dict[str, Any], decided_at: datetime,
    ) -> dict[str, Any]:
        conservative_cap = float(
            config.get("adaptive_conservative_maximum_multiplier", 1.05)
        )
        state = {
            "cap": conservative_cap,
            "prior_uplifted_positions": 0,
            "prior_closing_expected_profit_delta": 0.0,
            "status": "STATIC_OR_INSUFFICIENT_PRIOR_EVIDENCE",
        }
        if not config.get("adaptive_confidence_cap_enabled"):
            state["cap"] = float(
                config.get("positive_clv_maximum_stake_multiplier", 1.0)
            )
            state["status"] = "STATIC_POLICY"
            return state
        if (
            CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG is None
            or CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG is None
        ):
            return state

        local = decided_at.astimezone(CHINA_TZ)
        cutoff = datetime(local.year, local.month, 1, tzinfo=CHINA_TZ).astimezone(
            timezone.utc
        )
        conservative_policy = self.ensure_policy(
            CLV_RIDGE_CROSS_COST_UPLIFT_POLICY_CONFIG
        )
        growth_policy = self.ensure_policy(CLV_RIDGE_GROWTH_UPLIFT_POLICY_CONFIG)

        def prior_rows(policy_id: str) -> list[dict[str, Any]]:
            with self.db.connect() as connection:
                rows = connection.execute("""SELECT d.*,m.league,c.closing_edge_pct
                    FROM named_book_gap_decisions d
                    JOIN matches m ON m.id=d.match_id
                    JOIN named_book_gap_closing_observations c
                      ON c.decision_id=d.decision_id
                    WHERE d.policy_id=? AND d.action='CANDIDATE'
                      AND datetime(d.decided_at)<datetime(?)
                      AND datetime(d.kickoff_time)<datetime(?)
                      AND datetime(c.captured_at)<datetime(?)
                    ORDER BY d.decided_at,d.decision_id""", (
                        policy_id, cutoff.isoformat(), cutoff.isoformat(),
                        cutoff.isoformat(),
                    )).fetchall()
            return [dict(row) for row in rows]

        conservative_rows = prior_rows(conservative_policy["policy_id"])
        growth_rows = prior_rows(growth_policy["policy_id"])
        conservative_positions = self._paper_portfolio(
            conservative_rows, conservative_policy["config"], cutoff
        )["positions"]
        growth_positions = self._paper_portfolio(
            growth_rows, growth_policy["config"], cutoff
        )["positions"]
        conservative_stakes = {
            (int(row["match_id"]), str(row["outcome"])): float(row["stake"])
            for row in conservative_positions
        }
        growth_stakes = {
            (int(row["match_id"]), str(row["outcome"])): float(row["stake"])
            for row in growth_positions
        }
        closing_edges = {
            (int(row["match_id"]), str(row["selected_outcome"])):
            float(row["closing_edge_pct"]) / 100.0
            for row in growth_rows
        }
        expected_delta = 0.0
        uplifted = 0
        for key in conservative_stakes.keys() & growth_stakes.keys() & closing_edges.keys():
            stake_delta = growth_stakes[key] - conservative_stakes[key]
            if stake_delta > 1e-9:
                uplifted += 1
                expected_delta += stake_delta * closing_edges[key]
        state["prior_uplifted_positions"] = uplifted
        state["prior_closing_expected_profit_delta"] = round(expected_delta, 6)
        minimum = int(config["adaptive_minimum_prior_uplifted_positions"])
        if uplifted >= minimum and expected_delta > 0.0:
            state["cap"] = float(config["adaptive_growth_maximum_multiplier"])
            state["status"] = "GROWTH_CAP_FROM_PRIOR_MONTHS"
        return state

    def _adaptive_budget_deployment_state(
        self, config: dict[str, Any], decided_at: datetime,
    ) -> dict[str, Any]:
        base_multiplier = float(config.get(
            "adaptive_budget_base_multiplier",
            config.get("budget_deployment_multiplier", 1.0),
        ))
        state = {
            "multiplier": base_multiplier,
            "prior_active_months": 0,
            "prior_matched_positions": 0,
            "expected_profit_2_5pct": 0.0,
            "expected_profit_5pct": 0.0,
            "realized_profit_2_5pct": 0.0,
            "realized_profit_5pct": 0.0,
            "status": "STATIC_POLICY",
        }
        if not config.get("adaptive_budget_deployment_enabled"):
            return state
        state["status"] = "INSUFFICIENT_STRICTLY_PRIOR_MATCHED_EVIDENCE"
        if CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG is None:
            return state

        local = decided_at.astimezone(CHINA_TZ)
        cutoff = datetime(local.year, local.month, 1, tzinfo=CHINA_TZ).astimezone(
            timezone.utc
        )
        evidence_policy = self.ensure_policy(
            CLV_RIDGE_BUDGET_DEPLOYMENT_POLICY_CONFIG
        )
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,m.league,
                    c.closing_reference_probability,c.closing_edge_pct,
                    r.outcome AS actual_outcome,r.settled_at AS result_settled_at
                FROM named_book_gap_decisions d
                JOIN matches m ON m.id=d.match_id
                JOIN named_book_gap_closing_observations c
                  ON c.decision_id=d.decision_id
                JOIN results r ON r.match_id=d.match_id
                WHERE d.policy_id=? AND d.action='CANDIDATE'
                  AND d.positive_clv_probability IS NOT NULL
                  AND datetime(d.decided_at)<datetime(?)
                  AND datetime(d.kickoff_time)<datetime(?)
                  AND datetime(c.captured_at)<datetime(?)
                  AND datetime(r.settled_at)>=datetime(d.kickoff_time)
                  AND datetime(r.settled_at)>datetime(d.decided_at)
                  AND datetime(r.settled_at)<datetime(?)
                ORDER BY d.decided_at,d.decision_id""", (
                    evidence_policy["policy_id"], cutoff.isoformat(),
                    cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat(),
                )).fetchall()
        if not rows:
            return state

        raw_rows = [dict(row) for row in rows]
        exchange_keys = {
            str(key).lower() for key in config.get("exchange_bookmaker_keys", [])
        }
        cost_positions: dict[str, list[dict[str, Any]]] = {}
        closing_probabilities = {
            (int(row["match_id"]), str(row["selected_outcome"])):
            float(row["closing_reference_probability"])
            for row in raw_rows
        }
        evidence_config = {
            **evidence_policy["config"],
            "budget_deployment_multiplier": 1.0,
            "adaptive_budget_deployment_enabled": False,
        }
        for label, rate in config["adaptive_budget_cost_rates"].items():
            adjusted_rows = []
            for source in raw_rows:
                row = dict(source)
                bookmaker_key = str(row.get("execution_bookmaker_key") or "").lower()
                cost_rate = float(rate) if bookmaker_key in exchange_keys else 0.0
                row["bet365_odds"] = _net_execution_odds(
                    float(row["raw_execution_odds"]), cost_rate
                )
                adjusted_rows.append(row)
            cost_positions[str(label)] = self._paper_portfolio(
                adjusted_rows, evidence_config, cutoff
            )["positions"]

        common_keys = set.intersection(*[
            {(int(row["match_id"]), str(row["outcome"])) for row in positions}
            for positions in cost_positions.values()
        ])
        if not common_keys:
            return state
        active_months = sorted({
            str(row["decision_date"])[:7]
            for positions in cost_positions.values() for row in positions
            if (int(row["match_id"]), str(row["outcome"])) in common_keys
        })
        required_months = int(config["adaptive_budget_prior_active_months"])
        prior_months = active_months[-required_months:]
        state["prior_active_months"] = len(prior_months)
        if len(prior_months) < required_months:
            return state

        matched_count = None
        for label, positions in cost_positions.items():
            evidence = [
                row for row in positions
                if (int(row["match_id"]), str(row["outcome"])) in common_keys
                and str(row["decision_date"])[:7] in prior_months
            ]
            matched_count = len(evidence) if matched_count is None else min(
                matched_count, len(evidence)
            )
            expected_profit = sum(
                float(row["stake"]) * (
                    closing_probabilities[(int(row["match_id"]), str(row["outcome"]))]
                    * float(row["odds"]) - 1.0
                )
                for row in evidence
            )
            realized_profit = sum(float(row.get("profit") or 0.0) for row in evidence)
            state[f"expected_profit_{label}"] = round(expected_profit, 6)
            state[f"realized_profit_{label}"] = round(realized_profit, 6)
        state["prior_matched_positions"] = int(matched_count or 0)
        minimum = int(config["adaptive_budget_minimum_prior_matched_positions"])
        labels = list(config["adaptive_budget_cost_rates"])
        if (
            state["prior_matched_positions"] >= minimum
            and all(float(state[f"expected_profit_{label}"]) > 0.0 for label in labels)
            and all(float(state[f"realized_profit_{label}"]) > 0.0 for label in labels)
        ):
            state["multiplier"] = float(config["adaptive_budget_growth_multiplier"])
            state["status"] = "GROWTH_FROM_STRICTLY_PRIOR_MATCHED_EVIDENCE"
        return state

    def capture(self, limit: int = 100, as_of: str | datetime | None = None,
                policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        decided_at = _time(as_of or _now())
        policy = self.ensure_policy(policy_config)
        config = policy["config"]
        adaptive_cap = self._adaptive_confidence_cap_state(config, decided_at)
        adaptive_budget = self._adaptive_budget_deployment_state(config, decided_at)
        confidence_config = config
        if config.get("adaptive_confidence_cap_enabled"):
            confidence_config = {
                **config,
                "positive_clv_maximum_stake_multiplier": adaptive_cap["cap"],
            }
        counters: Counter[str] = Counter()
        inserted = candidates = 0
        active_matches = self.repository.list_active_research_matches(max(1, min(limit, 500)))
        next_primary_horizon_at: datetime | None = None
        eligible_matches = 0
        before_window_matches = 0
        after_window_matches = 0
        lower = float(config["primary_horizon_minutes"])
        upper = lower + float(config["horizon_tolerance_minutes"])
        for match in active_matches:
            kickoff = _time(match["kickoff_time"])
            minutes = (kickoff - decided_at).total_seconds() / 60.0
            if not lower <= minutes <= upper:
                counters["outside_primary_horizon"] += 1
                if minutes > upper:
                    before_window_matches += 1
                    window_at = kickoff - timedelta(minutes=upper)
                    if next_primary_horizon_at is None or window_at < next_primary_horizon_at:
                        next_primary_horizon_at = window_at
                else:
                    after_window_matches += 1
                continue
            eligible_matches += 1
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
            positive_clv_probability = None
            stake_confidence_multiplier = 1.0
            confidence_model_sha = None
            stored_expected_ev = selected[7]
            stored_conservative_ev = selected[8]
            stored_conservative_probability = selected[6]
            if config.get("decision_model") in {
                "frozen_json_clv_ridge", "frozen_json_clv_agreement",
                "frozen_json_clv_multi_horizon",
                "frozen_json_clv_three_horizon",
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
                    is_multi_horizon = config.get("decision_model") in {
                        "frozen_json_clv_multi_horizon",
                        "frozen_json_clv_three_horizon",
                    }
                    if is_multi_horizon and core_blockers:
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
                        elif config.get("decision_model") == "frozen_json_clv_three_horizon":
                            mid_ranker = _score_mid_horizon_agreement(feature_row, config)
                            mid_lower = float(mid_ranker["lower_predicted_clv"])
                            mid_probability = min(
                                0.999,
                                max(0.001, (1.0 + mid_lower / 100.0) / selected[1]),
                            )
                            mid_blockers = []
                            if mid_lower < float(config["tertiary_minimum_lower_clv_pct"]):
                                mid_blockers.append("predicted_lower_clv_below_policy_minimum")
                            if mid_probability < float(
                                config.get("tertiary_minimum_staking_probability", 0.0)
                            ):
                                mid_blockers.append(
                                    "conservative_probability_below_policy_minimum"
                                )
                            if not mid_blockers:
                                chosen = mid_ranker
                                chosen_probability = mid_probability
                                horizon_role = "12m6m_tertiary"
                                effective_kelly_fraction = float(
                                    config["tertiary_kelly_fraction"]
                                )
                            else:
                                selected[9].extend(
                                    f"core_horizon:{reason}" for reason in core_blockers
                                )
                                selected[9].extend(
                                    f"long_horizon:{reason}" for reason in long_blockers
                                )
                                selected[9].extend(
                                    f"mid_horizon:{reason}" for reason in mid_blockers
                                )
                        else:
                            selected[9].extend(
                                f"core_horizon:{reason}" for reason in core_blockers
                            )
                            selected[9].extend(
                                f"long_horizon:{reason}" for reason in long_blockers
                            )
                    else:
                        selected[9].extend(core_blockers)
                        if is_multi_horizon:
                            horizon_role = "9m3m_core"

                    predicted_clv = float(chosen["predicted_clv"])
                    lower_predicted_clv = float(chosen["lower_predicted_clv"])
                    ranker_model_sha = str(chosen["model_sha256"])
                    stored_expected_ev = predicted_clv / 100.0
                    stored_conservative_ev = lower_predicted_clv / 100.0
                    stored_conservative_probability = chosen_probability
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    selected[9].append(f"clv_ranker_unavailable:{type(exc).__name__}")
            if selected[9] and config.get("direct_only_fallback_enabled"):
                try:
                    direct_only = _score_clv_pair(
                        feature_row,
                        str(config["ranker_model_filename"]),
                        None,
                        str(config["ranker_model_sha256"]),
                    )
                    direct_lower = float(direct_only["lower_predicted_clv"])
                    direct_probabilities = list(
                        direct_only["market_staking_probabilities"]
                    )
                    direct_confidence = _positive_clv_confidence_uplift(
                        inputs, match, confidence_config, str(selected[0]),
                        "9m3m_core",
                    )
                    direct_positive_probability = direct_confidence[
                        "positive_clv_probability"
                    ]
                    if (
                        direct_lower >= float(
                            config["direct_only_minimum_lower_clv_pct"]
                        )
                        and direct_probabilities
                        and direct_positive_probability is not None
                        and float(direct_positive_probability) >= float(
                            config[
                                "direct_only_minimum_positive_clv_probability"
                            ]
                        )
                    ):
                        selected[9].clear()
                        predicted_clv = float(direct_only["predicted_clv"])
                        lower_predicted_clv = direct_lower
                        ranker_model_sha = str(direct_only["model_sha256"])
                        stored_expected_ev = predicted_clv / 100.0
                        stored_conservative_ev = direct_lower / 100.0
                        stored_conservative_probability = min(
                            direct_probabilities
                        )
                        horizon_role = "9m3m_direct_only"
                        effective_kelly_fraction = float(
                            config["direct_only_kelly_fraction"]
                        )
                        positive_clv_probability = float(
                            direct_positive_probability
                        )
                        confidence_model_sha = str(
                            direct_confidence["confidence_model_sha256"]
                        )
                except (KeyError, OSError, TypeError, ValueError):
                    pass
            if not selected[9]:
                selected[9].extend(_dual_cost_stability_blockers(
                    inputs, config, match, str(selected[0])
                ))
            if (
                not selected[9]
                and horizon_role != "9m3m_direct_only"
                and config.get("positive_clv_classifier_filenames")
            ):
                try:
                    confidence = _positive_clv_confidence_uplift(
                        inputs, match, confidence_config, str(selected[0]), horizon_role
                    )
                    positive_clv_probability = confidence[
                        "positive_clv_probability"
                    ]
                    stake_confidence_multiplier = float(
                        confidence["stake_confidence_multiplier"]
                    )
                    confidence_model_sha = str(
                        confidence["confidence_model_sha256"]
                    )
                    effective_kelly_fraction *= stake_confidence_multiplier
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    selected[9].append(
                        f"positive_clv_classifier_unavailable:{type(exc).__name__}"
                    )
            if selected[9] and config.get("wide_all_outcomes_incremental_enabled"):
                try:
                    incremental = _score_wide_all_outcomes_incremental(
                        inputs, match, config
                    )
                    if incremental is not None:
                        selected, incremental_score = incremental
                        selected[9].clear()
                        predicted_clv = float(
                            incremental_score["predicted_clv"]
                        )
                        lower_predicted_clv = float(
                            incremental_score["lower_predicted_clv"]
                        )
                        ranker_model_sha = str(
                            incremental_score["model_sha256"]
                        )
                        stored_expected_ev = predicted_clv / 100.0
                        stored_conservative_ev = lower_predicted_clv / 100.0
                        stored_conservative_probability = min(
                            0.999,
                            max(
                                0.001,
                                (1.0 + stored_conservative_ev)
                                / float(selected[1]),
                            ),
                        )
                        horizon_role = "9m3m_wide_all_outcomes_incremental"
                        effective_kelly_fraction = float(
                            config["wide_all_outcomes_kelly_fraction"]
                        )
                        positive_clv_probability = None
                        stake_confidence_multiplier = 1.0
                        confidence_model_sha = None
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    selected[9].append(
                        "wide_all_outcomes_incremental_unavailable:"
                        f"{type(exc).__name__}"
                    )
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
                "positive_clv_probability": positive_clv_probability,
                "stake_confidence_multiplier": stake_confidence_multiplier,
                "confidence_model_sha256": confidence_model_sha,
                "adaptive_confidence_cap": adaptive_cap["cap"],
                "adaptive_prior_uplifted_positions": adaptive_cap[
                    "prior_uplifted_positions"
                ],
                "adaptive_prior_closing_expected_profit_delta": adaptive_cap[
                    "prior_closing_expected_profit_delta"
                ],
                "adaptive_budget_multiplier": adaptive_budget["multiplier"],
                "adaptive_budget_prior_active_months": adaptive_budget[
                    "prior_active_months"
                ],
                "adaptive_budget_prior_matched_positions": adaptive_budget[
                    "prior_matched_positions"
                ],
                "adaptive_budget_prior_expected_profit_2_5pct": adaptive_budget[
                    "expected_profit_2_5pct"
                ],
                "adaptive_budget_prior_expected_profit_5pct": adaptive_budget[
                    "expected_profit_5pct"
                ],
                "adaptive_budget_prior_realized_profit_2_5pct": adaptive_budget[
                    "realized_profit_2_5pct"
                ],
                "adaptive_budget_prior_realized_profit_5pct": adaptive_budget[
                    "realized_profit_5pct"
                ],
                "adaptive_budget_state": adaptive_budget["status"],
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
                         horizon_role,effective_kelly_fraction,positive_clv_probability,
                         stake_confidence_multiplier,confidence_model_sha256,
                          adaptive_confidence_cap,adaptive_prior_uplifted_positions,
                          adaptive_prior_closing_expected_profit_delta,
                          adaptive_budget_multiplier,adaptive_budget_prior_active_months,
                          adaptive_budget_prior_matched_positions,
                          adaptive_budget_prior_expected_profit_2_5pct,
                          adaptive_budget_prior_expected_profit_5pct,
                          adaptive_budget_prior_realized_profit_2_5pct,
                          adaptive_budget_prior_realized_profit_5pct,adaptive_budget_state)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
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
                        horizon_role, effective_kelly_fraction, positive_clv_probability,
                        stake_confidence_multiplier, confidence_model_sha,
                        adaptive_cap["cap"], adaptive_cap["prior_uplifted_positions"],
                        adaptive_cap["prior_closing_expected_profit_delta"],
                        adaptive_budget["multiplier"], adaptive_budget["prior_active_months"],
                        adaptive_budget["prior_matched_positions"],
                        adaptive_budget["expected_profit_2_5pct"],
                        adaptive_budget["expected_profit_5pct"],
                        adaptive_budget["realized_profit_2_5pct"],
                        adaptive_budget["realized_profit_5pct"], adaptive_budget["status"],
                    ))
                inserted += 1
                candidates += int(action == "CANDIDATE")
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    counters["duplicate_decision"] += 1
                else:
                    raise
        report = self.report(policy["policy_id"], decided_at)
        return {"matches": len(active_matches), "decisions": inserted,
                "predictions": candidates, "blocker_counts": [{"reason": key, "matches": value} for key, value in counters.most_common()],
                "horizon_status": {
                    "primary_horizon_minutes": lower,
                    "horizon_tolerance_minutes": upper - lower,
                    "window_minutes_to_kickoff": [lower, upper],
                    "eligible_matches": eligible_matches,
                    "before_window_matches": before_window_matches,
                    "after_window_matches": after_window_matches,
                    "next_primary_horizon_at": (
                        next_primary_horizon_at.isoformat() if next_primary_horizon_at else None
                    ),
                },
                "report": report, "warnings": report["decision_reasons"]}

    def capture_experiment(self, limit: int = 100, as_of: str | datetime | None = None) -> dict[str, Any]:
        frozen_at = _time(as_of or _now())
        reports = [self.capture(limit, frozen_at, config) for config in EXPERIMENT_POLICY_CONFIGS]
        blockers: dict[str, dict[str, Any]] = {}
        for row in reports:
            for blocker in row.get("blocker_counts", []):
                reason = str(blocker["reason"])
                current = blockers.setdefault(reason, {"reason": reason, "matches": 0, "policies_affected": 0})
                current["matches"] = max(current["matches"], int(blocker.get("matches") or 0))
                current["policies_affected"] += 1
        horizon_status = reports[0].get("horizon_status", {}) if reports else {}
        return {
            "experiment": EXPERIMENT_NAME,
            "matches": max((int(row.get("matches") or 0) for row in reports), default=0),
            "decisions": sum(int(row.get("decisions") or 0) for row in reports),
            "predictions": sum(int(row.get("predictions") or 0) for row in reports),
            "policies": reports,
            "horizon_status": horizon_status,
            "blocker_counts": sorted(
                blockers.values(), key=lambda item: (-int(item["matches"]), item["reason"])
            ),
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

    def capture_closing_evidence(
        self, limit: int = 1000, as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        """Freeze post-decision, pre-kickoff closing consensus for CLV attribution."""
        observed_at = _time(as_of or _now())
        with self.db.connect() as connection:
            decisions = connection.execute("""SELECT d.*,p.config_json
                FROM named_book_gap_decisions d
                JOIN named_book_gap_policies p ON p.policy_id=d.policy_id
                LEFT JOIN named_book_gap_closing_observations c
                  ON c.decision_id=d.decision_id
                WHERE d.action='CANDIDATE' AND c.decision_id IS NULL
                  AND datetime(d.decided_at)<datetime(?)
                  AND EXISTS (
                    SELECT 1 FROM prospective_external_odds_snapshots s
                    WHERE s.match_id=d.match_id AND s.capture_window='CLOSING'
                      AND datetime(s.captured_at)>datetime(d.decided_at)
                      AND datetime(s.captured_at)<=datetime(d.kickoff_time)
                      AND datetime(s.captured_at)<=datetime(?)
                  )
                ORDER BY d.kickoff_time,d.decision_id LIMIT ?""", (
                    observed_at.isoformat(), observed_at.isoformat(), int(limit),
                )).fetchall()
            inserted = skipped = 0
            for source in decisions:
                decision = dict(source)
                snapshots = connection.execute("""SELECT *
                    FROM prospective_external_odds_snapshots
                    WHERE match_id=? AND capture_window='CLOSING'
                      AND datetime(captured_at)>datetime(?)
                      AND datetime(captured_at)<=datetime(kickoff_time)
                      AND datetime(captured_at)<=datetime(?)
                      AND captured_at=(
                        SELECT MAX(captured_at)
                        FROM prospective_external_odds_snapshots
                        WHERE match_id=? AND capture_window='CLOSING'
                          AND datetime(captured_at)>datetime(?)
                          AND datetime(captured_at)<=datetime(kickoff_time)
                          AND datetime(captured_at)<=datetime(?)
                      )
                    ORDER BY bookmaker_key""", (
                        decision["match_id"], decision["decided_at"],
                        observed_at.isoformat(), decision["match_id"],
                        decision["decided_at"], observed_at.isoformat(),
                    )).fetchall()
                if not snapshots:
                    skipped += 1
                    continue
                rows = [dict(row) for row in snapshots]
                references = [
                    {
                        "bookmaker_key": str(row["bookmaker_key"]),
                        "home_odds": float(row["home_odds"]),
                        "draw_odds": float(row["draw_odds"]),
                        "away_odds": float(row["away_odds"]),
                    }
                    for row in rows
                    if str(row["bookmaker_key"]) != str(decision["execution_bookmaker_key"])
                ]
                config = json.loads(str(decision["config_json"]))
                robust = _robust_consensus(references)
                if (
                    robust is None
                    or len(references) < int(config["minimum_reference_bookmakers"])
                ):
                    skipped += 1
                    continue
                probabilities, _dispersion = robust
                outcome = str(decision["selected_outcome"])
                probability = float(probabilities[outcome])
                execution_odds = float(decision["bet365_odds"])
                closing_edge_pct = (probability * execution_odds - 1.0) * 100.0
                captured_at = str(rows[0]["captured_at"])
                minutes = max(0.0, _age_minutes(
                    _time(decision["kickoff_time"]), captured_at
                ))
                bookmaker_keys = sorted(str(row["bookmaker_key"]) for row in references)
                source_hash = hashlib.sha256(json.dumps({
                    "decision_id": decision["decision_id"],
                    "snapshot_ids": sorted(str(row["snapshot_id"]) for row in rows),
                    "payload_hashes": sorted(str(row["payload_hash"]) for row in rows),
                }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                cursor = connection.execute("""INSERT OR IGNORE INTO
                    named_book_gap_closing_observations(
                        observation_id,decision_id,policy_id,match_id,selected_outcome,
                        captured_at,kickoff_time,minutes_to_kickoff,execution_odds,
                        closing_reference_probability,closing_fair_odds,closing_edge_pct,
                        positive_clv,reference_bookmakers_json,reference_method,
                        source_snapshot_hash,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        uuid.uuid4().hex, decision["decision_id"], decision["policy_id"],
                        decision["match_id"], outcome, captured_at,
                        decision["kickoff_time"], minutes, execution_odds, probability,
                        1.0 / probability, closing_edge_pct, int(closing_edge_pct > 0),
                        json.dumps(bookmaker_keys, separators=(",", ":")),
                        "normalized_component_median_leave_execution_book_out",
                        source_hash, observed_at.isoformat(),
                    ))
                inserted += int(cursor.rowcount > 0)
        return {
            "matches": inserted, "candidate_decisions_checked": len(decisions),
            "closing_observations": inserted,
            "skipped_without_eligible_closing_snapshot": skipped,
            "as_of": observed_at.isoformat(),
        }

    def report(
        self, policy_id: str | None = None, as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        policy = self.ensure_policy() if policy_id is None else self._policy(policy_id)
        observed_at = _time(as_of or _now())
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT d.*,m.league,
                c.captured_at AS closing_captured_at,
                c.closing_reference_probability,c.closing_fair_odds,
                c.closing_edge_pct,c.positive_clv,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at)
                       AND datetime(r.settled_at)<=datetime(?) THEN r.outcome END actual_outcome,
                CASE WHEN datetime(r.settled_at)>=datetime(d.kickoff_time)
                       AND datetime(r.settled_at)>datetime(d.decided_at)
                       AND datetime(r.settled_at)<=datetime(?) THEN r.settled_at END result_settled_at
                FROM named_book_gap_decisions d
                JOIN matches m ON m.id=d.match_id
                LEFT JOIN results r ON r.match_id=d.match_id
                LEFT JOIN named_book_gap_closing_observations c
                  ON c.decision_id=d.decision_id AND datetime(c.captured_at)<=datetime(?)
                WHERE d.policy_id=? AND datetime(d.decided_at)<=datetime(?)
                ORDER BY d.decided_at""", (
                    observed_at.isoformat(), observed_at.isoformat(), observed_at.isoformat(), policy["policy_id"],
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
        closing_evidenced = [
            row for row in candidates if row.get("closing_edge_pct") is not None
        ]
        settled_closing_evidenced = [
            row for row in settled if row.get("closing_edge_pct") is not None
        ]
        closing_coverage = (
            len(settled_closing_evidenced) / len(settled) if settled else 0.0
        )
        average_closing_edge = (
            fmean(float(row["closing_edge_pct"]) for row in closing_evidenced)
            if closing_evidenced else None
        )
        role_clv = {}
        for role, count in Counter(
            str(row.get("horizon_role") or "single_horizon")
            for row in closing_evidenced
        ).items():
            role_rows = [
                row for row in closing_evidenced
                if str(row.get("horizon_role") or "single_horizon") == role
            ]
            role_clv[role] = {
                "observations": count,
                "average_closing_edge_pct": round(fmean(
                    float(row["closing_edge_pct"]) for row in role_rows
                ), 4),
                "positive_clv_rate": round(fmean(
                    float(bool(row["positive_clv"])) for row in role_rows
                ), 4),
                "incremental_evidence_status": (
                    "READY" if count >= 30 else "COLLECTING"
                ),
            }
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
        if mature and closing_coverage < 0.80:
            reasons.append("prospective_closing_evidence_coverage<80pct")
        if mature and (average_closing_edge is None or average_closing_edge <= 0):
            reasons.append("prospective_average_closing_edge<=0")
        incremental_role = policy["config"].get("incremental_role_gate")
        if incremental_role:
            incremental = role_clv.get(str(incremental_role), {})
            incremental_observations = int(incremental.get("observations") or 0)
            if incremental_observations < int(policy["config"].get(
                "incremental_role_minimum_closing_observations", 30
            )):
                reasons.append(
                    f"{incremental_role}_closing_observations<"
                    f"{int(policy['config'].get('incremental_role_minimum_closing_observations', 30))}"
                )
            else:
                if float(incremental.get("average_closing_edge_pct") or 0.0) <= float(
                    policy["config"].get(
                        "incremental_role_minimum_average_closing_edge_pct", 0.0
                    )
                ):
                    reasons.append(
                        f"{incremental_role}_average_closing_edge_below_minimum"
                    )
                if float(incremental.get("positive_clv_rate") or 0.0) < float(
                    policy["config"].get(
                        "incremental_role_minimum_positive_clv_rate", 0.5
                    )
                ):
                    reasons.append(
                        f"{incremental_role}_positive_clv_rate_below_minimum"
                    )
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
                "prospective_clv": {
                    "observations": len(closing_evidenced),
                    "settled_selections": len(settled),
                    "settled_closing_evidence_coverage_pct": round(
                        closing_coverage * 100.0, 2
                    ),
                    "average_closing_edge_pct": round(
                        average_closing_edge, 4
                    ) if average_closing_edge is not None else None,
                    "positive_clv_rate": round(fmean(
                        float(bool(row["positive_clv"])) for row in closing_evidenced
                    ), 4) if closing_evidenced else None,
                    "by_horizon_role": role_clv,
                    "guardrail": (
                        "Closing observations are post-decision, pre-kickoff and immutable; "
                        "they never alter the frozen direction or stake."
                    ),
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
        default_budget_deployment_multiplier = float(
            config.get("budget_deployment_multiplier", 1.0)
        )
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
            frozen_budget_multiplier = row.get("adaptive_budget_multiplier")
            budget_deployment_multiplier = float(
                frozen_budget_multiplier
                if frozen_budget_multiplier is not None
                else default_budget_deployment_multiplier
            )
            stake = round(min(
                single_cap, remaining,
                daily_budget * full_kelly * row_fraction * stake_multiplier
                * budget_deployment_multiplier,
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
                              "budget_deployment_multiplier": budget_deployment_multiplier,
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
