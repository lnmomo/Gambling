from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from itertools import islice, product
from math import isfinite
from typing import Any


@dataclass
class TrueOddsFilterConfig:
    config_id: str
    name: str
    lower_bound_ev_min: float = 0.0
    edge_quality_min_score: float = 55.0
    allowed_edge_quality_levels: list[str] = field(default_factory=lambda: ["MEDIUM", "HIGH"])
    uncertainty_z: float = 1.0
    min_method_agreement_score: float = 0.55
    base_ev_threshold: float = 0.03
    market_quality_adjustments: dict[str, float] = field(default_factory=lambda: {"HIGH": -0.005, "MEDIUM": 0.0, "LOW": 0.015, "UNAVAILABLE": 0.025})
    model_disagreement_adjustments: dict[str, float] = field(default_factory=lambda: {"LOW": 0.0, "MEDIUM": 0.010, "HIGH": 0.025})
    risk_adjustments: dict[str, float] = field(default_factory=lambda: {"pure_model_low": 0.015, "lineup_high": 0.015, "fatigue_high": 0.010})
    outcome_adjustments: dict[str, float] = field(default_factory=lambda: {"DRAW": 0.010, "HOME": 0.0, "AWAY": 0.0})
    odds_bucket_adjustments: dict[str, float] = field(default_factory=lambda: {"LOW": 0.015, "NORMAL": 0.0, "HIGH": 0.020})
    league_reliability_adjustments: dict[str, float] = field(default_factory=lambda: {"LOW": 0.015, "MEDIUM": 0.0, "HIGH": 0.0})
    clv_history_adjustments: dict[str, float] = field(default_factory=lambda: {"POSITIVE": -0.005, "NEGATIVE": 0.015, "UNKNOWN": 0.0})
    draw_extra_threshold: float = 0.010
    high_odds_extra_threshold: float = 0.020
    low_odds_extra_threshold: float = 0.015
    require_positive_expected_clv: bool = False
    min_clv_win_probability: float | None = None
    mode: str = "FILTER_ONLY"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_default_true_odds_filter_config() -> TrueOddsFilterConfig:
    return TrueOddsFilterConfig(config_id="default-filter-only", name="Default FILTER_ONLY")


def validate_true_odds_config(config: TrueOddsFilterConfig | dict[str, Any]) -> tuple[bool, list[str]]:
    if isinstance(config, dict):
        config = TrueOddsFilterConfig(**{**get_default_true_odds_filter_config().to_dict(), **config})
    warnings: list[str] = []
    numeric = {
        "lower_bound_ev_min": config.lower_bound_ev_min,
        "edge_quality_min_score": config.edge_quality_min_score,
        "uncertainty_z": config.uncertainty_z,
        "min_method_agreement_score": config.min_method_agreement_score,
        "base_ev_threshold": config.base_ev_threshold,
        "draw_extra_threshold": config.draw_extra_threshold,
        "high_odds_extra_threshold": config.high_odds_extra_threshold,
        "low_odds_extra_threshold": config.low_odds_extra_threshold,
    }
    for name, value in numeric.items():
        if not isfinite(float(value)):
            warnings.append(f"{name} must be finite")
    if not 0 <= config.lower_bound_ev_min <= 0.05:
        warnings.append("lower_bound_ev_min must be between 0 and 0.05")
    if not 35 <= config.edge_quality_min_score <= 90:
        warnings.append("edge_quality_min_score must be between 35 and 90")
    if not 0.5 <= config.uncertainty_z <= 2.0:
        warnings.append("uncertainty_z must be between 0.5 and 2.0")
    if not 0 <= config.min_method_agreement_score <= 1:
        warnings.append("min_method_agreement_score must be between 0 and 1")
    if config.mode not in {"SHADOW", "FILTER_ONLY", "ADJUST_PROBABILITY"}:
        warnings.append("mode must be SHADOW, FILTER_ONLY, or ADJUST_PROBABILITY")
    if config.mode == "ADJUST_PROBABILITY" and config.config_id.startswith("default"):
        warnings.append("default config must not use ADJUST_PROBABILITY")
    if any(value < 0 for value in [config.base_ev_threshold, config.draw_extra_threshold, config.high_odds_extra_threshold, config.low_odds_extra_threshold]):
        warnings.append("threshold values must not be negative")
    if not config.allowed_edge_quality_levels:
        warnings.append("allowed_edge_quality_levels must not be empty")
    return not warnings, warnings


