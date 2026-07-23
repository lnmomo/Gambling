"""Leak-free daily portfolio backtest harness.

Drives the real football-data.co.uk pre-match opening 1X2 odds through the project's
probability stack (online Elo + Poisson + Ensemble) and the paper-portfolio
risk caps (quarter-Kelly stake sizing, daily budget, tiered drawdown breaker)
to simulate one bet per selected outcome per day, settling against the real
FTR, and reporting profit / ROI / max drawdown.

Leakage discipline (matches the immutable prospective ledger rules):
  * Elo ratings and Poisson lambdas are computed using only matches whose
    kickoff is strictly before the current match (predict-before-update).
  * The stake for a day's matches is frozen from features known at kickoff;
    only the day's *result* (FTR) is revealed after the stakes are frozen.
  * The tiered risk breaker reads only previously settled days, never the
    current day's profit, so the day's stake multiplier cannot peek at the
    outcome it is about to settle.

This harness is a backtest simulation tool. It never places a real bet and
has no order-placement interface. ENABLE_AUTO_BETTING stays false.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from .models import EloModel, EnsembleModel, PoissonModel
from .models.ensemble import market_probabilities
from .paper_portfolio import RISK_POLICY, settled_risk_state


OUTCOMES = ("home", "draw", "away")
FTR_MAP = {"H": "home", "D": "draw", "A": "away"}


@dataclass
class BacktestConfig:
    """Knobs that define an *algorithm variant* to compare on the same month."""

    name: str = "baseline-ensemble"
    # The loader only supplies pre-match opening fields. A different timing is
    # rejected so a future change cannot silently use closing information.
    market_price_timing: str = "opening"
    # A backtest may restrict decisions to one named, internally consistent
    # bookmaker feed. ``any`` retains the loader's per-match primary source;
    # it never combines outcomes from different books.
    execution_price_source: str = "any"  # any | pinnacle_opening | bet365_opening
    # ``MaxH/MaxD/MaxA`` are cross-book aggregates without a named executable
    # venue. They are therefore disabled by default, rather than silently
    # becoming an investable price in a portfolio replay.
    allow_unattributed_cross_book_max: bool = False
    daily_budget: float = 100.0
    unit_stake: float = 10.0
    # Starting capital the daily stakes draw against. Seeds the equity curve so
    # the tiered-breaker's drawdown *fraction* is meaningful from day one
    # (otherwise a single early loss on a near-zero peak trips PAUSED).
    starting_bankroll: float = 1000.0
    # Ensemble mixing weights (elo / poisson / market).
    weights: dict[str, float] = field(
        default_factory=lambda: {"elo": 0.20, "poisson": 0.45, "market": 0.35}
    )
    # Minimum EV gate (probability * odds - 1) required to place a bet.
    min_ev: float = 0.03
    # Optional executable-price interval. Kept optional for generic model
    # tests; investment candidates should state an explicit interval.
    minimum_odds: float | None = None
    maximum_odds: float | None = None
    # Cap per single bet as a fraction of the effective daily budget.
    max_single_fraction: float = 0.10
    # Fraction of full Kelly to stake (paper-portfolio default is 0.25).
    kelly_fraction: float = 0.25
    # How much of the model-vs-market residual to retain (0=pure market,
    # 1=pure model). Lower trusts the opening market more.
    residual_retention: float = 1.0
    # Drawdown control on/off (CAUTION/DEFENSIVE/PAUSED scaling of stakes).
    drawdown_control: bool = True
    # If True, pick the single highest-EV outcome per match; else skip.
    one_bet_per_match: bool = True
    # Selection criterion when one_bet_per_match is True:
    #   "ev"   — highest model EV (good when the model carries the edge);
    #   "prob" — highest de-vigged market probability (the strong favourite),
    #            correct for structural line-shopping strategies where the edge
    #            is in the price gap, not the model — picking by EV there would
    #            favour the longer-odds (less likely) outcome, the value sink.
    selection: str = "ev"
    # Candidate region filter. The structural edge in this data lives in
    # strong favourites (market prob >= favorite_min) and, to a lesser degree,
    # mid-prob home/draw. Longshots are a value sink (-20% ROI). Restricting
    # candidates to a region is an *algorithm* lever, not month-cherry-picking.
    bet_region: str = "all"  # all | strong_favorite | favorite_lean | mid_home | max_edge | named_book_edge
    favorite_min: float = 0.55
    favorite_lean_min: float = 0.45
    mid_home_min: float = 0.45
    mid_home_max: float = 0.55
    # "max edge": the best (Max) opening price beats the soft-book (B365)
    # baseline by >= max_edge_ratio. This selects value-priced bets.
    max_edge_ratio: float = 1.05
    # When max_edge is required, bet the Max price (sharpest/best obtainable)
    # rather than the soft-book baseline.
    use_max_price_when_edge: bool = True
    # Minimum B365/Pinnacle price ratio for the named-book market-dislocation
    # hypothesis. Both source triplets must exist; this never consumes Max*.
    named_book_edge_ratio: float = 1.02
    # Optional override of the tiered-breaker policy dict for this variant
    # only (does not touch the global paper_portfolio.RISK_POLICY). Used by
    # the optimization loop to compare breaker strengths on the same edge.
    risk_policy_override: dict[str, Any] | None = None
    # Goal-rate estimator used by the walk-forward Poisson component.
    # ``attack_defence`` matches the production feature builder: each team's
    # decayed scoring rate is paired with the opponent's conceded-goals rate
    # and both are shrunk toward the league mean when samples are thin.
    # ``legacy`` is retained only as a historical benchmark.
    lambda_engine: str = "attack_defence"


@dataclass
class MatchRecord:
    kickoff: datetime
    league: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    ftr: str  # 'H' / 'D' / 'A'
    odds_home: float
    odds_draw: float
    odds_away: float
    # Provenance of the complete primary 1X2 quote used for both de-vigging
    # and settlement pricing. This is deliberately not inferred per outcome.
    price_source: str = "unknown"
    # Complete named Pinnacle opening triplet retained even when the execution
    # source is B365, so a source-attributed comparison can be audited.
    pinnacle_odds_home: float = float("nan")
    pinnacle_odds_draw: float = float("nan")
    pinnacle_odds_away: float = float("nan")
    # Best (max) opening 1X2 across bookmakers, used to detect a "max edge".
    # Closing fields use a C suffix in football-data and are never read.
    # (best price beats the typical soft-book B365 line) — a structural value
    # signal independent of the model.
    max_odds_home: float = float("nan")
    max_odds_draw: float = float("nan")
    max_odds_away: float = float("nan")
    # Soft-book (B365) opening 1X2, used as the bettable price baseline.
    soft_odds_home: float = float("nan")
    soft_odds_draw: float = float("nan")
    soft_odds_away: float = float("nan")


@dataclass
class BetRecord:
    date: str
    league: str
    match: str
    outcome: str
    probability: float
    odds: float
    ev: float
    stake: float
    profit: float
    hit: bool


def _parse_date(value: str) -> datetime:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")


def _safe_float(value: Any) -> float:
    try:
        text = str(value).strip()
        return float(text) if text else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def load_football_data_rows(
    season_dirs: Iterable[str],
    primary_price_source: str = "prefer_pinnacle",
    leagues: tuple[str, ...] = (
        "E0", "E1", "E2", "E3", "SP1", "SP2", "I1", "I2", "D1", "D2",
        "F1", "F2", "N1", "B1", "P1", "T1", "G1", "SC0",
    ),
) -> list[MatchRecord]:
    """Load real football-data.co.uk opening-price rows into match records.

    ``prefer_pinnacle`` uses a complete pre-match Pinnacle PSH/PSD/PSA triplet
    when present, otherwise a complete B365H/B365D/B365A triplet. ``pinnacle``
    and ``bet365`` require that named source for every retained match. It never
    mixes outcomes across books. Closing columns have a C suffix (for example
    PSCH) and are deliberately excluded from decisions.
    """
    import csv
    import os

    if primary_price_source not in {"prefer_pinnacle", "pinnacle", "bet365"}:
        raise ValueError("primary_price_source must be prefer_pinnacle, pinnacle, or bet365")
    records: list[MatchRecord] = []
    for season_dir in season_dirs:
        for league in leagues:
            path = os.path.join(season_dir, f"{league}.csv")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    ftr = (row.get("FTR") or "").strip()
                    if ftr not in FTR_MAP:
                        continue
                    try:
                        kickoff = _parse_date(row["Date"])
                    except (KeyError, ValueError):
                        continue
                    pinnacle = tuple(_safe_float(row.get(field)) for field in ("PSH", "PSD", "PSA"))
                    bet365 = tuple(_safe_float(row.get(field)) for field in ("B365H", "B365D", "B365A"))
                    has_pinnacle = all(math.isfinite(value) and value > 1.0 for value in pinnacle)
                    has_bet365 = all(math.isfinite(value) and value > 1.0 for value in bet365)
                    if primary_price_source in {"prefer_pinnacle", "pinnacle"} and has_pinnacle:
                        oh, od, oa = pinnacle
                        price_source = "pinnacle_opening"
                    elif primary_price_source in {"prefer_pinnacle", "bet365"} and has_bet365:
                        oh, od, oa = bet365
                        price_source = "bet365_opening"
                    else:
                        continue
                    records.append(
                        MatchRecord(
                            kickoff=kickoff,
                            league=league,
                            home_team=(row.get("HomeTeam") or "").strip(),
                            away_team=(row.get("AwayTeam") or "").strip(),
                            home_score=int(_safe_float(row.get("FTHG") or 0)),
                            away_score=int(_safe_float(row.get("FTAG") or 0)),
                            ftr=ftr,
                            odds_home=oh,
                            odds_draw=od,
                            odds_away=oa,
                            price_source=price_source,
                            pinnacle_odds_home=pinnacle[0],
                            pinnacle_odds_draw=pinnacle[1],
                            pinnacle_odds_away=pinnacle[2],
                            max_odds_home=_safe_float(row.get("MaxH")),
                            max_odds_draw=_safe_float(row.get("MaxD")),
                            max_odds_away=_safe_float(row.get("MaxA")),
                            soft_odds_home=_safe_float(row.get("B365H")),
                            soft_odds_draw=_safe_float(row.get("B365D")),
                            soft_odds_away=_safe_float(row.get("B365A")),
                        )
                    )
    records.sort(key=lambda m: m.kickoff)
    return records


def _team_key(league: str, team: str) -> str:
    return f"{league}::{team}"


class _LeagueEloState:
    """Per-league online Elo so cross-league ratings never contaminate."""

    def __init__(self) -> None:
        from collections import defaultdict

        self.elo = EloModel()
        self._seen: set[str] = set()
        self._default = defaultdict(lambda: 1500.0)

    def rating(self, league: str, team: str) -> float:
        key = _team_key(league, team)
        return self.elo.rating(key) if key in self._seen else self._default[key]

    def predict(self, league: str, home: str, away: str) -> dict[str, float]:
        return self.elo.predict(_team_key(league, home), _team_key(league, away))

    def update(self, league: str, home: str, away: str, hs: int, as_: int) -> None:
        self.elo.update(_team_key(league, home), _team_key(league, away), hs, as_)
        self._seen.add(_team_key(league, home))
        self._seen.add(_team_key(league, away))


class _LeagueLambdaState:
    """Time-decayed attack/defence goals for Poisson lambdas, per league."""

    HALF_LIFE_DAYS = 90.0

    def __init__(self) -> None:
        from collections import defaultdict

        self._home: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._away: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._goals_for: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._goals_against: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._league_avg: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

    def _decay_sum(self, series: list[tuple[datetime, float]], as_of: datetime) -> tuple[float, float]:
        total_w = 0.0
        total_v = 0.0
        for ts, val in series:
            age = (as_of - ts).total_seconds() / 86400.0
            if age < 0:
                continue
            w = 0.5 ** (age / self.HALF_LIFE_DAYS)
            total_w += w
            total_v += w * val
        return total_v, total_w

    def _team_attack_defence(
        self, league: str, team: str, as_of: datetime
    ) -> tuple[float, float, int]:
        home_v, home_w = self._decay_sum(self._home[_team_key(league, team)], as_of)
        away_v, away_w = self._decay_sum(self._away[_team_key(league, team)], as_of)
        eff_home = home_w
        eff_away = away_w
        reliability = min(1.0, (eff_home + eff_away) / 20.0)
        league_avg_v, league_avg_w = self._decay_sum(self._league_avg[league], as_of)
        league_goals_per_team = (
            league_avg_v / league_avg_w if league_avg_w > 0 else 1.4
        )
        # Guard against an unsighted team returning zero division.
        home_goals = home_v / home_w if home_w > 0 else league_goals_per_team
        away_goals = away_v / away_w if away_w > 0 else league_goals_per_team
        if league_goals_per_team <= 0:
            league_goals_per_team = 1.4
        attack = (home_goals + away_goals) / (2.0 * league_goals_per_team)
        attack = 1.0 + reliability * (attack - 1.0)
        defence = 1.0  # simplified symmetric defence; lambda is attack-scaled
        return attack, defence, int(eff_home + eff_away)

    def _legacy_lambdas(self, league: str, home: str, away: str, as_of: datetime) -> tuple[float, float, int]:
        h_atk, _h_def, n_home = self._team_attack_defence(league, home, as_of)
        a_atk, _a_def, n_away = self._team_attack_defence(league, away, as_of)
        league_avg_v, league_avg_w = self._decay_sum(self._league_avg[league], as_of)
        base = league_avg_v / league_avg_w if league_avg_w > 0 else 1.35
        # Home advantage ~1.08, defence read as the opponent's attack inverse.
        lambda_home = max(0.25, min(4.0, base * 1.08 * h_atk / max(a_atk, 0.1)))
        lambda_away = max(0.20, min(3.5, base * a_atk / max(h_atk, 0.1)))
        return lambda_home, lambda_away, min(n_home, n_away)

    def _shrunk_ratio(self, values: list[tuple[datetime, float]], baseline: float,
                      as_of: datetime) -> tuple[float, int]:
        total, weight = self._decay_sum(values, as_of)
        observed = total / weight if weight > 0 else baseline
        reliability = min(1.0, weight / 20.0)
        ratio = 1.0 + reliability * (observed / max(baseline, 0.1) - 1.0)
        # ``weight`` is fractional after time decay, so casting it to int
        # makes a real one-match sample look like zero observations.
        return ratio, len(values)

    def _attack_defence_lambdas(
        self, league: str, home: str, away: str, as_of: datetime
    ) -> tuple[float, float, int]:
        league_total, league_weight = self._decay_sum(self._league_avg[league], as_of)
        baseline = league_total / league_weight if league_weight > 0 else 1.35
        home_key, away_key = _team_key(league, home), _team_key(league, away)
        home_attack, n_home = self._shrunk_ratio(self._goals_for[home_key], baseline, as_of)
        home_defence, _ = self._shrunk_ratio(self._goals_against[home_key], baseline, as_of)
        away_attack, n_away = self._shrunk_ratio(self._goals_for[away_key], baseline, as_of)
        away_defence, _ = self._shrunk_ratio(self._goals_against[away_key], baseline, as_of)
        lambda_home = max(0.25, min(4.0, baseline * 1.08 * home_attack * away_defence))
        lambda_away = max(0.20, min(3.5, baseline / 1.08 * away_attack * home_defence))
        return lambda_home, lambda_away, min(n_home, n_away)

    def lambdas(self, league: str, home: str, away: str, as_of: datetime,
                engine: str = "attack_defence") -> tuple[float, float, int]:
        if engine == "legacy":
            return self._legacy_lambdas(league, home, away, as_of)
        return self._attack_defence_lambdas(league, home, away, as_of)

    def update(self, league: str, home: str, away: str, hs: int, as_: int, ts: datetime) -> None:
        self._home[_team_key(league, home)].append((ts, hs))
        self._away[_team_key(league, away)].append((ts, as_))
        self._goals_for[_team_key(league, home)].append((ts, hs))
        self._goals_against[_team_key(league, home)].append((ts, as_))
        self._goals_for[_team_key(league, away)].append((ts, as_))
        self._goals_against[_team_key(league, away)].append((ts, hs))
        self._league_avg[league].append((ts, (hs + as_) / 2.0))


def _quarter_kelly(probability: float, odds: float, fraction: float) -> float:
    full = (probability * odds - 1.0) / (odds - 1.0)
    return max(0.0, min(0.10, full * fraction))


def _flat_stake(config: BacktestConfig, effective_budget: float) -> float:
    """Flat per-bet stake for structural (line-shopping) strategies.

    When the bet's edge comes from the price gap rather than the model EV
    (so model-EV may be ~0), fractional-Kelly sizing shrinks to dust. A flat
    stake sized to the budget is the correct knob for max_edge strategies.
    """
    stake = min(config.max_single_fraction * effective_budget, config.daily_budget * 0.10)
    return round(max(0.0, stake), 2)


def _market_anchored_probability(
    model_p: dict[str, float],
    market_p: dict[str, float],
    retention: float,
) -> dict[str, float]:
    """Blend model residual into the market prior.

    retention=1.0 keeps the pure model probability; retention=0.0 returns the
    de-vigged market probability. This mirrors the production
    `anchor_real_probability` residual-retention idea without its full cap
    machinery, so variants can be compared cleanly.
    """
    if retention >= 1.0:
        return model_p
    if retention <= 0.0:
        return market_p
    blended = {
        k: market_p[k] + retention * (model_p[k] - market_p[k]) for k in OUTCOMES
    }
    total = sum(blended.values())
    return {k: v / total for k, v in blended.items()}


def _in_bet_region(config: BacktestConfig, outcome: str, market_p: float) -> bool:
    """Structural candidate filter (algorithm lever, not month selection)."""
    region = getattr(config, "bet_region", "all")
    if region == "all":
        return True
    if region == "strong_favorite":
        return market_p >= config.favorite_min
    if region == "favorite_lean":
        return market_p >= config.favorite_lean_min
    if region == "mid_home":
        return (
            outcome == "home"
            and config.mid_home_min <= market_p <= config.mid_home_max
        )
    if region == "max_edge":
        # Region is decided per-bet in _resolve_price (needs the max/soft
        # odds pair); here allow all, the edge test filters inside.
        return True
    if region == "named_book_edge":
        # Price eligibility is checked in _resolve_price; no model-derived
        # favourite filter is applied to this independent-market hypothesis.
        return True
    return True


def _resolve_price(
    config: BacktestConfig,
    outcome: str,
    base_odds: float,
    m: MatchRecord,
) -> tuple[float, bool]:
    """Return (bettable_odds, passed_region_filter).

    For the max_edge region, a candidate passes only if the best opening price
    beats the soft-book baseline by >= max_edge_ratio; the bet is then struck
    at that best price. For other regions the base odds are used as-is.
    """
    region = getattr(config, "bet_region", "all")
    if region == "named_book_edge":
        if m.price_source != "bet365_opening":
            return base_odds, False
        if not all(
            math.isfinite(value) and value > 1.0
            for value in (m.pinnacle_odds_home, m.pinnacle_odds_draw, m.pinnacle_odds_away)
        ):
            return base_odds, False
        reference = {
            "home": m.pinnacle_odds_home,
            "draw": m.pinnacle_odds_draw,
            "away": m.pinnacle_odds_away,
        }[outcome]
        if not math.isfinite(reference) or reference <= 1.0:
            return base_odds, False
        return base_odds, base_odds >= reference * config.named_book_edge_ratio
    if region != "max_edge":
        return base_odds, True
    if not config.allow_unattributed_cross_book_max:
        return base_odds, False
    soft = {
        "home": m.soft_odds_home,
        "draw": m.soft_odds_draw,
        "away": m.soft_odds_away,
    }[outcome]
    mx = {
        "home": m.max_odds_home,
        "draw": m.max_odds_draw,
        "away": m.max_odds_away,
    }[outcome]
    if math.isnan(mx) or mx <= 1.0:
        return base_odds, False
    baseline = soft if (not math.isnan(soft) and soft > 1.0) else base_odds
    if mx < baseline * config.max_edge_ratio:
        return base_odds, False
    # Also require the de-vigged market probability to clear favorite_min so
    # the edge concentrates on strong favourites (where edge>=1.05 was the
    # only structurally +EV shape across all 9 months).
    devig = _multiplicative_devig(m)
    if devig[outcome] < config.favorite_min:
        return base_odds, False
    return (mx if config.use_max_price_when_edge else base_odds), True


def _multiplicative_devig(m: MatchRecord) -> dict[str, float]:
    """De-vigged market consensus probabilities.

    Uses one internally consistent opening 1X2 book. ``odds_*`` is Pinnacle
    when available and B365 otherwise. ``Max*`` cannot be used here because
    its three outcomes may come from different bookmakers, so joining them
    would fabricate a market probability vector that was never simultaneously
    available.
    """
    raw = [1.0 / m.odds_home, 1.0 / m.odds_draw, 1.0 / m.odds_away]
    s = sum(raw)
    return {"home": raw[0] / s, "draw": raw[1] / s, "away": raw[2] / s}


def _sharp_devig(m: MatchRecord) -> dict[str, float]:
    """De-vig using the sharp Pinnacle line; falls back to max-devig."""
    # MatchRecord carries the sharp line on its primary odds_* fields (the
    # loader prefers PSH/PSD/PSA), so multiplicative devig of odds_* already
    # is the sharp devig. This helper exists for clarity at call sites.
    return _multiplicative_devig(m)


def _pinnacle_devig(m: MatchRecord) -> dict[str, float] | None:
    """Return a complete named Pinnacle opening probability vector, if present."""
    odds = (m.pinnacle_odds_home, m.pinnacle_odds_draw, m.pinnacle_odds_away)
    if not all(math.isfinite(value) and value > 1.0 for value in odds):
        return None
    raw = [1.0 / value for value in odds]
    total = sum(raw)
    return {"home": raw[0] / total, "draw": raw[1] / total, "away": raw[2] / total}


def _stake_for(
    probability: float,
    odds: float,
    config: BacktestConfig,
    effective_budget: float,
    used_today: float,
    league_room: float,
    outcome_room: float,
) -> float:
    if getattr(config, "bet_region", "all") == "max_edge":
        # Structural line-shopping edge: flat stake, not Kelly (model EV ~ 0).
        flat = _flat_stake(config, effective_budget)
    else:
        flat = float("inf")
    fraction = _quarter_kelly(probability, odds, config.kelly_fraction)
    if fraction <= 0 and flat == float("inf"):
        return 0.0
    kelly_stake = effective_budget * fraction
    max_single = config.max_single_fraction * effective_budget
    budget_room = max(0.0, effective_budget - used_today)
    stake = min(
        kelly_stake if flat == float("inf") else flat,
        flat if flat != float("inf") else max_single,
        max_single,
        budget_room,
        league_room,
        outcome_room,
    )
    return round(max(0.0, stake), 2)


def run_daily_portfolio(
    records: list[MatchRecord],
    config: BacktestConfig,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Walk-forward daily portfolio simulation over real matches.

    Returns a report dict with daily equity, bets, profit, ROI, max drawdown,
    and the tiered-risk state trajectory. Purely a paper simulation.
    """
    elo_state = _LeagueEloState()
    lambda_state = _LeagueLambdaState()
    poisson = PoissonModel()
    ensemble = EnsembleModel(weights=config.weights)

    # If this variant overrides the tiered-breaker policy, apply it for the
    # duration of the run without mutating the global RISK_POLICY (which the
    # immutable paper-portfolio service still reads in production).
    import contextlib

    @contextlib.contextmanager
    def _scoped_policy():
        if not config.risk_policy_override:
            yield
            return
        saved = dict(RISK_POLICY)
        RISK_POLICY.clear()
        RISK_POLICY.update(saved)
        RISK_POLICY.update(config.risk_policy_override)
        try:
            yield
        finally:
            RISK_POLICY.clear()
            RISK_POLICY.update(saved)

    with _scoped_policy():
        return _run_daily_portfolio_inner(
            records, config, start, end, elo_state, lambda_state,
            poisson, ensemble,
        )


