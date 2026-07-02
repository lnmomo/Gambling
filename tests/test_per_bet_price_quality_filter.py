from __future__ import annotations

import pandas as pd

from scripts.per_bet_price_quality_filter import QualityConfig, apply_quality_filter, row_passes_quality


def test_quality_filter_uses_prior_month_history_only():
    rows = [
        {
            "date": "2026-01-01",
            "league": "L",
            "home_team": "A",
            "away_team": "B",
            "outcome": "home",
            "actual_result": "away",
            "odds": 2.0,
            "odds_bucket": "[1.8,2.2)",
            "market_prob_bucket": "[0.42,0.55)",
            "favorite_relation": "market_favorite",
            "stake": 1.0,
            "won": False,
            "profit": -1.0,
            "rule_label": "rule",
            "odds_source": "AVG_OPEN",
        },
        {
            "date": "2026-02-01",
            "league": "L",
            "home_team": "C",
            "away_team": "D",
            "outcome": "home",
            "actual_result": "home",
            "odds": 2.0,
            "odds_bucket": "[1.8,2.2)",
            "market_prob_bucket": "[0.42,0.55)",
            "favorite_relation": "market_favorite",
            "stake": 1.0,
            "won": True,
            "profit": 1.0,
            "rule_label": "rule",
            "odds_source": "AVG_OPEN",
        },
    ]
    config = QualityConfig(
        key_columns=("rule_label", "odds_source"),
        lookback_months=3,
        min_samples=1,
        min_roi=0.0,
        min_edge=0.0,
        min_conservative_edge=-1.0,
        cold_start="enabled",
    )

    selected, states = apply_quality_filter(pd.DataFrame(rows), config)

    assert selected["date"].tolist() == ["2026-01-01"]
    assert states.loc[states["month"] == "2026-01", "reason"].iloc[0] == "cold_start"
    assert states.loc[states["month"] == "2026-02", "reason"].iloc[0] == "quality_fail"


def test_row_quality_passes_when_prior_bucket_has_positive_edge():
    history = pd.DataFrame([
        {"month": "2026-01", "rule_label": "rule", "odds_source": "AVG_OPEN", "odds": 3.0, "stake": 1.0, "profit": 2.0, "won_bool": True},
        {"month": "2026-01", "rule_label": "rule", "odds_source": "AVG_OPEN", "odds": 3.0, "stake": 1.0, "profit": 2.0, "won_bool": True},
        {"month": "2026-01", "rule_label": "rule", "odds_source": "AVG_OPEN", "odds": 3.0, "stake": 1.0, "profit": -1.0, "won_bool": False},
    ])
    row = pd.Series({"rule_label": "rule", "odds_source": "AVG_OPEN"})
    config = QualityConfig(
        key_columns=("rule_label", "odds_source"),
        lookback_months=3,
        min_samples=3,
        min_roi=0.0,
        min_edge=0.0,
        min_conservative_edge=-0.2,
        cold_start="disabled",
    )

    passed, state = row_passes_quality(history, row, config)

    assert passed is True
    assert state["edge"] > 0
