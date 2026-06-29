#!/usr/bin/env python3
"""Live-score refresh for the Wimbledon bot.

Meant to run every few minutes during match hours (scheduled via Windows
Task Scheduler), separately from daily_update.py — live scores change far
more often than rankings/elo/draw, so they need their own faster cadence.
Cheap to run repeatedly: only hits tennisexplorer.com/matches/ once and
writes nothing if a match's score hasn't changed.
"""
import logging
import sys

import db
import predictions
from scrapers import live

DB_PATH = "data/wimbledon.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename="data/live_update.log",
)
logger = logging.getLogger(__name__)


def main():
    db.init_db(DB_PATH)
    try:
        rows = live.run_from_tennisexplorer(DB_PATH)
        logger.info("OK live: %d rows", rows)
        print(f"[OK] live: {rows} filas")
    except Exception as exc:
        logger.error("FAILED live: %s", exc)
        print(f"[FALLO] live: {exc}")
        return

    try:
        won = predictions.backfill_winners_from_live(DB_PATH)
        logged = predictions.log_pending_predictions(DB_PATH)
        logger.info("OK predictions: %d winners backfilled, %d new predictions logged", won, logged)
        print(f"[OK] predictions: {won} ganadores, {logged} predicciones nuevas")
    except Exception as exc:
        logger.error("FAILED predictions: %s", exc)
        print(f"[FALLO] predictions: {exc}")


if __name__ == "__main__":
    sys.exit(main() or 0)
