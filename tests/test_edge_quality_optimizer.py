from football_agents.edge_quality_optimizer import run_edge_quality_optimization
from football_agents.true_odds_config import generate_true_odds_config_grid


def rows(count=80):
    output = []
    for index in range(count):
        home_score = 2 if index % 3 == 0 else 1 if index % 3 == 1 else 0
        away_score = 0 if index % 3 == 0 else 1 if index % 3 == 1 else 2
        output.append({
            "id": f"m{index}",
            "date": f"2025-01-{(index % 28) + 1:02d}",
            "league": "Test League",
            "home_team": f"Home {index % 6}",
            "away_team": f"Away {index % 6}",
            "home_score": home_score,
            "away_score": away_score,
            "sp_home": 2.1 + (index % 4) * 0.1,
            "sp_draw": 3.2,
            "sp_away": 3.4 - (index % 3) * 0.1,
            "closing_home": 2.05 + (index % 4) * 0.08,
            "closing_draw": 3.25,
            "closing_away": 3.35,
        })
    return output


def test_optimizer_runs_multiple_configs_and_returns_best_config():
    configs = generate_true_odds_config_grid({"max_configs": 8})
    result = run_edge_quality_optimization(rows(), None, configs, {"min_samples": 50})
    assert len(result.variant_results) == len(configs)
    assert result.best_config is not None
    assert result.ranking
    assert result.promotion_decision in {"KEEP_CURRENT", "ENABLE_FILTER_ONLY", "NEED_MORE_DATA", "REJECT_TRUE_ODDS_FILTER", "SHADOW_ONLY"}
    assert all(isinstance(item["score"], float) for item in result.ranking)


def test_optimizer_needs_more_data_for_small_sample():
    result = run_edge_quality_optimization(rows(12), None, None, {"max_configs": 5, "min_samples": 200})
    assert result.promotion_decision == "NEED_MORE_DATA"
    assert not result.recommended_for_production
