from football_agents.true_odds_engine import calculate_true_odds_estimate


def test_true_odds_estimate_generates_edges_and_fair_odds():
    estimate = calculate_true_odds_estimate(
        {"id": 1, "official_match_id": "M1", "league": "Test"},
        {
            "officialSp": {"home": 2.1, "draw": 3.2, "away": 3.4},
            "finalProbability": {"home": .50, "draw": .27, "away": .23},
            "pureModelProbability": {"home": .49, "draw": .28, "away": .23},
            "features": {"source_confidence": .8, "lambda_home": 1.4, "lambda_away": 1.0},
        },
        {"selected_outcome": "HOME", "selected_odds": 2.1, "model_disagreement": "LOW", "external_market_quality": "HIGH"},
    )
    assert set(estimate.edge_quality_by_outcome) == {"HOME", "DRAW", "AWAY"}
    assert abs(sum(estimate.true_probability_estimate.values()) - 1) < 1e-9
    assert estimate.true_fair_odds["home"] == 1 / estimate.true_probability_estimate["home"]
    assert estimate.selected_edge.outcome in {"HOME", "DRAW", "AWAY", "NO_BET"}


def test_true_odds_estimate_does_not_turn_raw_longshot_model_ev_into_real_ev():
    estimate = calculate_true_odds_estimate(
        {"id": 1, "official_match_id": "M2", "league": "Test"},
        {
            "officialSp": {"home": 1.55, "draw": 4.2, "away": 6.0},
            "finalProbability": {"home": .50, "draw": .25, "away": .25},
            "pureModelProbability": {"home": .49, "draw": .26, "away": .25},
            "features": {"source_confidence": .7, "lambda_home": 1.8, "lambda_away": .7},
        },
        {"model_disagreement": "LOW", "external_market_quality": "MEDIUM"},
    )

    raw_away_ev = .25 * 6.0 - 1.0
    assert raw_away_ev == 0.5
    assert estimate.real_ev["away"] < 0.05
    assert estimate.edge_quality_by_outcome["AWAY"].expected_ev < 0.05
    assert not estimate.edge_quality_by_outcome["AWAY"].passes_true_odds_filter
    assert estimate.real_ev_calibration["longshot_penalties"]["away"] > 0
