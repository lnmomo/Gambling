import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import market_bias_portfolio_simulation as portfolio_simulation  # noqa: E402
from market_bias_portfolio_simulation import simulate_settlement_portfolio  # noqa: E402


def test_settlement_portfolio_uses_daily_limit_and_settled_cooldown_only():
    bets = pd.DataFrame([
        {"date": "2027-01-01", "league": "I2", "home_team": "A", "away_team": "B", "outcome": "draw", "actual_result": "home", "odds": 3.0, "won": False, "rule_label": "r"},
        {"date": "2027-01-01", "league": "I2", "home_team": "C", "away_team": "D", "outcome": "draw", "actual_result": "away", "odds": 3.0, "won": False, "rule_label": "r"},
        {"date": "2027-01-02", "league": "I2", "home_team": "E", "away_team": "F", "outcome": "draw", "actual_result": "draw", "odds": 3.0, "won": True, "rule_label": "r"},
    ])
    summary, daily, placed = simulate_settlement_portfolio(
        bets,
        daily_limit=100.0,
        max_single_stake=60.0,
        settlement_delay_days=1,
        stop_after_losing_settlement_days=1,
        cooldown_days=3,
    )
    day1 = daily[daily["date"] == "2027-01-01"].iloc[0]
    day2 = daily[daily["date"] == "2027-01-02"].iloc[0]
    assert day1["staked"] == 100.0
    assert day2["settled_profit"] == -100.0
    assert day2["staked"] == 0.0
    assert day2["skipped_reason"] == "cooldown_after_losing_settlement_days"
    assert len(placed) == 2
    assert summary["overall"]["profit"] == -100.0


def test_custom_portfolio_rule_does_not_include_default_i2_rule(monkeypatch):
    captured = {}

    def fake_run_walk_forward(seasons, first_month, last_month, rules, lookback_months, min_active_months,
                              min_bets, min_roi, max_rules, daily_limit, odds_source):
        captured["rules"] = rules
        return {"config": {}, "overall": {}}, pd.DataFrame(), pd.DataFrame()

    def fake_simulate_settlement_portfolio(bets, daily_limit, max_single_stake, settlement_delay_days,
                                           stop_after_losing_settlement_days, cooldown_days):
        return {"overall": {}, "config": {}}, pd.DataFrame(), pd.DataFrame()

    monkeypatch.setattr(portfolio_simulation, "run_walk_forward", fake_run_walk_forward)
    monkeypatch.setattr(portfolio_simulation, "simulate_settlement_portfolio", fake_simulate_settlement_portfolio)

    portfolio_simulation.run_from_walk_forward(Namespace(
        seasons="2122",
        first_month="2022-08",
        last_month="2022-08",
        rule=["league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]"],
        lookback_months=12,
        min_active_months=6,
        min_bets=50,
        min_roi=0.02,
        max_rules=3,
        daily_limit=100.0,
        odds_source="AVG_OPEN",
        max_single_stake=10.0,
        settlement_delay_days=1,
        stop_after_losing_settlement_days=999,
        cooldown_days=0,
    ))

    assert captured["rules"] == [(("league", "outcome", "market_prob_bucket"), ("SP1", "home", "[0.55,1.00]"))]


def test_custom_i2_band_portfolio_rule_uses_custom_band(monkeypatch):
    captured = {}

    def fake_build_market_frame(seasons, odds_source):
        return pd.DataFrame([
            {"league": "I2", "outcome": "draw", "odds": 3.2},
        ])

    def fake_run_walk_forward_frame(frame, seasons, first_month, last_month, rules, lookback_months,
                                    min_active_months, min_bets, min_roi, max_rules, daily_limit, odds_source):
        captured["rules"] = rules
        captured["band_values"] = frame["custom_i2_draw_band"].tolist()
        return {"config": {}, "overall": {}}, pd.DataFrame(), pd.DataFrame()

    def fake_simulate_settlement_portfolio(bets, daily_limit, max_single_stake, settlement_delay_days,
                                           stop_after_losing_settlement_days, cooldown_days):
        return {"overall": {}, "config": {}}, pd.DataFrame(), pd.DataFrame()

    monkeypatch.setattr(portfolio_simulation, "build_market_frame", fake_build_market_frame)
    monkeypatch.setattr(portfolio_simulation, "run_walk_forward_frame", fake_run_walk_forward_frame)
    monkeypatch.setattr(portfolio_simulation, "simulate_settlement_portfolio", fake_simulate_settlement_portfolio)

    portfolio_simulation.run_from_walk_forward(Namespace(
        seasons="2122",
        first_month="2022-08",
        last_month="2022-08",
        rule=None,
        lookback_months=12,
        min_active_months=6,
        min_bets=50,
        min_roi=0.02,
        max_rules=1,
        daily_limit=100.0,
        odds_source="AVG_OPEN",
        max_single_stake=10.0,
        settlement_delay_days=1,
        stop_after_losing_settlement_days=999,
        cooldown_days=0,
        i2_draw_band_low=2.8,
        i2_draw_band_high=3.3,
    ))

    assert captured["rules"] == [(("league", "outcome", "custom_i2_draw_band"), ("I2", "draw", "[2.80,3.30)"))]
    assert captured["band_values"] == ["[2.80,3.30)"]
