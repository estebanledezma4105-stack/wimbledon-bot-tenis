import json
import os
from unittest.mock import MagicMock

import db
from scrapers import draw

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "draw.json")
TENNISEXPLORER_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "draw_tennisexplorer.html")


def test_parse_draw_json_normalizes_fields():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parsed = draw.parse_draw_json(payload)
    assert parsed == [
        {"round": "R1", "player1": "Carlos Alcaraz", "player2": "Mark Newcomer",
         "winner": "Carlos Alcaraz", "completed_at": "2026-06-29T15:00:00Z"},
        {"round": "R1", "player1": "Novak Djokovic", "player2": "Jane Qualifier",
         "winner": None, "completed_at": None},
    ]


def test_parse_draw_json_skips_malformed_entries():
    payload = [{"round": "R1"}]
    assert draw.parse_draw_json(payload) == []


def test_store_match_inserts_then_updates(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    entry = {"round": "R1", "player1": "Carlos Alcaraz", "player2": "Mark Newcomer",
              "winner": None, "completed_at": None}
    draw._store_match(db_path, entry)

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM draw_matches").fetchone()
    assert row["winner_id"] is None

    entry["winner"] = "Carlos Alcaraz"
    entry["completed_at"] = "2026-06-29T15:00:00Z"
    draw._store_match(db_path, entry)

    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM draw_matches").fetchall()
    assert len(rows) == 1
    assert rows[0]["completed_at"] == "2026-06-29T15:00:00Z"


def test_parse_draw_html_extracts_matches_and_strips_seed_numbers():
    with open(TENNISEXPLORER_FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = draw.parse_draw_html(html)
    assert parsed == [
        {"round": "1R", "player1": "Rublev", "player2": "Safiullin",
         "winner": None, "completed_at": None},
        {"round": "1R", "player1": "Trungelliti", "player2": "Damm",
         "winner": None, "completed_at": None},
    ]


def test_parse_draw_html_returns_empty_list_without_round_column():
    assert draw.parse_draw_html("<table class='result'><tr><td>x</td></tr></table>") == []


def test_resolve_by_surname_matches_unique_surname(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Andrey Rublev")
    assert draw._resolve_by_surname(db_path, "Rublev") == "Andrey Rublev"


def test_resolve_by_surname_returns_none_on_ambiguous_surname(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Alexander Zverev")
    db.upsert_player(db_path, name="Mischa Zverev")
    assert draw._resolve_by_surname(db_path, "Zverev") is None


def test_run_from_tennisexplorer_resolves_known_surname_to_full_name(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Andrey Rublev")

    with open(TENNISEXPLORER_FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = draw.run_from_tennisexplorer(db_path, session=mock_session)
    assert rows == 2

    with db.get_connection(db_path) as conn:
        match = conn.execute(
            """SELECT p1.name as p1 FROM draw_matches dm
               JOIN players p1 ON p1.id = dm.player1_id
               WHERE dm.round = '1R' AND p1.name LIKE '%Rublev%'"""
        ).fetchone()
    assert match["p1"] == "Andrey Rublev"


def test_run_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        draw.run(db_path, session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'draw'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]
