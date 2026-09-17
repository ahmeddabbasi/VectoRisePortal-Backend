import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_daily_jobs():
    from app.services.attendance_jobs import AttendanceJobService

    db = SessionLocal()
    try:
        result = AttendanceJobService(db).run_daily_jobs()
        db.commit()
        logger.info("Daily jobs completed: %s", result)
    except Exception:
        db.rollback()
        logger.exception("Daily jobs failed")
    finally:
        db.close()


def _run_sync():
    from app.services.sync import SyncService

    creds = Path(settings.google_service_account_path)
    if not settings.google_spreadsheet_id or not creds.exists():
        logger.debug("Skipping scheduled sync — Google credentials not configured")
        return
    db = SessionLocal()
    try:
        run = SyncService(db).run()
        logger.info("Scheduled sync: %s — %s", run.status, run.message)
    except Exception:
        logger.exception("Scheduled sync failed")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_daily_jobs,
        CronTrigger(hour=settings.daily_jobs_hour, minute=settings.daily_jobs_minute),
        id="daily_jobs",
        replace_existing=True,
    )
    if settings.enable_sync_scheduler and settings.sync_interval_minutes > 0:
        _scheduler.add_job(
            _run_sync,
            IntervalTrigger(minutes=settings.sync_interval_minutes),
            id="google_sync",
            replace_existing=True,
        )
    _scheduler.start()
    logger.info(
        "Scheduler started (daily jobs at %02d:%02d UTC, sync every %s min)",
        settings.daily_jobs_hour,
        settings.daily_jobs_minute,
        settings.sync_interval_minutes if settings.enable_sync_scheduler else "disabled",
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
