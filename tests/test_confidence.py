import pytest
from confidence import ConfidenceScorer

def test_confidence_high_with_rich_data():
    scorer = ConfidenceScorer()
    data = {
        'h2h_matches': 15,
        'form_window_size': 8,
        'grass_winrate': 0.72,
        'total_matches': 200,
    }
    conf = scorer.score(data)
    assert conf['level'] == 'HIGH'
    assert conf['score'] > 0.75

def test_confidence_medium_with_partial_data():
    scorer = ConfidenceScorer()
    data = {
        'h2h_matches': 2,
        'form_window_size': 3,
        'grass_winrate': 0.65,
        'total_matches': 50,
    }
    conf = scorer.score(data)
    assert conf['level'] == 'MEDIUM'
    assert 0.5 < conf['score'] < 0.75

def test_confidence_low_with_sparse_data():
    scorer = ConfidenceScorer()
    data = {
        'h2h_matches': 0,
        'form_window_size': 0,
        'grass_winrate': None,
        'total_matches': 5,
    }
    conf = scorer.score(data)
    assert conf['level'] == 'LOW'
    assert conf['score'] < 0.5
