from football_agents.adaptive_threshold import calculate_adaptive_ev_threshold


def test_adaptive_threshold_bounds_and_quality_adjustments():
    high = calculate_adaptive_ev_threshold({"odds": 2}, {}, {"externalMarketQuality": "HIGH"})
    low = calculate_adaptive_ev_threshold({"odds": 2}, {}, {"externalMarketQuality": "LOW"})
    assert 0.02 <= high <= 0.10
    assert 0.02 <= low <= 0.10
    assert high < low


def test_draw_and_long_odds_raise_threshold():
    normal = calculate_adaptive_ev_threshold({"outcome": "HOME", "odds": 2}, {}, {"externalMarketQuality": "MEDIUM"})
    draw_long = calculate_adaptive_ev_threshold({"outcome": "DRAW", "odds": 6}, {}, {"externalMarketQuality": "MEDIUM"})
    assert draw_long > normal
