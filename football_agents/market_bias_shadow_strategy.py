from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


I2_DRAW_STRATEGY_ID = "market-bias-i2-draw-2.8-3.5-v1"
SP1_HOME_STRATEGY_ID = "market-bias-sp1-home-market-prob-0.55-1.00-v1"
I2_SP1_COMBO_STRATEGY_ID = "market-bias-i2-draw-plus-sp1-home-v1"
JPN_AWAY_PROB28_34_RESEARCH_ID = "research-market-bias-jpn-away-market-prob-0.28-0.34-v1"
MARKET_BIAS_PORTFOLIO_STRATEGIES = {
    I2_SP1_COMBO_STRATEGY_ID: {I2_DRAW_STRATEGY_ID, SP1_HOME_STRATEGY_ID},
}

I2_LEAGUE_ALIASES = {
    "i2",
    "italian serie b",
    "italy serie b",
    "serie b",
}

SP1_LEAGUE_ALIASES = {
    "sp1",
    "spanish la liga",
    "spain la liga",
    "la liga",
    "laliga",
}

JPN_LEAGUE_ALIASES = {
    "jpn",
    "japan j1 league",
    "japanese j1 league",
    "j1 league",
    "j-league",
    "j league",
}


@dataclass(frozen=True)
class MarketBiasShadowCandidate:
    strategy_id: str
    league_family: str
    outcome: str
    rule_type: str
    min_sp: float | None
    max_sp: float | None
    min_market_probability: float | None
    max_market_probability: float | None
    selected_sp: float
    selected_market_probability: float | None
    expected_roi: float
    evidence: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketBiasResearchCandidate:
    strategy_id: str
    validation_stage: str
    league_family: str
    outcome: str
    rule_type: str
    min_sp: float | None
    max_sp: float | None
    min_market_probability: float | None
    max_market_probability: float | None
    selected_sp: float
    selected_market_probability: float | None
    evidence: str
    reason: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_league(value: Any) -> str:
    return str(value or "").strip().casefold()


def is_i2_league(league: Any) -> bool:
    raw = str(league or "")
    normalized = _normalize_league(raw)
    return normalized in I2_LEAGUE_ALIASES or "serie b" in normalized or "\u610f\u4e59" in raw


def is_sp1_league(league: Any) -> bool:
    raw = str(league or "")
    normalized = _normalize_league(raw)
    return (
        normalized in SP1_LEAGUE_ALIASES
        or "la liga" in normalized
        or "\u897f\u7532" in raw
    )


def is_jpn_league(league: Any) -> bool:
    raw = str(league or "")
    normalized = _normalize_league(raw)
    return (
        normalized in JPN_LEAGUE_ALIASES
        or "j1 league" in normalized
        or "\u65e5\u804c" in raw
        or "\u65e5\u672c\u804c\u4e1a" in raw
    )


