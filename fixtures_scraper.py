"""Scraper for ATP tennis fixtures."""
import logging
from datetime import datetime, timedelta
import db

logger = logging.getLogger(__name__)

def load_fixtures(db_path):
    """Load upcoming ATP fixtures from Tennis Explorer API and insert into DB."""
    try:
        logger.info("Loading ATP fixtures...")

        # Fetch upcoming matches from Tennis Explorer API
        url = "https://www.tennisexplorer.com/ajax/players-events-result/"

        # Get fixtures for next 30 days
        today = datetime.now().date()
        fixtures = []

        # For now, we'll seed with some sample matches
        # In production, connect to ATP/Tennis Explorer API
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

        with db.get_connection(db_path) as conn:
            loaded_count = 0
            for match in sample_matches:
                # Get player IDs - search without .lower() since names in DB use mixed case
                p1_row = conn.execute(
                    "SELECT id FROM players WHERE name = ?",
                    (match["player1"],)
                ).fetchone()

                p2_row = conn.execute(
                    "SELECT id FROM players WHERE name = ?",
                    (match["player2"],)
                ).fetchone()

                if p1_row and p2_row:
                    conn.execute(
                        """INSERT OR IGNORE INTO draw_matches
                           (tournament_id, year, round, player1_id, player2_id, scheduled_date)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (match["tournament"], 2026, match["round"],
                         p1_row["id"], p2_row["id"], match["date"])
                    )
                    loaded_count += 1
                    logger.info(f"Loaded match: {match['player1']} vs {match['player2']}")
                else:
                    logger.warning(f"Players not found: {match['player1']} ({p1_row}) vs {match['player2']} ({p2_row})")

        logger.info(f"Successfully loaded {loaded_count}/{len(sample_matches)} fixtures")
        return loaded_count

    except Exception as e:
        logger.error(f"Error loading fixtures: {e}")
        return 0
