"""Background scheduler for automatic data updates every 10 minutes."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import db
from fixtures_scraper import load_fixtures

logger = logging.getLogger(__name__)

def update_all_data(db_path):
    """Update rankings, fixtures, results, and stats every 10 minutes."""
    try:
        logger.info("Starting scheduled data update...")

        # Load and sync all ATP data
        db.load_all_data(db_path)

        logger.info("Data update completed successfully")
    except Exception as e:
        logger.error(f"Error during scheduled update: {e}")

def setup_scheduler(db_path):
    """Initialize background scheduler for 10-minute updates and daily fixture loads."""
    scheduler = BackgroundScheduler()

    # Job 1: Update all data every 10 minutes
    scheduler.add_job(
        update_all_data,
        args=(db_path,),
        trigger=IntervalTrigger(minutes=10),
        id='update_all_data',
        name='Update ATP rankings, fixtures, results, and stats',
        replace_existing=True
    )

    # Job 2: Load fixtures daily at 6 AM
    scheduler.add_job(
        load_fixtures,
        args=(db_path,),
        trigger=CronTrigger(hour=6, minute=0),
        id='load_fixtures',
        name='Load ATP fixtures daily',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started - updates every 10 minutes + daily fixtures at 6 AM")
    return scheduler
