import db
import predictions


def _make_match(db_path, p1_name, p2_name, round_="1R"):
    p1 = db.upsert_player(db_path, name=p1_name)
    p2 = db.upsert_player(db_path, name=p2_name)
    with db.get_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id)
               VALUES ('wimbledon', 2026, ?, ?, ?)""",
            (round_, p1, p2),
        )
        return cursor.lastrowid, p1, p2


def test_count_set_wins_handles_tiebreak_notation():
    assert predictions._count_set_wins("6-3, 7-6(7), 4-6") == (2, 1)


def test_count_set_wins_returns_zero_zero_on_empty_string():
    assert predictions._count_set_wins("") == (0, 0)


def test_backfill_winners_from_live_sets_winner_id(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")
    with db.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO live_scores (match_id, sets, status, updated_at) VALUES (?, ?, 'finished', '')",
            (match_id, "6-3, 6-3"),
        )

    updated = predictions.backfill_winners_from_live(db_path)
    assert updated == 1

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT winner_id FROM draw_matches WHERE id = ?", (match_id,)).fetchone()
    assert row["winner_id"] == p1


def test_backfill_winners_from_live_skips_unfinished_or_already_decided(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")
    with db.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO live_scores (match_id, sets, status, updated_at) VALUES (?, ?, 'in_progress', '')",
            (match_id, "6-3"),
        )

    updated = predictions.backfill_winners_from_live(db_path)
    assert updated == 0


def test_log_pending_predictions_locks_in_prediction_for_undecided_match(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")
    db.upsert_player(db_path, name="Carlos Alcaraz", elo=2100)
    db.upsert_player(db_path, name="Mark Newcomer", elo=1500)

    logged = predictions.log_pending_predictions(db_path)
    assert logged == 1

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM predictions WHERE match_id = ?", (match_id,)).fetchone()
    assert row["favorite_id"] == p1
    assert row["probability"] > 0.5


def test_log_pending_predictions_does_not_relog_or_touch_decided_matches(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")
    db.set_match_winner(db_path, match_id, p2)  # upset: underdog won

    logged = predictions.log_pending_predictions(db_path)
    assert logged == 0

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM predictions WHERE match_id = ?", (match_id,)).fetchone()
    assert row is None


def test_compute_accuracy_reflects_locked_in_prediction_not_recomputed_one(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")

    # Lock in a prediction favoring p1, then the underdog (p2) actually wins —
    # accuracy must reflect that miss, not silently "correct" itself using
    # post-match data.
    db.record_prediction(db_path, match_id, favorite_id=p1, probability=0.9)
    db.set_match_winner(db_path, match_id, p2)

    correct, total, details = predictions.compute_accuracy(db_path)
    assert (correct, total) == (0, 1)
    assert details[0]["correct"] is False
    assert details[0]["predicted"] == "Carlos Alcaraz"
    assert details[0]["winner"] == "Mark Newcomer"


def test_record_prediction_never_overwrites_existing_one(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    match_id, p1, p2 = _make_match(db_path, "Carlos Alcaraz", "Mark Newcomer")

    db.record_prediction(db_path, match_id, favorite_id=p1, probability=0.9)
    db.record_prediction(db_path, match_id, favorite_id=p2, probability=0.6)

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM predictions WHERE match_id = ?", (match_id,)).fetchone()
    assert row["favorite_id"] == p1
    assert row["probability"] == 0.9
