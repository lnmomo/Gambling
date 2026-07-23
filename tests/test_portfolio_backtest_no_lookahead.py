from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from football_agents.portfolio_backtest import (
    BacktestConfig,
    MatchRecord,
    _LeagueLambdaState,
    _resolve_price,
    _sharp_devig,
    load_football_data_rows,
    run_daily_portfolio,
)


def _match(day: datetime, home: str, away: str, ftr: str) -> MatchRecord:
    scores = {"H": (2, 0), "D": (1, 1), "A": (0, 2)}[ftr]
    return MatchRecord(
        kickoff=day,
        league="TST",
        home_team=home,
        away_team=away,
        home_score=scores[0],
        away_score=scores[1],
        ftr=ftr,
        odds_home=10.0,
        odds_draw=10.0,
        odds_away=10.0,
    )


def _config() -> BacktestConfig:
    return BacktestConfig(
        name="no-lookahead-test",
        min_ev=-1.0,
        residual_retention=1.0,
        selection="ev",
        drawdown_control=False,
    )


def _bet(report: dict, match: str) -> dict:
    return next(row for row in report["bets_sample"] if row["match"] == match)


def test_same_day_result_cannot_change_another_same_day_prediction() -> None:
    day = datetime(2026, 1, 2)
    home_win = [_match(day, "A", "B", "H"), _match(day, "A", "C", "D")]
    away_win = [_match(day, "A", "B", "A"), _match(day, "A", "C", "D")]

    first = run_daily_portfolio(home_win, _config(), day, day)
    second = run_daily_portfolio(away_win, _config(), day, day)

    assert _bet(first, "A v C")["outcome"] == _bet(second, "A v C")["outcome"]
    assert _bet(first, "A v C")["probability"] == _bet(second, "A v C")["probability"]


def test_pre_window_results_warm_up_the_model_without_entering_test_profit() -> None:
    start = datetime(2026, 1, 2)
    warmup_day = start - timedelta(days=1)
    target = _match(start, "A", "C", "D")
    home_history = [_match(warmup_day, "A", "B", "H"), target]
    away_history = [_match(warmup_day, "A", "B", "A"), target]

    first = run_daily_portfolio(home_history, _config(), start, start)
    second = run_daily_portfolio(away_history, _config(), start, start)

    assert first["warmup_matches"] == 1
    assert first["matches_in_window"] == 1
    assert _bet(first, "A v C")["probability"] != _bet(second, "A v C")["probability"]


def test_market_devig_uses_one_sharp_book_not_cross_book_max_prices() -> None:
    record = MatchRecord(
        kickoff=datetime(2026, 1, 2), league="TST", home_team="A", away_team="B",
        home_score=0, away_score=0, ftr="D",
        odds_home=2.0, odds_draw=3.0, odds_away=4.0,
        max_odds_home=2.4, max_odds_draw=3.7, max_odds_away=5.0,
    )

    probabilities = _sharp_devig(record)

    assert probabilities["home"] == 6 / 13
    assert probabilities["draw"] == 4 / 13
    assert probabilities["away"] == 3 / 13


def test_loader_uses_opening_prices_and_never_closing_c_suffix_fields(tmp_path: Path) -> None:
    source = tmp_path / "E0.csv"
    source.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSH,PSD,PSA,MaxH,MaxD,MaxA,B365H,B365D,B365A,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA\n"
        "01/01/2026,Home,Away,1,0,H,2.1,3.2,4.1,2.2,3.3,4.2,2.0,3.0,4.0,91,92,93,94,95,96\n",
        encoding="utf-8",
    )

    rows = load_football_data_rows([str(tmp_path)], leagues=("E0",))

    assert len(rows) == 1
    assert (rows[0].odds_home, rows[0].odds_draw, rows[0].odds_away) == (2.1, 3.2, 4.1)
    assert (rows[0].max_odds_home, rows[0].max_odds_draw, rows[0].max_odds_away) == (2.2, 3.3, 4.2)
    assert rows[0].price_source == "pinnacle_opening"


