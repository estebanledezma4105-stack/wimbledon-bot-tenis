import pytest
from odds_validator import OddsValidator

def test_american_to_probability():
    validator = OddsValidator()
    prob = validator.american_to_probability(-120)
    assert 0.54 < prob < 0.55

def test_decimal_to_probability():
    validator = OddsValidator()
    prob = validator.decimal_to_probability(1.83)
    assert 0.54 < prob < 0.55

def test_identify_value_bets():
    validator = OddsValidator()
    model_prob = 0.65
    implied_prob = 0.55
    is_value = validator.is_value(model_prob, implied_prob, min_ev=0.05)
    assert is_value is True

    is_value = validator.is_value(0.55, 0.65, min_ev=0.05)
    assert is_value is False
