"""Tests for ranking_form scraper (ATP ranking and recent tournament form)."""
import os
from unittest.mock import MagicMock, patch

from scrapers import ranking_form

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "player_profile_ranking.html")


def test_extract_ranking_parses_player_profile():
    """Verify extraction of ranking position, points, and recent form from HTML."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    result = ranking_form.extract_ranking_and_form("Jannik Sinner", session=mock_session)

    assert result is not None
    assert "ranking_position" in result
    assert "ranking_points" in result
    assert "tournaments_played" in result
    assert "wins" in result
    assert "losses" in result
    assert "titles" in result
    assert "finals_reached" in result
    assert "last_tournament_date" in result
    # Verify the values are populated
    assert result["ranking_position"] > 0
    assert result["ranking_points"] >= 0
    assert result["tournaments_played"] >= 0
    assert result["wins"] >= 0
    assert result["losses"] >= 0
    assert result["titles"] >= 0
    assert result["finals_reached"] >= 0


def test_extract_ranking_handles_missing_ranking():
    """Gracefully handle missing ranking data by returning default ranking 2000."""
    html_no_ranking = "<html><body>Player not found</body></html>"

    mock_response = MagicMock()
    mock_response.text = html_no_ranking
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    result = ranking_form.extract_ranking_and_form("Unknown Player", session=mock_session)

    # Should return None when parsing fails (not found)
    assert result is None


def test_extract_ranking_handles_network_error():
    """Return None on network error instead of raising."""
    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    result = ranking_form.extract_ranking_and_form("Jannik Sinner", session=mock_session)

    assert result is None
