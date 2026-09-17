# VectoRise Portal — Backend

FastAPI API for the VectoRise Workforce Portal (HRM, sales sync, chat).

## Stack

- FastAPI + SQLAlchemy + APScheduler
- PostgreSQL (production) / SQLite (local dev)

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env   # edit as needed
set PYTHONPATH=.
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: `http://127.0.0.1:8000/health`

## Production (Render)

See `render.yaml` and set environment variables in the Render dashboard.

Required: `DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS`, `ENVIRONMENT=production`

First deploy: `SEED_DATABASE=true` once, then `false`.

## Frontend

Pair with [VectoRisePortal-Frontend](https://github.com/ahmeddabbasi/VectoRisePortal-Frontend).