def _named_variants() -> list[TrueOddsFilterConfig]:
    base = get_default_true_odds_filter_config()
    return [
        base,
        replace(base, config_id="conservative", name="Conservative", lower_bound_ev_min=0.010, edge_quality_min_score=65, uncertainty_z=1.25, min_method_agreement_score=0.65),
        replace(base, config_id="aggressive", name="Aggressive", lower_bound_ev_min=0.0, edge_quality_min_score=50, uncertainty_z=0.75, min_method_agreement_score=0.45),
        replace(base, config_id="draw-strict", name="Draw Strict", draw_extra_threshold=0.020, edge_quality_min_score=60),
        replace(base, config_id="high-odds-strict", name="High Odds Strict", high_odds_extra_threshold=0.030, edge_quality_min_score=60),
        replace(base, config_id="high-agreement", name="High Agreement", min_method_agreement_score=0.75, edge_quality_min_score=60),
        replace(base, config_id="high-confidence", name="High Confidence", lower_bound_ev_min=0.015, edge_quality_min_score=70, uncertainty_z=1.50, min_method_agreement_score=0.70),
    ]


def generate_true_odds_config_grid(options: dict[str, Any] | None = None) -> list[TrueOddsFilterConfig]:
    options = options or {}
    max_configs = int(options.get("max_configs") or 50)
    mode = "SHADOW" if options.get("shadow_only") else "FILTER_ONLY"
    configs = [replace(item, mode=mode) for item in _named_variants()]
    combos = product([0.0, 0.005, 0.010, 0.015], [55, 60, 65, 70, 75], [0.75, 1.0, 1.25, 1.5], [0.45, 0.55, 0.65, 0.75])
    for index, (lower, score, z, agreement) in enumerate(islice(combos, max(0, max_configs - len(configs))), 1):
        configs.append(TrueOddsFilterConfig(
            config_id=f"grid-{index:03d}", name=f"Grid {index:03d}", lower_bound_ev_min=lower,
            edge_quality_min_score=float(score), uncertainty_z=z, min_method_agreement_score=agreement,
            draw_extra_threshold=0.010 + (0.005 if score >= 65 else 0),
            high_odds_extra_threshold=0.020 + (0.005 if agreement >= 0.65 else 0),
            mode=mode,
        ))
    valid: list[TrueOddsFilterConfig] = []
    seen: set[tuple] = set()
    for config in configs:
        ok, warnings = validate_true_odds_config(config)
        config.warnings = warnings
        key = (config.lower_bound_ev_min, config.edge_quality_min_score, config.uncertainty_z, config.min_method_agreement_score, config.draw_extra_threshold, config.high_odds_extra_threshold, config.mode)
        if ok and key not in seen:
            seen.add(key)
            valid.append(config)
        if len(valid) >= max_configs:
            break
    return valid


def create_true_odds_config_version(config: TrueOddsFilterConfig, source_optimization_run_id: str | None = None,
                                    source_optimization_summary: dict[str, Any] | None = None,
                                    name: str | None = None, notes: str | None = None):
    from .shadow_prediction_store import ShadowPredictionStore
    return ShadowPredictionStore().create_config_version(config, source_optimization_run_id, source_optimization_summary, name, notes)


def save_true_odds_config_version(version):
    from .shadow_prediction_store import ShadowPredictionStore
    return ShadowPredictionStore().save_config_version(version)


def get_true_odds_config_version(config_version_id: str):
    from .shadow_prediction_store import ShadowPredictionStore
    return ShadowPredictionStore().get_config_version(config_version_id)


def get_active_shadow_config_versions():
    from .shadow_prediction_store import ShadowPredictionStore
    return ShadowPredictionStore().get_active_shadow_config_versions()


def get_latest_recommended_config_version():
    from .shadow_prediction_store import ShadowPredictionStore
    return ShadowPredictionStore().get_latest_recommended_config_version()


def archive_true_odds_config_version(config_version_id: str) -> None:
    from .shadow_prediction_store import ShadowPredictionStore
    ShadowPredictionStore().archive_config_version(config_version_id)
