import os
from unittest.mock import MagicMock

import db
from scrapers import h2h

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "h2h_pair.html")


def test_parse_h2h_html_extracts_wins():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = h2h.parse_h2h_html(html)
    assert parsed == {
        "player1": "Carlos Alcaraz",
        "player2": "Novak Djokovic",
        "player1_wins": 5,
        "player2_wins": 3,
    }


def test_parse_h2h_html_returns_none_on_missing_data():
    assert h2h.parse_h2h_html("<html></html>") is None


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


def test_run_for_pair_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        h2h.run_for_pair(db_path, "alcaraz", "djokovic", session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'h2h'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]
