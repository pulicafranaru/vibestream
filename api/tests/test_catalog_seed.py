from __future__ import annotations

import lzma
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402

from vibestream.models import Base  # noqa: E402
from vibestream.tools import catalog  # noqa: E402


def _server(path: Path) -> str:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return str(path)


def _established(path: Path) -> str:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from vibestream.models import Episode, Media, Profile, Season, Torrent

    db = _server(path)
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        s.add(Media(id=1, tmdb_id=1399, media_type="tv", title="A Show",
                    poster_path="/poster.jpg", coverage=0.8))
        s.add(Season(id=1, media_id=1, number=1, name="Season 1"))
        s.add(Torrent(id=7, name="A.Show.S01", category=21, media_id=1, season=1))
        s.add(Episode(id=1, media_id=1, season_id=1, season_number=1, number=1, name="Pilot",
                      still_path="/still.jpg", file_path="/data/library/Shows/A Show/S01E01.mkv",
                      file_size=123, prepared_at=datetime(2026, 10, 1)))
        s.add(Profile(id=1, name="Somebody", avatar="crimson-smile"))
        s.commit()
    engine.dispose()
    return db


def _unpack(packed: Path, to: Path) -> sqlite3.Connection:
    to.write_bytes(lzma.decompress(packed.read_bytes()))
    return sqlite3.connect(to)


def test_an_export_holds_the_catalog_and_nothing_of_the_household(tmp_path):
    out = tmp_path / "catalog.db.xz"
    counts = catalog.export(_established(tmp_path / "old.db"), str(out))
    assert counts == {"media": 1, "seasons": 1, "torrents": 1, "episodes": 1}
    seed = _unpack(out, tmp_path / "seed.db")
    tables = {t for (t,) in seed.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"media", "seasons", "torrents", "episodes", "seed_info"}
    row = seed.execute("SELECT name, still_path, file_path, file_size, prepared_at FROM episodes").fetchone()
    assert row == ("Pilot", "/still.jpg", None, None, None)
    assert seed.execute("SELECT coverage FROM media").fetchone() == (0.8,)


def test_a_new_server_takes_the_seed_in(tmp_path):
    out = tmp_path / "catalog.db.xz"
    catalog.export(_established(tmp_path / "old.db"), str(out))
    new = _server(tmp_path / "new.db")
    assert catalog.seed_if_empty(new, out) == {"media": 1, "seasons": 1, "torrents": 1, "episodes": 1}
    c = sqlite3.connect(new)
    assert c.execute("SELECT title FROM media").fetchone() == ("A Show",)
    assert c.execute("SELECT name, file_path FROM episodes").fetchone() == ("Pilot", None)
    assert c.execute("SELECT COUNT(*) FROM profiles").fetchone() == (0,)


def test_a_server_with_titles_is_left_alone(tmp_path):
    out = tmp_path / "catalog.db.xz"
    catalog.export(_established(tmp_path / "old.db"), str(out))
    busy = _established(tmp_path / "busy.db")
    assert catalog.seed_if_empty(busy, out) is None


def test_no_seed_no_trouble(tmp_path):
    assert catalog.seed_if_empty(_server(tmp_path / "new.db"), tmp_path / "missing.db.xz") is None


def test_the_shipped_seed_brings_its_releases(tmp_path):
    """Seed rows predating NOT NULL release columns get defaults instead of being dropped."""
    new = _server(tmp_path / "new.db")
    counts = catalog.seed_if_empty(new)
    seed = _unpack(catalog.SEED, tmp_path / "seed.db")
    for table in catalog.TABLES:
        assert counts[table] == seed.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    c = sqlite3.connect(new)
    assert c.execute("SELECT COUNT(*) FROM torrents WHERE origin = 'filelist' "
                     "AND linkable = 0 AND held = 0").fetchone()[0] == counts["torrents"]


def _without_sql_defaults(path: Path) -> str:
    """A database made before the models had SQL defaults."""
    import re

    from sqlalchemy.schema import CreateTable

    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(engine))
            conn.exec_driver_sql(re.sub(r" DEFAULT ('(?:[^']|'')*'|[-\d.]+)", "", ddl))
    engine.dispose()
    return str(path)


def test_a_seed_older_than_the_schema_still_goes_in(tmp_path):
    out = tmp_path / "catalog.db.xz"
    old = _established(tmp_path / "old.db")
    c = sqlite3.connect(old)
    for column in ("origin", "linkable", "held", "first_seen"):
        c.execute(f'ALTER TABLE torrents DROP COLUMN "{column}"')
    c.commit()
    c.close()
    catalog.export(old, str(out))
    new = _without_sql_defaults(tmp_path / "new.db")
    assert catalog.seed_if_empty(new, out)["torrents"] == 1
    c = sqlite3.connect(new)
    origin, linkable, held, first_seen = c.execute(
        "SELECT origin, linkable, held, first_seen FROM torrents").fetchone()
    assert (origin, linkable, held) == ("filelist", 0, 0)
    assert first_seen


def test_every_constant_default_is_also_a_sql_default():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.default is not None and column.default.is_scalar:
                assert column.server_default is not None, f"{table.name}.{column.name}"
