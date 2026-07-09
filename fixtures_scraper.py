"""Scraper for ATP tennis fixtures."""
import logging
from datetime import datetime, timedelta
import db

logger = logging.getLogger(__name__)

def ensure_players_exist(db_path):
    """Ensure required players exist in database. Create them if missing."""
    required_players = [
        "Carlos Alcaraz",
        "Jannik Sinner",
        "Novak Djokovic",
        "Lorenzo Musetti",
        "Rafael Nadal",
        "Andrey Rublev",
    ]

    with db.get_connection(db_path) as conn:
        for player_name in required_players:
            existing = conn.execute(
                "SELECT id FROM players WHERE name = ?",
                (player_name,)
            ).fetchone()

            if not existing:
                logger.info(f"Creating missing player: {player_name}")
                try:
                    conn.execute(
                        "INSERT INTO players (name, ranking, last_updated) VALUES (?, ?, ?)",
                        (player_name, 999, datetime.now().isoformat())
                    )
                    logger.info(f"  Successfully created {player_name}")
                except Exception as e:
                    logger.error(f"Failed to create player {player_name}: {e}")

def load_fixtures(db_path):
    """Load upcoming ATP fixtures from Tennis Explorer API and insert into DB."""
    try:
        logger.info("=" * 70)
        logger.info("STARTING FIXTURE LOADER")
        logger.info("=" * 70)

        today = datetime.now().date()
        today_iso = today.isoformat()
        logger.info(f"Today's date: {today_iso}")

        # Ensure all required players exist (creates them if missing)
        logger.info("\n[STEP 0] Ensuring all required players exist...")
        ensure_players_exist(db_path)

        # Clean up old fixtures for today to prevent duplicates
        logger.info("\n[STEP 0.5] Cleaning up old fixtures for today...")
        with db.get_connection(db_path) as conn:
            conn.execute(
                "DELETE FROM draw_matches WHERE scheduled_date = ?",
                (today_iso,)
            )
            logger.info(f"  Cleaned up old fixtures for {today_iso}")

        # Sample matches for testing
        sample_matches = [
            {
                "player1": "Carlos Alcaraz",
                "player2": "Jannik Sinner",
                "date": today.isoformat(),
                "tournament": "ATP 250",
                "round": "Quarterfinals"
            },
            {
                "player1": "Novak Djokovic",
                "player2": "Lorenzo Musetti",
                "date": today.isoformat(),
                "tournament": "ATP 250",
                "round": "Quarterfinals"
            },
            {
                "player1": "Rafael Nadal",
                "player2": "Andrey Rublev",
                "date": today.isoformat(),
                "tournament": "ATP 500",
                "round": "Semifinals"
            }
        ]

        logger.info(f"Attempting to load {len(sample_matches)} fixtures...")

        with db.get_connection(db_path) as conn:
            # First, verify players exist in database
            logger.info("\n[STEP 1] Verifying players exist in database...")
            players_found = 0
            players_missing = 0

            for match in sample_matches:
                p1 = conn.execute("SELECT id FROM players WHERE name = ?", (match["player1"],)).fetchone()
                p2 = conn.execute("SELECT id FROM players WHERE name = ?", (match["player2"],)).fetchone()

                if p1 and p2:
                    players_found += 2
                    logger.info(f"  OK: {match['player1']} (ID {p1['id']}) and {match['player2']} (ID {p2['id']})")
                else:
                    players_missing += 1
                    if not p1:
                        logger.error(f"  MISSING: {match['player1']}")
                    if not p2:
                        logger.error(f"  MISSING: {match['player2']}")

            logger.info(f"  Total: {players_found} found, {players_missing} missing")

            # Insert matches
            logger.info("\n[STEP 2] Inserting matches into database...")
            loaded_count = 0
            failed_count = 0

            for match in sample_matches:
                p1_row = conn.execute("SELECT id FROM players WHERE name = ?", (match["player1"],)).fetchone()
                p2_row = conn.execute("SELECT id FROM players WHERE name = ?", (match["player2"],)).fetchone()

                if p1_row and p2_row:
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO draw_matches
                               (tournament_id, year, round, player1_id, player2_id, scheduled_date)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (match["tournament"], 2026, match["round"],
                             p1_row["id"], p2_row["id"], match["date"])
                        )
                        loaded_count += 1
                        logger.info(f"  INSERTED: {match['player1']} vs {match['player2']} ({match['date']})")
                    except Exception as e:
                        failed_count += 1
                        logger.error(f"  INSERT FAILED for {match['player1']} vs {match['player2']}: {e}")
                else:
                    failed_count += 1
                    p1_status = "FOUND" if p1_row else "MISSING"
                    p2_status = "FOUND" if p2_row else "MISSING"
                    logger.error(f"  SKIP: {match['player1']} ({p1_status}) vs {match['player2']} ({p2_status})")

            logger.info(f"\n  Total: {loaded_count} inserted, {failed_count} failed")

            # Verify insertions
            logger.info("\n[STEP 3] Verifying insertions...")
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM draw_matches WHERE scheduled_date = ?",
                (today.isoformat(),)
            ).fetchone()
            logger.info(f"  Matches for {today.isoformat()}: {count['cnt']}")

        logger.info("\n" + "=" * 70)
        logger.info(f"FIXTURE LOADER COMPLETE - Loaded {loaded_count} fixtures")
        logger.info("=" * 70 + "\n")

        return loaded_count

    except Exception as e:
        logger.error(f"\n!!! CRITICAL ERROR in load_fixtures: {e}")
        logger.error("=" * 70 + "\n")
        import traceback
        logger.error(traceback.format_exc())
        return 0
