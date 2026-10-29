"""Numbered changes to the database, applied once each, in order.

The number reached is kept in SQLite's user_version. A new database is made
whole by create_all and starts at the last number. New columns need no step
here (db._add_missing_columns adds them); renames, removals and changes to
existing rows do. Append only: a step, once released, is never edited.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger(__name__)


class NewerDatabase(RuntimeError):
    pass


def _retire_watch_states(conn: Connection) -> None:
    conn.execute(text('DROP TABLE IF EXISTS "watch_states"'))


def _love_is_like(conn: Connection) -> None:
    conn.execute(text("UPDATE ratings SET value = 1 WHERE value > 1"))


def _torrentio_is_an_addon(conn: Connection) -> None:
    conn.execute(text("UPDATE torrents SET origin = 'addon' WHERE origin = 'torrentio'"))


def _maturity_from_facts(conn: Connection) -> None:
    import json

    from .services.maturity import age

    rows = conn.execute(text("SELECT id, facts FROM media WHERE facts IS NOT NULL")).all()
    for media_id, facts in rows:
        try:
            certification = (json.loads(facts) or {}).get("certification")
        except (TypeError, ValueError):
            continue
        conn.execute(text("UPDATE media SET maturity = :age WHERE id = :id"),
                     {"age": age(certification), "id": media_id})


STEPS: list[Callable[[Connection], None]] = [
    _retire_watch_states,
    _love_is_like,
    _torrentio_is_an_addon,
    _maturity_from_facts,
]


def schema(conn: Connection) -> int:
    return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def migrate(engine: Engine, fresh: bool) -> None:
    """Bring the database to len(STEPS), each step in its own transaction.
    A database past len(STEPS) is from a newer VibeStream, and is refused."""
    with engine.begin() as conn:
        at = schema(conn)
        if fresh:
            conn.exec_driver_sql(f"PRAGMA user_version = {len(STEPS)}")
            return
    if at > len(STEPS):
        raise NewerDatabase(
            f"the database is from a newer VibeStream (schema {at}, this version knows "
            f"{len(STEPS)}): update again, or restore the backup taken before the update"
        )
    for number in range(at, len(STEPS)):
        with engine.begin() as conn:
            STEPS[number](conn)
            conn.exec_driver_sql(f"PRAGMA user_version = {number + 1}")
        log.info("database schema %d: %s", number + 1, STEPS[number].__name__.strip("_"))
