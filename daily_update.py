#!/usr/bin/env python3
"""Daily data refresh for the Wimbledon bot.

Run once per morning (scheduled via Windows Task Scheduler) to:
1. Refresh ATP rankings (tennisexplorer.com)
2. Refresh real Elo ratings: overall, then grass-specific (ultimatetennisstatistics.com)
3. Refresh recent-form deltas (ultimatetennisstatistics.com)
4. Refresh the draw with today's/upcoming matches and their real scheduled_date
   (tennisexplorer.com) — this is what makes /partidos automatically show only
   the current day's round without any manual intervention.

The bot itself reads from the database fresh on every Telegram command, so
it does NOT need to be restarted after this runs.
"""
import logging
import sys
from datetime import datetime, timezone

import httpx

import db
from scrapers import draw, elo_uts, rankings
from scrapers.ranking_form import extract_ranking_and_form

DB_PATH = "data/wimbledon.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename="data/daily_update.log",
)
logger = logging.getLogger(__name__)


def run_step(name, fn):
    try:
        rows = fn()
        logger.info("OK %s: %d rows", name, rows)
        print(f"[OK] {name}: {rows} filas")
    except Exception as exc:
        logger.error("FAILED %s: %s", name, exc)
        print(f"[FALLO] {name}: {exc}")


def update_ranking_and_form():
    """Scrape ATP ranking and recent tournament form for all players in the draw."""
    data = db.load_all_data(DB_PATH)

    # Get all unique players in the draw
    player_names = set()
    for match in data["draw"]["matches"]:
        if match["player1"]:
            player_names.add(match["player1"])
        if match["player2"]:
            player_names.add(match["player2"])

    print(f"Scraping ranking + form for {len(player_names)} players...")
    logger.info("Scraping ranking + form for %d players...", len(player_names))

    success = 0
    failed = 0

    with httpx.Client(timeout=10) as session:
        for player_name in sorted(player_names):
            result = extract_ranking_and_form(player_name, session)

            if result is None:
                failed += 1
                logger.debug("SKIP: %s", player_name)
                continue

            player = db.get_player_by_name(DB_PATH, player_name)
            if player is None:
                logger.error("ERROR: Player %s not in DB (shouldn't happen)", player_name)
                continue

            # Upsert ranking
            db.upsert_ranking(DB_PATH, player["id"],
                            ranking_position=result["ranking_position"],
                            ranking_points=result["ranking_points"])

            # Upsert recent form
            db.upsert_recent_form(DB_PATH, player["id"],
                                 tournaments_played=result["tournaments_played"],
                                 wins=result["wins"],
                                 losses=result["losses"],
                                 titles=result["titles"],
                                 finals_reached=result["finals_reached"],
                                 last_tournament_date=result["last_tournament_date"])

            success += 1
            if success % 10 == 0:
                print(f"  {success} scraped...")

    print(f"Ranking + form scrape complete: {success} success, {failed} failed")
    logger.info("Ranking + form scrape complete: %d success, %d failed", success, failed)
    return success


def main():
    db.init_db(DB_PATH)
    print(f"=== Actualización diaria — {datetime.now(timezone.utc).isoformat()} ===")
    run_step("rankings", lambda: rankings.run(DB_PATH))
    run_step("elo_overall", lambda: elo_uts.run(DB_PATH, rank_type="ELO_RANK", row_count=500))
    run_step("elo_grass", lambda: elo_uts.run(DB_PATH, rank_type="GRASS_ELO_RANK", row_count=500))
    run_step("form", lambda: elo_uts.run_form(DB_PATH, row_count=500))
    run_step("draw", lambda: draw.run_from_tennisexplorer(DB_PATH))
    run_step("ranking_form", update_ranking_and_form)
    print("=== Actualización completa ===")


if __name__ == "__main__":
    sys.exit(main() or 0)
