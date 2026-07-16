from scripts.pooled_current_pool_market_anchored import pooled_config


def test_pooled_config_is_fixed_and_market_anchored():
    config = pooled_config("AVG_CLOSE", ("USA", "NOR", "BRA"))

    assert config.selected_rules == ("USA", "NOR", "BRA")
    assert config.train_months == 30
    assert config.validation_months == 6
    assert config.require_probability_improvement is True
    assert config.require_validation_tail_edge is True
    assert config.min_validation_selections == 30
    assert config.residual_cap == 0.03
    assert (config.min_odds, config.max_odds) == (1.8, 4.0)
