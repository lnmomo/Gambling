from __future__ import annotations

from dataclasses import dataclass, field

from .multi_devig import Probability, calculate_multi_devig_probabilities


@dataclass
class ClosingLineProxy:
    opening_probability: Probability | None
    recommendation_probability: Probability | None
    closing_probability: Probability | None
    closing_devig_method: str
    recommendation_to_closing_delta: dict[str, float]
    selected_outcome_clv: float | None
    expected_closing_edge: float | None
    clv_win_probability: float
    available: bool
    warnings: list[str] = field(default_factory=list)


def build_closing_line_proxy(recommendation_snapshot: dict | None, closing_snapshot: dict | None, selected_outcome: str, devig_method: str = "POWER") -> ClosingLineProxy:
    if not recommendation_snapshot or not closing_snapshot:
        return ClosingLineProxy(None, None, None, devig_method, {}, None, None, 0.5, False, ["closing snapshot unavailable"])
    rec_sp = recommendation_snapshot.get("official_sp") or recommendation_snapshot.get("sp") or recommendation_snapshot
    closing_sp = closing_snapshot.get("official_sp") or closing_snapshot.get("sp") or closing_snapshot
    rec = calculate_multi_devig_probabilities(rec_sp, {"recommended_method": devig_method, "source": "recommendation"})
    close = calculate_multi_devig_probabilities(closing_sp, {"recommended_method": devig_method, "source": "closing"})
    selected = selected_outcome.lower()
    if selected not in ("home", "draw", "away") or not rec.methods[rec.recommended_method].valid or not close.methods[close.recommended_method].valid:
        return ClosingLineProxy(rec.recommended_probability, None, None, devig_method, {}, None, None, 0.5, False, ["closing proxy input invalid"])
    clv = rec_sp[selected] / closing_sp[selected] - 1
    edge = close.recommended_probability[selected] * rec_sp[selected] - 1
    win_prob = 0.60 if clv > 0 else 0.40 if clv < 0 else 0.50
    delta = {key: rec.recommended_probability[key] - close.recommended_probability[key] for key in ("home", "draw", "away")}
    return ClosingLineProxy(None, rec.recommended_probability, close.recommended_probability, close.recommended_method, delta, clv, edge, win_prob, True, ["clv_win_probability fallback used"])
