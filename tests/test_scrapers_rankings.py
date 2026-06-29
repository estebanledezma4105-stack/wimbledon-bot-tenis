import os
from unittest.mock import MagicMock

import db
from scrapers import rankings

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "rankings_atp.html")


def test_parse_rankings_html_extracts_players():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = rankings.parse_rankings_html(html)
    assert parsed == [
        {"rank": 1, "name": "Jannik Sinner"},
        {"rank": 2, "name": "Carlos Alcaraz"},
        {"rank": 3, "name": "Alexander Zverev"},
    ]


def test_parse_rankings_html_returns_empty_list_on_unexpected_structure():
    parsed = rankings.parse_rankings_html("<html><body>nothing here</body></html>")
    assert parsed == []


def test_parse_rankings_html_skips_decoy_result_tables():
    """tennisexplorer.com renders a date-picker table with class="result"
    before the real rankings table — the parser must not pick it up."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = rankings.parse_rankings_html(html)
    names = [entry["name"] for entry in parsed]
    assert "29. 06. 2026" not in names
    assert len(parsed) == 3


def test_normalize_name_swaps_two_token_names():
    assert rankings._normalize_name("Sinner Jannik") == "Jannik Sinner"


def test_normalize_name_leaves_multiword_names_unchanged():
    assert rankings._normalize_name("Van De Zandschulp Botic") == "Van De Zandschulp Botic"


def test_run_writes_players_and_logs_success(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = rankings.run(db_path, session=mock_session)
    assert rows == 3

    with db.get_connection(db_path) as conn:
        players = conn.execute("SELECT name, ranking FROM players ORDER BY ranking").fetchall()
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'rankings'").fetchone()

    assert [p["name"] for p in players] == ["Jannik Sinner", "Carlos Alcaraz", "Alexander Zverev"]
    assert run_log["status"] == "success"
    assert run_log["rows_fetched"] == 3


def test_run_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        rankings.run(db_path, session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'rankings'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]
