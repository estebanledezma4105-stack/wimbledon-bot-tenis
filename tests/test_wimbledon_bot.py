import db
import wimbledon_bot


def test_update_elo_from_results_persists_winner_and_loser_elo(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(wimbledon_bot, "DB_PATH", db_path)
    db.init_db(db_path)

    winner_id = db.upsert_player(db_path, name="Carlos Alcaraz", elo=2100)
    loser_id = db.upsert_player(db_path, name="Mark Newcomer", elo=1500)

    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO draw_matches
               (tournament_id, year, round, player1_id, player2_id, winner_id, completed_at)
               VALUES ('wimbledon', 2026, 'R1', ?, ?, ?, '2026-06-29T15:00:00Z')""",
            (winner_id, loser_id, winner_id),
        )

    wimbledon_bot.update_elo_from_results()

    winner_row = db.get_player_by_name(db_path, "Carlos Alcaraz")
    loser_row = db.get_player_by_name(db_path, "Mark Newcomer")
    assert winner_row["elo"] > 2100
    assert loser_row["elo"] < 1500


def test_update_elo_from_results_no_completed_matches_does_not_raise(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(wimbledon_bot, "DB_PATH", db_path)
    db.init_db(db_path)

    wimbledon_bot.update_elo_from_results()
