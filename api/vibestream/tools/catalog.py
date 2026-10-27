"""The catalog seed a new server starts with (titles, releases, seasons, episodes; nothing per server).

Usage:
    python -m vibestream.tools.catalog fill
    python -m vibestream.tools.catalog export /tmp/catalog.db.xz
"""

from __future__ import annotations

import json
import logging
import lzma
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

SEED = Path(__file__).resolve().parents[1] / "seed" / "catalog.db.xz"

# In insert order: each after the tables it refers to.
TABLES = ("media", "seasons", "torrents", "episodes")

# Columns about this server's own files and downloads, not the title.
HOUSEHOLD = {
    "episodes": ("download_id", "file_path", "file_size", "prepared_at",
                 "prepare_error", "source_removed_at"),
}


def export(db_path: str, out_path: str) -> dict:
    with tempfile.TemporaryDirectory() as work:
        copy = os.path.join(work, "catalog.db")
        src = sqlite3.connect(db_path)
        try:
            src.execute("VACUUM INTO ?", (copy,))
        finally:
            src.close()
        db = sqlite3.connect(copy)
        try:
            tables = [t for (t,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                if table not in TABLES:
                    db.execute(f'DROP TABLE "{table}"')
            for table, columns in HOUSEHOLD.items():
                db.execute(f'UPDATE "{table}" SET ' + ", ".join(f'"{c}" = NULL' for c in columns))
            counts = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in TABLES}
            db.execute("CREATE TABLE seed_info (key TEXT PRIMARY KEY, value TEXT)")
            db.executemany("INSERT INTO seed_info VALUES (?, ?)", [
                ("exported_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                ("counts", json.dumps(counts)),
            ])
            db.commit()
            db.execute("VACUUM")
        finally:
            db.close()
        with open(copy, "rb") as raw, lzma.open(out_path, "wb", preset=9) as out:
            shutil.copyfileobj(raw, out)
    return counts


def _default(table: str, column: str):
    from sqlalchemy.dialects import sqlite

    from ..models import Base

    col = Base.metadata.tables[table].columns[column]
    default = col.default
    if default is None:
        return None
    value = default.arg(None) if default.is_callable else default.arg
    dialect = sqlite.dialect()
    process = col.type.dialect_impl(dialect).bind_processor(dialect)
    return process(value) if process else value


def seed_if_empty(db_path: str, seed: Path = SEED) -> dict | None:
    """Takes in the seed when there are no titles. Only shared columns are
    copied, so older or newer seeds still load."""
    if not seed.is_file():
        return None
    db = sqlite3.connect(db_path)
    try:
        if db.execute("SELECT COUNT(*) FROM media").fetchone()[0]:
            return None
        with tempfile.TemporaryDirectory() as work:
            unpacked = os.path.join(work, "catalog.db")
            with lzma.open(seed, "rb") as packed, open(unpacked, "wb") as out:
                shutil.copyfileobj(packed, out)
            db.execute("ATTACH DATABASE ? AS seed", (unpacked,))
            counts = {}
            try:
                for table in TABLES:
                    ours = list(db.execute(f'PRAGMA main.table_info("{table}")'))
                    theirs = {r[1] for r in db.execute(f'PRAGMA seed.table_info("{table}")')}
                    columns = [r[1] for r in ours if r[1] in theirs]
                    if not columns:
                        continue
                    # A NOT NULL column newer than the seed, without a SQL default, would make
                    # INSERT OR IGNORE drop every row: it gets the model's default.
                    filled = {r[1]: _default(table, r[1]) for r in ours
                              if r[1] not in theirs and r[3] and r[4] is None and not r[5]}
                    listed = ", ".join(f'"{c}"' for c in [*columns, *filled])
                    values = ", ".join([*(f'"{c}"' for c in columns), *("?" for _ in filled)])
                    before = db.total_changes
                    db.execute(f'INSERT OR IGNORE INTO main."{table}" ({listed}) '
                               f'SELECT {values} FROM seed."{table}"', list(filled.values()))
                    counts[table] = db.total_changes - before
                db.commit()
            finally:
                db.execute("DETACH DATABASE seed")
        return counts
    finally:
        db.close()


async def fill(report=print) -> dict:
    from sqlalchemy import select

    from ..db import session_scope
    from ..models import Media, Season
    from ..services.shows import sync_episodes, sync_seasons

    with session_scope() as s:
        shows = [m for (m,) in s.execute(
            select(Media.id).where(Media.media_type == "tv", Media.tmdb_id.is_not(None))
            .order_by(Media.id))]
    seasons = failed = 0
    began = time.time()
    for at, media_id in enumerate(shows, 1):
        try:
            with session_scope() as s:
                media = s.get(Media, media_id)
                await sync_seasons(s, media)
                numbers = list(s.scalars(select(Season.number).where(Season.media_id == media_id)))
                for number in numbers:
                    await sync_episodes(s, media, number)
                seasons += len(numbers)
        except Exception as exc:
            failed += 1
            log.warning("could not fill show %s: %s", media_id, exc)
        if at % 25 == 0 or at == len(shows):
            report(f"{at}/{len(shows)} shows, {seasons} seasons, {failed} failed, "
                   f"{time.time() - began:.0f}s")
    return {"shows": len(shows), "seasons": seasons, "failed": failed}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "fill":
        import asyncio

        logging.basicConfig(level=logging.WARNING)
        print(json.dumps(asyncio.run(fill(lambda line: print(line, flush=True)))))
        return 0
    if len(argv) == 3 and argv[1] == "export":
        from ..config import settings

        counts = export(settings.db_path, argv[2])
        print(json.dumps(counts), file=sys.stderr)
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
