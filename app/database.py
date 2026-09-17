from pathlib import Path



from sqlalchemy import create_engine, inspect, text

from sqlalchemy.orm import DeclarativeBase, sessionmaker



from app.config import settings





def _normalize_database_url(url: str) -> str:

    if url.startswith("postgres://"):

        return url.replace("postgres://", "postgresql://", 1)

    return url





def _with_ssl_if_needed(url: str) -> str:

    if url.startswith("sqlite"):

        return url

    if "sslmode=" not in url and ("neon.tech" in url or "supabase.co" in url):

        sep = "&" if "?" in url else "?"

        return f"{url}{sep}sslmode=require"

    return url





_db_url = _with_ssl_if_needed(_normalize_database_url(settings.database_url))

if _db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {"connect_timeout": 10}

engine = create_engine(
    _db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)





class Base(DeclarativeBase):

    pass





def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()





def _sqlite_add_column_if_missing(table: str, column: str, ddl: str):

    inspector = inspect(engine)

    if table not in inspector.get_table_names():

        return

    existing = {col["name"] for col in inspector.get_columns(table)}

    if column not in existing:

        with engine.begin() as conn:

            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))





def _ensure_postgres_indexes():

    if _db_url.startswith("sqlite"):

        return

    indexes = [

        "CREATE INDEX IF NOT EXISTS ix_attendance_emp_date ON attendance_records (employee_id, work_date)",

        "CREATE INDEX IF NOT EXISTS ix_attendance_work_date ON attendance_records (work_date)",

        "CREATE INDEX IF NOT EXISTS ix_employees_status ON employees (status)",

        "CREATE INDEX IF NOT EXISTS ix_employees_department ON employees (department_id)",

        "CREATE INDEX IF NOT EXISTS ix_chat_participant_user ON chat_participants (user_id)",

        "CREATE INDEX IF NOT EXISTS ix_chat_participant_conv ON chat_participants (conversation_id)",

        "CREATE INDEX IF NOT EXISTS ix_chat_msg_conv_created ON chat_messages (conversation_id, created_at)",

        "CREATE INDEX IF NOT EXISTS ix_task_assignee_status ON tasks (assigned_employee_id, status)",

    ]

    with engine.begin() as conn:

        for ddl in indexes:

            conn.execute(text(ddl))





def migrate_schema():

    if _db_url.startswith("sqlite"):

        _sqlite_add_column_if_missing("users", "employee_id", "employee_id INTEGER")

        _sqlite_add_column_if_missing("employees", "employee_code", "employee_code VARCHAR(50)")

        _sqlite_add_column_if_missing("employees", "phone", "phone VARCHAR(30)")

        _sqlite_add_column_if_missing("employees", "job_title", "job_title VARCHAR(100)")

        _sqlite_add_column_if_missing("employees", "department_id", "department_id INTEGER")

        _sqlite_add_column_if_missing("employees", "joining_date", "joining_date DATE")

        _sqlite_add_column_if_missing("employees", "profile_photo_url", "profile_photo_url VARCHAR(500)")

    else:

        _ensure_postgres_indexes()





def init_db():

    from app import models  # noqa: F401



    if _db_url.startswith("sqlite"):

        db_path = settings.database_url.replace("sqlite:///", "")

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    migrate_schema()


