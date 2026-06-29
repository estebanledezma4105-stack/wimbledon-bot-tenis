import json
import os
from unittest.mock import MagicMock

import db
from scrapers import draw

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "draw.json")


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
