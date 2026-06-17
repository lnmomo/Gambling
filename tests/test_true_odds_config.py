import math

from football_agents.true_odds_config import (
    TrueOddsFilterConfig,
    generate_true_odds_config_grid,
    get_default_true_odds_filter_config,
    validate_true_odds_config,
)


def test_default_config_is_valid_and_not_adjust_probability():
    config = get_default_true_odds_filter_config()
    valid, warnings = validate_true_odds_config(config)
    assert valid, warnings
    assert config.mode == "FILTER_ONLY"
    assert config.mode != "ADJUST_PROBABILITY"


def test_config_grid_is_reasonable_and_finite():
    grid = generate_true_odds_config_grid({"max_configs": 40})
    assert 7 <= len(grid) <= 40
    assert all(validate_true_odds_config(config)[0] for config in grid)
    assert all(math.isfinite(config.lower_bound_ev_min) for config in grid)


def test_validate_rejects_invalid_values():
    config = TrueOddsFilterConfig(config_id="bad", name="Bad", lower_bound_ev_min=0.2, edge_quality_min_score=120)
    valid, warnings = validate_true_odds_config(config)
    assert not valid
    assert warnings
