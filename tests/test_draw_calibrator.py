from football_agents.draw_calibrator import calibrate_draw_probability


def test_low_lambda_raises_draw_with_small_cap():
    adjusted, details = calibrate_draw_probability({"home": .45, "draw": .25, "away": .30}, {"lambda_home": 1.0, "lambda_away": .9, "sample_count": 100})
    assert adjusted["draw"] > .25
    assert details["draw_delta"] <= .025
    assert abs(sum(adjusted.values()) - 1) < 1e-9


def test_missing_lambda_is_safe():
    adjusted, _ = calibrate_draw_probability({"home": .45, "draw": .25, "away": .30}, {})
    assert abs(sum(adjusted.values()) - 1) < 1e-9
