import logging
import threading

from app.database import SessionLocal
from app.services.sync import SyncService, cleanup_stale_sync_runs

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_running = False


def is_sync_running() -> bool:
    return _running


def start_background_sync() -> bool:
    global _running
    with _lock:
        if _running:
            return False
        _running = True

    def job():
        global _running
        db = SessionLocal()
        try:
            cleanup_stale_sync_runs(db)
            run = SyncService(db).run()
            logger.info("Background sync finished: %s — %s", run.status, run.message)
        except Exception:
            logger.exception("Background sync failed")
        finally:
            _running = False
            db.close()

    threading.Thread(target=job, daemon=True).start()
    return True
