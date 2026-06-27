"""Reproducible research models and evaluation utilities."""

from .dataset import OddsTiming, audit_football_data, load_football_data
from .evaluation import evaluate_probabilities, paired_bootstrap_difference
from .features import FEATURE_COLUMNS, build_leakage_free_rolling_features
from .models import HierarchicalLeagueDixonColes, MarketAnchoredResidualModel, TimeDecayDixonColes

__all__ = [
    "MarketAnchoredResidualModel",
    "HierarchicalLeagueDixonColes",
    "OddsTiming",
    "TimeDecayDixonColes",
    "audit_football_data",
    "evaluate_probabilities",
    "load_football_data",
    "paired_bootstrap_difference",
    "FEATURE_COLUMNS",
    "build_leakage_free_rolling_features",
]
