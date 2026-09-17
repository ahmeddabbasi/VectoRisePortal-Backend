from app.database import init_db
from app.services.sync import SyncService, seed_database
from app.database import SessionLocal


def main():
    init_db()
    db = SessionLocal()
    try:
        seed_database(db)
        run = SyncService(db).run()
        print(run.status, run.message)
    finally:
        db.close()


if __name__ == "__main__":
    main()
