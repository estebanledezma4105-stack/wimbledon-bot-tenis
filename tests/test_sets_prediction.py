# tests/test_sets_prediction.py
import pytest
from predictions import SetsPrediction

def test_set_win_probability_from_ratings():
    pred = SetsPrediction()
    set_prob = pred.set_win_probability(match_prob=0.65)
    assert 0.60 < set_prob < 0.70

def test_match_score_probability_3_0():
    pred = SetsPrediction()
    prob_3_0 = pred.match_score_probability(set_win_prob=0.70, score="3-0")
    expected = 0.70 ** 3
    assert abs(prob_3_0 - expected) < 0.001

def test_match_score_probability_3_1():
    pred = SetsPrediction()
    prob_3_1 = pred.match_score_probability(set_win_prob=0.70, score="3-1")
    expected = 3 * (0.70 ** 3) * 0.30
    assert abs(prob_3_1 - expected) < 0.001

def test_all_match_outcomes_sum_to_one():
    pred = SetsPrediction()
    set_prob = 0.60
    total = (
        pred.match_score_probability(set_prob, "3-0") +
        pred.match_score_probability(set_prob, "3-1") +
        pred.match_score_probability(set_prob, "3-2") +
        pred.match_score_probability(set_prob, "2-3") +
        pred.match_score_probability(set_prob, "1-3") +
        pred.match_score_probability(set_prob, "0-3")
    )
    assert abs(total - 1.0) < 0.001