def test_loader_never_mixes_a_partial_pinnacle_triplet_with_bet365(tmp_path: Path) -> None:
    source = tmp_path / "E0.csv"
    source.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSH,PSD,PSA,B365H,B365D,B365A\n"
        "01/01/2026,Home,Away,1,0,H,2.1,,4.1,2.0,3.0,4.0\n",
        encoding="utf-8",
    )

    rows = load_football_data_rows([str(tmp_path)], leagues=("E0",))

    assert len(rows) == 1
    assert (rows[0].odds_home, rows[0].odds_draw, rows[0].odds_away) == (2.0, 3.0, 4.0)
    assert rows[0].price_source == "bet365_opening"


def test_loader_can_require_one_named_book_for_every_match(tmp_path: Path) -> None:
    source = tmp_path / "E0.csv"
    source.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSH,PSD,PSA,B365H,B365D,B365A\n"
        "01/01/2026,Home,Away,1,0,H,2.1,3.2,4.1,2.0,3.0,4.0\n",
        encoding="utf-8",
    )

    rows = load_football_data_rows(
        [str(tmp_path)], primary_price_source="bet365", leagues=("E0",)
    )

    assert len(rows) == 1
    assert (rows[0].odds_home, rows[0].odds_draw, rows[0].odds_away) == (2.0, 3.0, 4.0)
    assert rows[0].price_source == "bet365_opening"


def test_closing_price_mode_is_rejected() -> None:
    day = datetime(2026, 1, 2)
    config = BacktestConfig(
        name="invalid-closing-mode", market_price_timing="closing", drawdown_control=False,
    )

    try:
        run_daily_portfolio([_match(day, "A", "B", "H")], config, day, day)
    except ValueError as exc:
        assert "opening prices" in str(exc)
    else:
        raise AssertionError("closing-price decisions must be rejected")


def test_cross_book_max_price_is_not_an_executable_default() -> None:
    record = MatchRecord(
        kickoff=datetime(2026, 1, 2), league="TST", home_team="A", away_team="B",
        home_score=1, away_score=0, ftr="H",
        odds_home=2.0, odds_draw=3.0, odds_away=4.0,
        soft_odds_home=2.0, max_odds_home=2.2,
    )
    config = BacktestConfig(bet_region="max_edge", max_edge_ratio=1.05)

    _odds, allowed = _resolve_price(config, "home", record.odds_home, record)

    assert not allowed


def test_named_book_edge_requires_complete_pinnacle_reference_and_bet365_price_gap() -> None:
    record = MatchRecord(
        kickoff=datetime(2026, 1, 2), league="TST", home_team="A", away_team="B",
        home_score=1, away_score=0, ftr="H",
        odds_home=2.1, odds_draw=3.1, odds_away=4.1,
        price_source="bet365_opening",
        pinnacle_odds_home=2.0, pinnacle_odds_draw=3.0, pinnacle_odds_away=4.0,
    )
    config = BacktestConfig(bet_region="named_book_edge", named_book_edge_ratio=1.03)

    _odds, allowed = _resolve_price(config, "home", record.odds_home, record)

    assert allowed
    incomplete = MatchRecord(
        kickoff=record.kickoff, league=record.league, home_team=record.home_team,
        away_team=record.away_team, home_score=record.home_score, away_score=record.away_score,
        ftr=record.ftr, odds_home=record.odds_home, odds_draw=record.odds_draw,
        odds_away=record.odds_away, price_source="bet365_opening",
        pinnacle_odds_home=2.0, pinnacle_odds_draw=float("nan"), pinnacle_odds_away=4.0,
    )
    _odds, allowed = _resolve_price(config, "home", incomplete.odds_home, incomplete)
    assert not allowed


def test_attack_defence_lambda_pairs_scoring_with_opponent_conceding() -> None:
    state = _LeagueLambdaState()
    day = datetime(2026, 1, 1)
    state.update("TST", "A", "B", 3, 0, day)
    state.update("TST", "C", "D", 0, 3, day)

    home_rate, away_rate, sample_count = state.lambdas(
        "TST", "A", "B", day + timedelta(days=1), "attack_defence"
    )
    legacy_home_rate, legacy_away_rate, _ = state.lambdas(
        "TST", "A", "B", day + timedelta(days=1), "legacy"
    )

    assert sample_count == 1
    assert home_rate > away_rate
    # The corrected estimator is deliberately distinct from the old formula,
    # which used the opponent's attack as a proxy for its defensive weakness.
    assert (home_rate, away_rate) != (legacy_home_rate, legacy_away_rate)
