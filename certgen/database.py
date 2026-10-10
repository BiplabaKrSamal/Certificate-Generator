from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; put UTC back so the API's timestamps are unambiguous."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        options = {"pool_pre_ping": True, "pool_recycle": 300}
        if parsed.drivername == "postgresql+psycopg":
            # Hosted Postgres sits behind a transaction-mode pooler, which can't
            # carry server-side prepared statements.
            options["connect_args"] = {"prepare_threshold": None}
        return create_engine(url, **options)

    engine = create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        # WAL: one request writing doesn't block another reading.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # SQLite ignores foreign keys unless asked; Postgres never does.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_schema(engine: Engine) -> None:
    """Create the tables if they are missing. Safe to run on every cold start."""
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            # Several instances can start at once; let one create the tables.
            connection.execute(text("SELECT pg_advisory_xact_lock(7283104)"))
        Base.metadata.create_all(connection)