def _sp_value(official_sp: dict[str, Any], key: str) -> float | None:
    try:
        value = float(official_sp.get(key) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 1 else None


def _devig_market_probabilities(official_sp: dict[str, Any]) -> dict[str, float] | None:
    odds = {key: _sp_value(official_sp, key) for key in ("home", "draw", "away")}
    if any(value is None for value in odds.values()):
        return None
    inverse = {key: 1 / float(value) for key, value in odds.items()}
    total = sum(inverse.values())
    if total <= 0:
        return None
    return {key: inverse[key] / total for key in inverse}


def _i2_draw_candidate(match: dict[str, Any], official_sp: dict[str, Any]) -> MarketBiasShadowCandidate | None:
    """Frozen research challenger: Italy Serie B draw in the validated price band.

    This is deliberately narrow. It should be evaluated through live shadow
    settlement before being promoted to any production recommendation logic.
    """
    if not is_i2_league(match.get("league")):
        return None
    try:
        draw_sp = float(official_sp.get("draw") or 0)
    except (TypeError, ValueError):
        return None
    if not 2.8 <= draw_sp < 3.5:
        return None
    return MarketBiasShadowCandidate(
        strategy_id=I2_DRAW_STRATEGY_ID,
        league_family="I2",
        outcome="DRAW",
        rule_type="odds_band",
        min_sp=2.8,
        max_sp=3.5,
        min_market_probability=None,
        max_market_probability=None,
        selected_sp=draw_sp,
        selected_market_probability=None,
        expected_roi=0.0774,
        evidence="AVG_CLOSE sensitivity floor: 863 bets, +66.79 units, 7.74% ROI; AVG_OPEN: 871 bets, +82.76 units, 9.50% ROI",
        reason="Italy Serie B draw SP is inside the frozen market-bias validation band [2.8,3.5).",
    )


def _sp1_home_high_market_probability_research_candidate(
    match: dict[str, Any], official_sp: dict[str, Any],
) -> MarketBiasResearchCandidate | None:
    """Research-only challenger: SP1 home side when market-implied home probability is high.

    Full-period ROI is attractive, but the 12-month multi-window gate only
    passed 2/12 windows, so this must not create shadow picks by default.
    """
    if not is_sp1_league(match.get("league")):
        return None
    market_probabilities = _devig_market_probabilities(official_sp)
    home_sp = _sp_value(official_sp, "home")
    if market_probabilities is None or home_sp is None:
        return None
    home_probability = market_probabilities["home"]
    if home_probability < 0.55:
        return None
    return MarketBiasResearchCandidate(
        strategy_id=SP1_HOME_STRATEGY_ID,
        validation_stage="RESEARCH_ONLY_UNSTABLE_WINDOWS",
        league_family="SP1",
        outcome="HOME",
        rule_type="market_probability_band",
        min_sp=None,
        max_sp=None,
        min_market_probability=0.55,
        max_market_probability=1.0,
        selected_sp=home_sp,
        selected_market_probability=round(home_probability, 6),
        evidence=(
            "High full-period ROI, but multi-window validation is unstable: "
            "2/12 windows passed across AVG_OPEN and AVG_CLOSE; keep research-only."
        ),
        reason="Spanish La Liga home SP has devigged market probability >= 0.55, matching an unstable research rule.",
        warnings=(
            "research-only: SP1 did not pass the multi-window shadow gate",
            "do not create shadow recommendations from this rule until rolling-window stability improves",
        ),
    )


def _jpn_away_mid_market_probability_research_candidate(
    match: dict[str, Any], official_sp: dict[str, Any],
) -> MarketBiasResearchCandidate | None:
    """Research-only watchlist candidate.

    This rule has historical signal but failed full source-diversity promotion
    gates. It must not be converted into live shadow or production picks until
    official-SP prospective validation catches up.
    """
    if not is_jpn_league(match.get("league")):
        return None
    market_probabilities = _devig_market_probabilities(official_sp)
    away_sp = _sp_value(official_sp, "away")
    if market_probabilities is None or away_sp is None:
        return None
    away_probability = market_probabilities["away"]
    if not 0.28 <= away_probability < 0.34:
        return None
    return MarketBiasResearchCandidate(
        strategy_id=JPN_AWAY_PROB28_34_RESEARCH_ID,
        validation_stage="RESEARCH_WATCH_ONLY",
        league_family="JPN",
        outcome="AWAY",
        rule_type="market_probability_band",
        min_sp=None,
        max_sp=None,
        min_market_probability=0.28,
        max_market_probability=0.34,
        selected_sp=away_sp,
        selected_market_probability=round(away_probability, 6),
        evidence=(
            "Worldwide close-odds scan: robustness 4/12, source passes 2/4; "
            "AVG_CLOSE portfolio 339 bets, +211.40 stake units, 6.24% ROI; "
            "MAX_CLOSE 456 bets, +770.70 stake units, 16.90% ROI; PS_CLOSE latest-season weakness."
        ),
        reason="Japanese J1 away SP has devigged market probability in the research band [0.28,0.34).",
        warnings=(
            "research-only: do not create shadow recommendations from this rule yet",
            "insufficient source diversity for promotion",
            "requires prospective Chinese official-SP validation before any betting use",
        ),
    )


def find_market_bias_shadow_candidates(match: dict[str, Any], official_sp: dict[str, Any]) -> list[MarketBiasShadowCandidate]:
    candidates = []
    for finder in (
        _i2_draw_candidate,
    ):
        candidate = finder(match, official_sp)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def find_market_bias_research_candidates(match: dict[str, Any], official_sp: dict[str, Any]) -> list[MarketBiasResearchCandidate]:
    candidates = []
    for finder in (
        _sp1_home_high_market_probability_research_candidate,
        _jpn_away_mid_market_probability_research_candidate,
    ):
        candidate = finder(match, official_sp)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def find_market_bias_shadow_candidate(match: dict[str, Any], official_sp: dict[str, Any]) -> MarketBiasShadowCandidate | None:
    candidates = find_market_bias_shadow_candidates(match, official_sp)
    return candidates[0] if candidates else None


def expand_market_bias_strategy_id(strategy_id: str | None) -> set[str] | None:
    if not strategy_id:
        return None
    return MARKET_BIAS_PORTFOLIO_STRATEGIES.get(strategy_id, {strategy_id})
