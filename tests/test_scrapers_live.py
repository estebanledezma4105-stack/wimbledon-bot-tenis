import json
import os
from unittest.mock import MagicMock

import db
from scrapers import live

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "live.json")


def test_parse_live_json_normalizes_fields():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parsed = live.parse_live_json(payload)
    assert parsed == [
        {"external_match_id": "wim-2026-r1-001", "sets": "6-4, 3-2", "status": "in_progress"},
        {"external_match_id": "wim-2026-r1-002", "sets": "6-2, 6-3", "status": "finished"},
    ]


def test_parse_live_json_skips_entries_without_match_id():
    assert live.parse_live_json([{"sets": "6-4"}]) == []


def test_store_live_scores_updates_matched_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    p1 = db.upsert_player(db_path, name="Carlos Alcaraz")
    p2 = db.upsert_player(db_path, name="Mark Newcomer")
    with db.get_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id)
               VALUES ('wimbledon', 2026, 'R1', ?, ?)""",
            (p1, p2),
        )
        local_match_id = cursor.lastrowid

    parsed = [{"external_match_id": "wim-2026-r1-001", "sets": "6-4, 3-2", "status": "in_progress"}]
    external_id_map = {"wim-2026-r1-001": local_match_id}

    updated = live.store_live_scores(db_path, parsed, external_id_map)
    assert updated == 1

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM live_scores WHERE match_id = ?", (local_match_id,)).fetchone()
    assert row["status"] == "in_progress"


def test_store_live_scores_skips_unmatched_entries(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    parsed = [{"external_match_id": "unknown-match", "sets": "6-4", "status": "in_progress"}]
    updated = live.store_live_scores(db_path, parsed, external_id_map={})
    assert updated == 0


def test_run_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        live.run(db_path, external_id_map={}, session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'live'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]
