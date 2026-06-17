from football_agents.multi_devig import DevigMethod, calculate_multi_devig_probabilities


def test_multi_devig_methods_are_valid_and_sum_to_one():
    result = calculate_multi_devig_probabilities({"home": 2.10, "draw": 3.20, "away": 3.40})
    assert result.recommended_method == DevigMethod.POWER.value
    assert result.method_agreement_score > 0
    for method in DevigMethod:
        row = result.methods[method.value]
        assert row.valid
        assert abs(sum(row.probability.values()) - 1) < 1e-9
        assert all(value > 1 for value in row.fair_odds.values())
    assert result.method_spread["max"] >= 0


def test_invalid_odds_do_not_raise_or_emit_nan():
    result = calculate_multi_devig_probabilities({"home": 1.0, "draw": 0, "away": 3.4})
    assert "invalid odds" in result.warnings
    assert all(not row.valid for row in result.methods.values())
    assert abs(sum(result.recommended_probability.values()) - 1) < 1e-9
