from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Media, Torrent, utcnow  # noqa: E402
from vibestream.services import downloads  # noqa: E402

from .test_release_gone import FILM  # noqa: E402


class EmptyQbit:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def info(self, _hashes):
        return []


def _world():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="Film", media_type="movie")
    session.add(media)
    session.flush()
    session.add(Torrent(id=5, name="Film.2010.1080p", media_id=media.id))
    session.add(Torrent(id=6, name="Film.2010.2160p", media_id=media.id))
    session.commit()
    return session


def test_a_torrent_just_added_is_not_taken_for_vanished(monkeypatch):
    session = _world()
    monkeypatch.setattr(downloads, "QbitClient", EmptyQbit)
    monkeypatch.setattr(downloads, "record_event", lambda *a, **k: None)
    fresh = Download(torrent_id=5, info_hash="a" * 40, state="adding",
                     requested_at=utcnow())
    old = Download(torrent_id=6, info_hash="b" * 40, state="downloading",
                   requested_at=utcnow() - timedelta(hours=1),
                   added_at=utcnow() - timedelta(hours=1))
    session.add_all([fresh, old])
    session.commit()

    asyncio.run(downloads._sync_torrents(session, {"tracked": 0, "errors": 0, "updated": 0}))
    assert fresh.state == "adding" and fresh.reaped_at is None
    assert old.state == "removed" and old.reaped_at is not None


def test_an_add_that_a_sync_took_for_vanished_comes_back(monkeypatch):
    from .test_episode_downloads import FakeQbit

    session = _world()

    class RacingQbit(FakeQbit):
        async def add_torrent_file(self, content, **kwargs):
            return None

        async def __aexit__(self, *_exc):
            for row in session.query(Download).filter(Download.info_hash.is_not(None)):
                row.state = "removed"
                row.reaped_at = utcnow()
            session.commit()

    async def fetch(_torrent_id):
        return FILM

    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    monkeypatch.setattr(downloads, "QbitClient", RacingQbit)
    monkeypatch.setattr(downloads, "record_event", lambda *a, **k: None)

    download = asyncio.run(downloads.request_download(session, 5))
    assert download.state == "downloading" and download.reaped_at is None
