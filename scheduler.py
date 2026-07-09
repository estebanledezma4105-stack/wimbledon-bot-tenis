"""Background scheduler for automatic data updates every 10 minutes."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import db

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
    """Initialize background scheduler for 10-minute updates."""
    scheduler = BackgroundScheduler()

    # Add job: run every 10 minutes with db_path argument
    scheduler.add_job(
        update_all_data,
        args=(db_path,),
        trigger=IntervalTrigger(minutes=10),
        id='update_all_data',
        name='Update ATP rankings, fixtures, results, and stats',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started - updates every 10 minutes")
    return scheduler
