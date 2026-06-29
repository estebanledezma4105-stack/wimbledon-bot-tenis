import os
from unittest.mock import MagicMock

import db
from scrapers import h2h

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "h2h_mutual.html")


def test_parse_h2h_html_extracts_winner_loser_per_match():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = h2h.parse_h2h_html(html)
    assert parsed == [
        {"winner": "Sinner J.", "loser": "Alcaraz C."},
        {"winner": "Alcaraz C.", "loser": "Sinner J."},
    ]


def test_parse_h2h_html_returns_empty_list_without_year_header():
    assert h2h.parse_h2h_html("<html><body>nothing here</body></html>") == []


def test_label_matches_canonical_ignores_single_letter_initial():
    assert h2h._label_matches_canonical("Sinner J.", "Jannik Sinner") is True
    assert h2h._label_matches_canonical("Alcaraz C.", "Jannik Sinner") is False


def test_search_player_slug_returns_url_for_unambiguous_match():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "links": [{"type": "p", "url": "alcaraz-5ab70", "name": "Alcaraz, Carlos (ESP)"}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    slug = h2h.search_player_slug(mock_session, "Carlos Alcaraz")
    assert slug == "alcaraz-5ab70"


def test_search_player_slug_returns_none_when_ambiguous():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "links": [
            {"type": "p", "url": "sinner-8b8e8", "name": "Sinner, Jannik (ITA)"},
            {"type": "p", "url": "sinner", "name": "Sinner, Martin (GER)"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    assert h2h.search_player_slug(mock_session, "Sinner") is None


def test_store_h2h_normalizes_player_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    id_b = db.upsert_player(db_path, name="Novak Djokovic")
    id_a = db.upsert_player(db_path, name="Carlos Alcaraz")

    h2h._store_h2h(db_path, "Carlos Alcaraz", "Novak Djokovic", wins1=5, wins2=3)

    lower_id, higher_id = sorted([id_a, id_b])
    expected_a_wins = 5 if id_a == lower_id else 3
    expected_b_wins = 3 if id_a == lower_id else 5

    with db.get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM h2h WHERE player_a_id = ? AND player_b_id = ?",
            (lower_id, higher_id),
        ).fetchone()
    assert row is not None
    assert row["a_wins"] == expected_a_wins
    assert row["b_wins"] == expected_b_wins


def test_run_for_pair_resolves_slugs_fetches_and_stores_totals(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        mutual_html = f.read()

    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json.side_effect = [
        {"links": [{"type": "p", "url": "sinner-8b8e8", "name": "Sinner, Jannik (ITA)"}]},
        {"links": [{"type": "p", "url": "alcaraz-5ab70", "name": "Alcaraz, Carlos (ESP)"}]},
    ]
    mutual_response = MagicMock()
    mutual_response.text = mutual_html
    mutual_response.raise_for_status = MagicMock()

    mock_session = MagicMock()
    mock_session.get.side_effect = [search_response, search_response, mutual_response]

    rows = h2h.run_for_pair(db_path, "Jannik Sinner", "Carlos Alcaraz", session=mock_session)
    assert rows == 2

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM h2h").fetchone()
    assert {row["a_wins"], row["b_wins"]} == {1, 1}


def test_run_for_pair_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        h2h.run_for_pair(db_path, "Jannik Sinner", "Carlos Alcaraz", session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'h2h'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]


def test_run_for_pair_logs_failure_when_slug_unresolvable(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    empty_response = MagicMock()
    empty_response.raise_for_status = MagicMock()
    empty_response.json.return_value = {"links": []}
    mock_session = MagicMock()
    mock_session.get.return_value = empty_response

    rows = h2h.run_for_pair(db_path, "Totally Unknown", "Carlos Alcaraz", session=mock_session)
    assert rows == 0

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'h2h'").fetchone()
    assert run_log["status"] == "failure"
