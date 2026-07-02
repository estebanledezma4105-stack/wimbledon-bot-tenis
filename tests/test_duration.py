import pytest
from match_duration import MatchDuration

def test_baseline_duration_is_2_5_hours():
    duration = MatchDuration()
    base = duration.baseline_minutes()
    assert base == 150

def test_duration_estimate_returns_minutes():
    duration = MatchDuration()
    est = duration.estimate("Alcaraz", "Djokovic", recent_a=[150], recent_b=[180])
    assert isinstance(est, int)
    assert 120 < est < 300
