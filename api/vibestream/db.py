from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base, Event

log = logging.getLogger(__name__)


def _make_engine() -> Engine:
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    eng = create_engine(
        f"sqlite+pysqlite:///{settings.db_path}",
        echo=False,
        future=True,
        connect_args={"timeout": 30, "check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        # Not journal_mode: it takes a brief exclusive lock, so setting it per
        # connection stalls new connections for the busy timeout while a writer
        # is active. WAL is persistent and set once below.
        # pragma needs a brief exclusive lock, so every new pooled connection
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    with eng.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
        log.info("sqlite journal mode: %s", mode)

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _add_missing_columns() -> None:
    """Additive migration: create_all() never adds columns to existing tables."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = f"{column.name} {column.type.compile(engine.dialect)}"
                default = column.default
                server = getattr(column.server_default, "arg", None)
                if server is not None:
                    ddl += f" DEFAULT {getattr(server, 'text', server)}"
                elif default is not None and not callable(getattr(default, "arg", None)):
                    value = getattr(default, "arg", None)
                    if isinstance(value, bool):
                        ddl += f" DEFAULT {1 if value else 0}"
                    elif isinstance(value, (int, float)):
                        ddl += f" DEFAULT {value}"
                    elif isinstance(value, str):
                        ddl += f" DEFAULT '{value}'"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                log.info("added column %s.%s", table.name, column.name)


_RETIRED_TABLES = ("watch_states",)


def init_db() -> None:
    from sqlalchemy import text

    Base.metadata.create_all(engine)
    _add_missing_columns()
    with engine.begin() as conn:
        for name in _RETIRED_TABLES:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        conn.execute(text("UPDATE ratings SET value = 1 WHERE value > 1"))
        conn.execute(text("UPDATE torrents SET origin = 'addon' WHERE origin = 'torrentio'"))
    log.info("database ready at %s", settings.db_path)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def record_event(
    session: Session, source: str, message: str, detail: str | None = None, level: str = "info"
) -> None:
    session.add(Event(source=source, message=message, detail=detail, level=level))
    log.log(
        {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING,
         "error": logging.ERROR}.get(level, logging.INFO),
        "[%s] %s %s", source, message, detail or "",
    )


def kv_get(session: Session, key: str, default: str = "") -> str:
    from .models import KV

    row = session.get(KV, key)
    return row.value if row else default


def kv_set(session: Session, key: str, value: str) -> None:
    from .models import KV, utcnow

    row = session.get(KV, key)
    if row:
        row.value = value
        row.updated_at = utcnow()
    else:
        session.add(KV(key=key, value=value))