def _run_daily_portfolio_inner(
    records: list[MatchRecord],
    config: BacktestConfig,
    start: datetime | None,
    end: datetime | None,
    elo_state: _LeagueEloState,
    lambda_state: _LeagueLambdaState,
    poisson: PoissonModel,
    ensemble: EnsembleModel,
) -> dict[str, Any]:
    """Body of the daily portfolio sim; runs under the scoped risk policy."""
    if config.market_price_timing != "opening":
        raise ValueError("daily portfolio decisions require pre-match opening prices")
    ordered_records = sorted(records, key=lambda item: item.kickoff)
    start_dt = start or ordered_records[0].kickoff
    end_dt = end or ordered_records[-1].kickoff
    warmup = [m for m in ordered_records if m.kickoff < start_dt]
    for match in warmup:
        _update_states(elo_state, lambda_state, match)
    window = [m for m in ordered_records if start_dt <= m.kickoff <= end_dt]
    by_day: dict[str, list[MatchRecord]] = {}
    for m in window:
        by_day.setdefault(m.kickoff.date().isoformat(), []).append(m)

    settled_daily: list[dict[str, Any]] = [
        # Seed the rolling 30-day drawdown window with the starting bankroll so
        # the *fraction* (drawdown / peak) is measured against real capital,
        # not a near-zero window-local peak that a few losses would push above
        # 1.0 and trip a spurious PAUSE.
        {"date": "BANKROLL_SEED", "profit": config.starting_bankroll}
    ]
    last_settled_at: datetime | None = None
    bets: list[BetRecord] = []
    equity = config.starting_bankroll
    peak = config.starting_bankroll
    max_drawdown = 0.0
    daily_rows: list[dict[str, Any]] = []

    for day in sorted(by_day):
        matches = by_day[day]
        day_dt = datetime.combine(
            matches[0].kickoff.date(), datetime.min.time(), tzinfo=matches[0].kickoff.tzinfo
        )
        if config.drawdown_control:
            risk = settled_risk_state(
                settled_daily, day_dt, config.daily_budget, last_settled_at
            )
            stake_mult = float(risk["stake_multiplier"])
            risk_status = risk["status"]
        else:
            risk = None
            stake_mult = 1.0
            risk_status = "NORMAL"
        effective_budget = config.daily_budget * stake_mult
        used = 0.0
        league_used: dict[str, float] = {}
        outcome_used: dict[str, float] = {}

        day_bets: list[BetRecord] = []
        # Candidate pool for the day, scored once per match so a multi-bet
        # strategy can rank across matches (not just within one). Pool entries
        # carry (match, outcome, p, odds, ev) so the daily budget is allocated
        # to the best daily candidates, mirroring the production allocate()
        # which orders by predicted EV.
        daily_pool: list[tuple] = []
        for m in matches:
            if (
                config.execution_price_source != "any"
                and m.price_source != config.execution_price_source
            ):
                continue
            odds = {"home": m.odds_home, "draw": m.odds_draw, "away": m.odds_away}
            # The de-vigged *sharp market consensus* (best/sharp closing price,
            # margin removed) is the structural signal for the max_edge region
            # and a stronger prior than the soft-book line for blending.
            devig_p = _sharp_devig(m)
            elo_p = elo_state.predict(m.league, m.home_team, m.away_team)
            lambda_home, lambda_away, _n = lambda_state.lambdas(
                m.league, m.home_team, m.away_team, m.kickoff, config.lambda_engine
            )
            poisson_p = poisson.predict(lambda_home, lambda_away)
            model_p = ensemble.predict(
                {"elo": elo_p, "poisson": poisson_p, "market": devig_p}
            )
            final_p = _market_anchored_probability(model_p, devig_p, config.residual_retention)
            if config.bet_region == "named_book_edge":
                final_p = _pinnacle_devig(m)
                if final_p is None:
                    continue
            match_candidates = []
            for outcome in OUTCOMES:
                p = final_p[outcome]
                bet_odds, region_ok = _resolve_price(
                    config, outcome, odds[outcome], m
                )
                if not region_ok:
                    continue
                if config.minimum_odds is not None and bet_odds < config.minimum_odds:
                    continue
                if config.maximum_odds is not None and bet_odds > config.maximum_odds:
                    continue
                ev = p * bet_odds - 1.0
                if ev < config.min_ev:
                    continue
                if not _in_bet_region(config, outcome, devig_p[outcome]):
                    continue
                match_candidates.append((outcome, p, bet_odds, ev))
            if not match_candidates:
                continue
            if config.one_bet_per_match:
                if getattr(config, "selection", "ev") == "prob":
                    match_candidates.sort(key=lambda c: c[1], reverse=True)
                else:
                    match_candidates.sort(key=lambda c: c[3], reverse=True)
                match_candidates = match_candidates[:1]
            for outcome, p, o, ev in match_candidates:
                daily_pool.append((m, outcome, p, o, ev))

        # Rank the day's pool by EV descending and allocate the daily budget to
        # the top candidates until exhausted (same logic the production
        # PaperPortfolioService uses for its candidate ordering).
        daily_pool.sort(key=lambda c: c[4], reverse=True)
        for m, outcome, p, o, ev in daily_pool:
            league_room = (
                config.daily_budget * RISK_POLICY["maximum_league_daily_share"]
                - league_used.get(m.league, 0.0)
            )
            outcome_room = (
                config.daily_budget * RISK_POLICY["maximum_outcome_daily_share"]
                - outcome_used.get(outcome, 0.0)
            )
            if o >= RISK_POLICY["longshot_odds_threshold"]:
                outcome_room = min(
                    outcome_room,
                    config.daily_budget * RISK_POLICY["maximum_longshot_daily_share"]
                    - outcome_used.get(outcome, 0.0),
                )
            stake = _stake_for(
                p, o, config, effective_budget, used, league_room, outcome_room
            )
            if stake <= 0:
                continue
            used += stake
            league_used[m.league] = league_used.get(m.league, 0.0) + stake
            outcome_used[outcome] = outcome_used.get(outcome, 0.0) + stake
            actual = FTR_MAP[m.ftr]
            hit = actual == outcome
            profit = round(stake * (o - 1.0) if hit else -stake, 2)
            bet = BetRecord(
                date=day,
                league=m.league,
                match=f"{m.home_team} v {m.away_team}",
                outcome=outcome,
                probability=round(p, 4),
                odds=o,
                ev=round(ev, 4),
                stake=stake,
                profit=profit,
                hit=hit,
            )
            day_bets.append(bet)
            bets.append(bet)

        # The source CSV has match dates but no reliable kickoff times. Freeze
        # every decision for the date before revealing any result from that date.
        for match in matches:
            _update_states(elo_state, lambda_state, match)

        day_profit = round(sum(b.profit for b in day_bets), 2)
        day_staked = round(sum(b.stake for b in day_bets), 2)
        equity += day_profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if day_bets:
            settled_daily.append({"date": day, "profit": day_profit})
            last_settled_at = day_dt.replace(
                hour=23, minute=59, second=59, microsecond=0
            )
        # Surface the breaker's drawdown diagnostics for the daily row (the
        # values computed before this day's stake was frozen). None when the
        # drawdown control is disabled.
        risk_drawdown_frac = None
        risk_rolling_frac = None
        if risk:
            risk_drawdown_frac = risk.get("current_drawdown_fraction")
            risk_rolling_frac = risk.get("rolling_max_drawdown_fraction")
        daily_rows.append(
            {
                "date": day,
                "bets": len(day_bets),
                "staked": day_staked,
                "profit": day_profit,
                "equity": round(equity, 2),
                "drawdown": round(peak - equity, 2),
                "risk_status": risk_status,
                "stake_multiplier": stake_mult,
                "effective_budget": round(effective_budget, 2),
                "current_drawdown_fraction": risk_drawdown_frac,
                "rolling_max_drawdown_fraction": risk_rolling_frac,
            }
        )

    total_staked = round(sum(b.stake for b in bets), 2)
    total_profit = round(sum(b.profit for b in bets), 2)
    wins = sum(1 for b in bets if b.hit)
    return {
        "config_name": config.name,
        "market_price_timing": config.market_price_timing,
        "execution_price_source": config.execution_price_source,
        "allow_unattributed_cross_book_max": config.allow_unattributed_cross_book_max,
        "daily_budget": config.daily_budget,
        "min_ev": config.min_ev,
        "minimum_odds": config.minimum_odds,
        "maximum_odds": config.maximum_odds,
        "weights": config.weights,
        "residual_retention": config.residual_retention,
        "drawdown_control": config.drawdown_control,
        "bet_region": config.bet_region,
        "favorite_min": config.favorite_min,
        "favorite_lean_min": config.favorite_lean_min,
        "kelly_fraction": config.kelly_fraction,
        "starting_bankroll": config.starting_bankroll,
        "max_edge_ratio": config.max_edge_ratio,
        "named_book_edge_ratio": config.named_book_edge_ratio,
        "lambda_engine": config.lambda_engine,
        "period_start": (start_dt.date().isoformat() if start_dt else None),
        "period_end": (end_dt.date().isoformat() if end_dt else None),
        "warmup_matches": len(warmup),
        "matches_in_window": len(window),
        "betting_days": len(by_day),
        "bets": len(bets),
        "staked": total_staked,
        "profit": total_profit,
        "roi_pct": round(total_profit / total_staked * 100, 2) if total_staked else 0.0,
        "win_rate": round(wins / len(bets), 4) if bets else 0.0,
        "max_drawdown": round(max_drawdown, 2),
        "ending_equity": round(equity, 2),
        "daily_rows": daily_rows,
        "bets_sample": [
            {
                "date": b.date,
                "league": b.league,
                "match": b.match,
                "outcome": b.outcome,
                "probability": b.probability,
                "odds": b.odds,
                "ev": b.ev,
                "stake": b.stake,
                "profit": b.profit,
                "hit": b.hit,
            }
            for b in bets[:50]
        ],
    }


def _update_states(
    elo_state: _LeagueEloState,
    lambda_state: _LeagueLambdaState,
    m: MatchRecord,
) -> None:
    """Reveal the result AFTER prediction (predict-before-update, no leakage)."""
    elo_state.update(m.league, m.home_team, m.away_team, m.home_score, m.away_score)
    lambda_state.update(
        m.league, m.home_team, m.away_team, m.home_score, m.away_score, m.kickoff
    )
