from __future__ import annotations

from scripts.i2_sp1_band_stability_scan import BandCandidate, SP1_HOME_RULE, make_band_candidates


def test_band_candidate_uses_custom_i2_rule_plus_fixed_sp1_home_rule():
    candidate = BandCandidate(2.9, 3.4)

    assert candidate.candidate_id == "market-bias-i2-draw-2.90-3.40-plus-sp1-home-v1"
    assert candidate.rules == (
        "league|outcome|custom_i2_draw_band=I2|draw|[2.90,3.40)",
        SP1_HOME_RULE,
    )


def test_make_band_candidates_respects_minimum_width():
    candidates = make_band_candidates([2.8, 3.2], [3.0, 3.3], min_width=0.25)

    assert [(item.low, item.high) for item in candidates] == [
        (2.8, 3.3),
    ]
