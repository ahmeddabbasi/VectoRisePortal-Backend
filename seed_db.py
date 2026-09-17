"""Bootstrap database with departments, admin user, and optional demo data.

Usage:
  cd backend && python seed_db.py
"""

from app.database import SessionLocal, init_db
from app.services.sync import seed_database


def main():
    init_db()
    db = SessionLocal()
    try:
        seed_database(db)
        print("Database seeded successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
