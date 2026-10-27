"""SQLite stores no timezone, so datetimes must come back UTC aware."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Torrent, WatchProgress, Profile, utcnow  # noqa: E402


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


def test_utcnow_is_aware():
    assert utcnow().tzinfo is not None


def test_roundtrip_preserves_awareness():
    s = _session()
    s.add(Torrent(id=1, name="x", upload_date=utcnow()))
    s.commit()
    s.expunge_all()

    row = s.scalar(select(Torrent).where(Torrent.id == 1))
    assert row.upload_date.tzinfo is not None
    assert row.upload_date < utcnow() + timedelta(seconds=1)


def test_naive_input_is_stored_as_utc():
    s = _session()
    naive = datetime(2026, 1, 2, 3, 4, 5)
    s.add(Torrent(id=2, name="y", upload_date=naive))
    s.commit()
    s.expunge_all()

    row = s.scalar(select(Torrent).where(Torrent.id == 2))
    assert row.upload_date.tzinfo is not None
    assert row.upload_date == naive.replace(tzinfo=timezone.utc)


def test_non_utc_input_is_normalised():
    s = _session()
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 2, 12, 0, 0, tzinfo=plus_two)
    s.add(Torrent(id=3, name="z", upload_date=local))
    s.commit()
    s.expunge_all()

    row = s.scalar(select(Torrent).where(Torrent.id == 3))
    assert row.upload_date == datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)


def test_none_stays_none():
    s = _session()
    s.add(Torrent(id=4, name="n", upload_date=None))
    s.commit()
    s.expunge_all()
    assert s.scalar(select(Torrent).where(Torrent.id == 4)).upload_date is None


def test_reaper_style_grace_comparison_does_not_raise():
    s = _session()
    s.add(Torrent(id=5, name="show"))
    s.flush()
    d = Download(torrent_id=5, info_hash="abc")
    s.add(d)
    s.flush()
    profile = Profile(name="p")
    s.add(profile)
    s.flush()
    s.add(WatchProgress(profile_id=profile.id, download_id=d.id,
                        finished_at=utcnow() - timedelta(days=30)))
    s.commit()
    s.expunge_all()

    progress = s.scalar(select(WatchProgress))
    cutoff = utcnow() - timedelta(days=7)
    assert progress.finished_at < cutoff
