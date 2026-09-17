import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.chat_routes import router as chat_router
from app.api.employee_routes import router as employee_router
from app.api.notification_routes import router as notification_router
from app.api.hrm_routes import router as hrm_router
from app.api.sales_routes import router as sales_router
from app.bootstrap import ensure_google_credentials
from app.config import settings
from app.database import SessionLocal, init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.sync import seed_database

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_google_credentials()
    init_db()
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    (settings.upload_path / "profile").mkdir(parents=True, exist_ok=True)

    if settings.should_seed:
        db = SessionLocal()
        try:
            seed_database(db)
            logger.info("Database seeded (development mode)")
        finally:
            db.close()
    else:
        logger.info("Database seed skipped (production mode)")

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

settings.upload_path.mkdir(parents=True, exist_ok=True)
(settings.upload_path / "profile").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(employee_router)
app.include_router(hrm_router)
app.include_router(sales_router)
app.include_router(chat_router)
app.include_router(notification_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }
