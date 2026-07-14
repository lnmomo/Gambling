from __future__ import annotations

import pandas as pd

from scripts.multi_source_market_bias_discovery import aggregate_source_diagnostics


def _row(rule_key: str, source: str, profit: float, roi_pct: float, latest_profit: float = 1.0) -> dict:
    return {
        "columns": "league|outcome",
        "key": rule_key,
        "odds_source": source,
        "bets": 200,
        "profit": profit,
        "roi_pct": roi_pct,
        "active_months": 24,
        "positive_months": 14,
        "negative_months": 10,
        "latest_month": "2026-05",
        "latest_profit": latest_profit,
        "score": 10.0,
    }


def test_aggregate_requires_multiple_passing_sources() -> None:
    diagnostics = pd.DataFrame([
        _row("A|draw", "MAX_OPEN", 20.0, 10.0),
        _row("A|draw", "AVG_OPEN", -1.0, -0.5),
        _row("B|home", "MAX_OPEN", 18.0, 9.0),
        _row("B|home", "AVG_OPEN", 10.0, 5.0),
    ])

    result = aggregate_source_diagnostics(
        diagnostics,
        min_sources=2,
        min_source_roi_pct=3.0,
        require_positive_latest=True,
    )

    assert result["rule"].tolist() == ["league|outcome=B|home"]
    assert int(result.iloc[0]["passing_sources"]) == 2


def test_aggregate_can_require_positive_latest_source_result() -> None:
    diagnostics = pd.DataFrame([
        _row("A|draw", "MAX_OPEN", 20.0, 10.0, latest_profit=1.0),
        _row("A|draw", "AVG_OPEN", 10.0, 5.0, latest_profit=-2.0),
    ])

    strict = aggregate_source_diagnostics(
        diagnostics,
        min_sources=2,
        min_source_roi_pct=3.0,
        require_positive_latest=True,
    )
    loose = aggregate_source_diagnostics(
        diagnostics,
        min_sources=2,
        min_source_roi_pct=3.0,
        require_positive_latest=False,
    )

    assert strict.empty
    assert not loose.empty
