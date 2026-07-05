from football_agents.real_ev import anchor_real_probability, real_ev_by_outcome


def test_longshot_positive_model_residual_is_heavily_discounted():
    probability, diagnostics = anchor_real_probability(
        {"home": 0.50, "draw": 0.25, "away": 0.25},
        {"home": 0.60, "draw": 0.25, "away": 0.15},
        {"home": 1.55, "draw": 4.2, "away": 6.0},
        reliability=0.7,
    )

    assert probability["away"] < 0.17
    assert diagnostics.longshot_penalties["away"] > 0
    assert "away longshot positive residual discounted" in diagnostics.warnings


def test_real_ev_uses_anchored_probability_not_raw_model_probability():
    probability, _ = anchor_real_probability(
        {"home": 0.50, "draw": 0.25, "away": 0.25},
        {"home": 0.60, "draw": 0.25, "away": 0.15},
        {"home": 1.55, "draw": 4.2, "away": 6.0},
        reliability=0.7,
    )
    ev = real_ev_by_outcome(probability, {"home": 1.55, "draw": 4.2, "away": 6.0})

    assert ev["away"] < 0.05
