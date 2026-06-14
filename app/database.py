"""Database configuration and session management."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import get_settings

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Timezone-aware UTC 'now' for model defaults.

    SQLite's ``CURRENT_TIMESTAMP`` (what ``func.now()`` compiles to) stores naive UTC;
    SQLAlchemy reads it back without tzinfo, so downstream serializers can't distinguish
    it from a local wall-clock value. Binding Python-side aware datetimes via ``default``
    keeps the tzinfo on the outbound row and lets the frontend convert UTC -> local.
    """
    return datetime.now(timezone.utc)

settings = get_settings()

# Create SQLite engine for users database
SQLALCHEMY_DATABASE_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},  # SQLite specific
    echo=False,  # Set to True for SQL debugging
)

# Create separate engine for logs database
LOGS_DB_PATH = Path(settings.log_dir) / "scanscribe_logs.db"
LOGS_DATABASE_URL = f"sqlite:///{LOGS_DB_PATH}"

logs_engine = create_engine(
    LOGS_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)

# Events pipeline DB (Worker/Master per monitor)
EVENTS_DB_PATH = settings.db_path.parent / "scanscribe_events.db"
EVENTS_DATABASE_URL = f"sqlite:///{EVENTS_DB_PATH}"

events_engine = create_engine(
    EVENTS_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)

@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable WAL + a busy timeout on every SQLite connection.

    Multiple background workers (queue, watcher, auto-summary, events cleanup)
    plus request handlers write to three SQLite DBs concurrently. WAL allows
    concurrent readers during a write, and busy_timeout makes writers wait for
    a lock instead of immediately raising "database is locked".
    """
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:
        # Non-SQLite backends (or a locked DB at connect time) shouldn't break startup.
        pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
LogsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=logs_engine)
EventsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=events_engine)

Base = declarative_base()
LogsBase = declarative_base()
EventsBase = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_logs_db() -> Generator[Session, None, None]:
    """Dependency for getting logs database sessions."""
    db = LogsSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_events_db() -> Generator[Session, None, None]:
    """Dependency for getting events pipeline database sessions."""
    db = EventsSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    # Ensure all model modules are imported so Base.metadata is complete
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    LogsBase.metadata.create_all(bind=logs_engine)

    # Events pipeline DB
    from .models import event  # noqa: F401
    EventsBase.metadata.create_all(bind=events_engine)

    # Lightweight, idempotent schema migrations for the events DB. Each is guarded
    # by a column-existence check so re-running on every boot is a no-op. Wrapped in
    # try/except so a migration failure surfaces a clear log line instead of an
    # opaque traceback that aborts startup.
    def _ensure_column(conn, table: str, column: str, ddl_type: str) -> None:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        if column not in existing:
            logger.info("Migrating events DB: adding %s.%s", table, column)
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            conn.commit()

    try:
        with events_engine.connect() as conn:
            _ensure_column(conn, "events", "close_recommendation", "BOOLEAN")
            _ensure_column(conn, "events", "broadcast_type", "VARCHAR(64)")
            _ensure_column(conn, "event_transcript_links", "entities_json", "TEXT")
            _ensure_column(conn, "event_transcript_links", "llm_reason", "TEXT")

            # span_store schema changed (dropped legacy label columns, added 'status').
            # Wipe + recreate when the legacy columns are present — user opted-in to a clean slate
            # for entity observations (no backfill). Safe: SpanStore is regenerated from new ingest.
            span_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(span_store)")).fetchall()}
            _LEGACY_SPAN_COLS = {"cross_streets", "persons", "vehicles", "plates"}
            if span_cols & _LEGACY_SPAN_COLS:
                logger.warning(
                    "Migrating events DB: span_store has legacy columns %s — dropping and "
                    "recreating (entity observations are not backfilled).",
                    sorted(span_cols & _LEGACY_SPAN_COLS),
                )
                conn.execute(text("DROP TABLE IF EXISTS span_store"))
                conn.commit()
                # Recreate via SQLAlchemy metadata so new schema is applied.
                from .models.event import SpanStore as _SpanStore
                _SpanStore.__table__.create(bind=events_engine, checkfirst=True)
    except Exception:
        logger.exception("Events DB migration failed")
        raise
