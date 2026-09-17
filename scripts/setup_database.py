"""
Initialize production PostgreSQL database (create tables + optional seed).

Usage:
  cd backend
  set DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
  set SEED_DATABASE=true
  set ADMIN_EMAIL=admin@yourcompany.com
  set ADMIN_PASSWORD=your-strong-password
  python scripts/setup_database.py
"""

import os
import sys

# Allow running from backend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine, init_db
from app.services.sync import seed_database
from app.database import SessionLocal


def main():
    url = settings.database_url
    if url.startswith("sqlite"):
        print("WARNING: DATABASE_URL points to SQLite. For production use PostgreSQL (Neon/Supabase).")
    else:
        print(f"Connecting to: {url.split('@')[-1] if '@' in url else 'database'}...")

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Connection: OK")
    except Exception as exc:
        print(f"Connection FAILED: {exc}")
        sys.exit(1)

    print("Creating tables...")
    init_db()

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tables created: {len(tables)} ({', '.join(sorted(tables)[:5])}...)")

    if settings.should_seed:
        print("Seeding admin user and defaults...")
        db = SessionLocal()
        try:
            seed_database(db)
            print(f"Admin user: {settings.admin_email}")
            print("Seed: OK")
        finally:
            db.close()
    else:
        print("Seed skipped (SEED_DATABASE=false or ENVIRONMENT=production)")

    print("\nDatabase setup complete.")


if __name__ == "__main__":
    main()
