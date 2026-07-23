from __future__ import annotations

from scripts.portfolio_algorithm_rolling_validation import _aggregate, _fold


def test_fold_has_disjoint_six_month_training_and_three_month_holdout() -> None:
    fold = _fold(2024, 9)

    assert fold["train_start"].isoformat().startswith("2024-09-01")
    assert fold["train_end"].isoformat().startswith("2025-02-28")
    assert fold["holdout_start"].isoformat().startswith("2025-03-01")
    assert fold["holdout_end"].isoformat().startswith("2025-05-31")
    assert fold["holdout_start"] > fold["train_end"]


def test_aggregate_uses_weighted_roi_and_true_even_median() -> None:
    summary = _aggregate([
        {"bets": 2, "staked": 10, "profit": -1, "roi_pct": -10, "max_drawdown": 4},
        {"bets": 3, "staked": 30, "profit": 9, "roi_pct": 30, "max_drawdown": 8},
    ])

    assert summary == {
        "folds": 2,
        "positive_folds": 1,
        "bets": 5,
        "staked": 40.0,
        "profit": 8.0,
        "roi_pct": 20.0,
        "median_fold_roi_pct": 10.0,
        "worst_fold_roi_pct": -10.0,
        "max_fold_drawdown": 8.0,
    }
