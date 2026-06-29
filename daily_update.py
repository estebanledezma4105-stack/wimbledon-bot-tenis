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

import db
from scrapers import draw, elo_uts, rankings

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


def main():
    db.init_db(DB_PATH)
    print(f"=== Actualización diaria — {datetime.now(timezone.utc).isoformat()} ===")
    run_step("rankings", lambda: rankings.run(DB_PATH))
    run_step("elo_overall", lambda: elo_uts.run(DB_PATH, rank_type="ELO_RANK", row_count=500))
    run_step("elo_grass", lambda: elo_uts.run(DB_PATH, rank_type="GRASS_ELO_RANK", row_count=500))
    run_step("form", lambda: elo_uts.run_form(DB_PATH, row_count=500))
    run_step("draw", lambda: draw.run_from_tennisexplorer(DB_PATH))
    print("=== Actualización completa ===")


if __name__ == "__main__":
    sys.exit(main() or 0)
