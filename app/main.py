import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.chat_routes import router as chat_router
from app.api.employee_routes import router as employee_router
from app.api.media_routes import router as media_router
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
    (settings.upload_path / "tasks").mkdir(parents=True, exist_ok=True)

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
    allow_origin_regex=r"https://vecto-rise-portal-frontend[a-z0-9-]*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    if request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/media"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(employee_router)
app.include_router(hrm_router)
app.include_router(sales_router)
app.include_router(chat_router)
app.include_router(notification_router)
app.include_router(media_router)


def _record_error(request: Request, status_code: int, message: str) -> None:
    from app.models.error_report import ErrorReport

    text = " ".join(str(message or "Server error").split())[:500]
    db = SessionLocal()
    try:
        db.add(
            ErrorReport(
                method=request.method[:10],
                path=request.url.path[:300],
                status_code=status_code,
                message=text,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        _record_error(request, exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    _record_error(request, 500, exc.__class__.__name__)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong"})


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}
