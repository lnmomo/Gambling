import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rolling_low_correlation_rule_selector import _load_market_candidates, run_rolling_selector  # noqa: E402


def _row(month: str, league: str, outcome: str, profit: float) -> dict:
    return {
        "date": f"{month}-01",
        "month": month,
        "league": league,
        "home_team": f"H-{league}-{month}",
        "away_team": f"A-{league}-{month}",
        "outcome": outcome,
        "actual_result": outcome if profit > 0 else "draw",
        "odds": profit + 1 if profit > 0 else 2.0,
        "odds_bucket": "[2.2,2.8)",
        "market_probability": 0.4,
        "market_prob_bucket": "[0.34,0.42)",
        "favorite_relation": "market_favorite",
        "odds_source": "AVG_CLOSE",
        "won": profit > 0,
        "unit_profit": profit,
        "stake": 1.0,
        "profit": profit,
    }


def test_rolling_selector_uses_only_past_training_data():
    rows = []
    for month in pd.period_range("2023-01", "2023-12", freq="M").astype(str):
        rows.append(_row(month, "PAST_A", "home", 1.2))
        rows.append(_row(month, "PAST_B", "away", 1.1))
    for month in pd.period_range("2024-01", "2024-12", freq="M").astype(str):
        rows.append(_row(month, "FUTURE_ONLY", "home", 5.0))
        rows.append(_row(month, "PAST_A", "home", 1.2))
        rows.append(_row(month, "PAST_B", "away", 1.1))

    result = run_rolling_selector(
        pd.DataFrame(rows),
        first_validation_month="2024-01",
        last_validation_month="2024-12",
        train_months=12,
        validation_months=12,
        step_months=12,
        max_feature_combo_size=3,
        require_outcome=True,
        require_price_bucket=True,
        max_rules=10,
        combo_size=2,
        min_rule_bets=6,
        min_rule_active_months=6,
        min_rule_roi_pct=0.0,
        max_pairwise_corr=1.0,
        require_latest_non_negative=True,
        train_validation_months=12,
        train_step_months=12,
        min_train_pass_rate=0.0,
        min_window_bets=1,
        min_window_roi_pct=0.0,
        min_positive_month_edge=-12,
        max_drawdown_to_profit=999.0,
    )

    selected = result["windows"][0]["selected_rules"]
    assert selected
    assert all("FUTURE_ONLY" not in rule for rule in selected)
    assert result["summary"]["active_window_count"] == 1


def test_loader_accepts_unit_bet_profit_column(tmp_path):
    path = tmp_path / "unit_bets.csv"
    pd.DataFrame([_row("2024-01", "L", "home", 1.2)]).drop(columns=["unit_profit"]).to_csv(path, index=False)

    frame = _load_market_candidates([path])

    assert frame.loc[0, "profit"] == 1.2
    assert frame.loc[0, "month"] == "2024-01"
