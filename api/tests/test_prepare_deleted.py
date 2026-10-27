from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Media, Torrent, utcnow  # noqa: E402
from vibestream.services import preparation  # noqa: E402


def test_a_film_deleted_while_preparing_is_not_marked_ready(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="Film", media_type="movie")
    session.add(media)
    session.flush()
    session.add(Torrent(id=5, name="Film.2010.1080p", media_id=media.id))
    download = Download(torrent_id=5, state="linked")
    session.add(download)
    session.commit()
    path = tmp_path / "Film (2010).mkv"
    path.write_bytes(b"film")

    class Scope:
        def __enter__(self):
            return session

        def __exit__(self, kind, *_exc):
            session.commit() if kind is None else session.rollback()
            return False

    cleared = []

    async def prepare_file(*_args):
        download.state = "removed"
        download.reaped_at = utcnow()
        session.commit()
        return None

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(preparation, "session_scope", lambda: Scope())
    monkeypatch.setattr(preparation, "_resolve_path", lambda _d, _e=None: str(path))
    monkeypatch.setattr(preparation, "_prepare_file", prepare_file)
    monkeypatch.setattr(preparation, "_build_extras", nothing)
    monkeypatch.setattr(preparation.mediainfo, "probe", nothing)
    monkeypatch.setattr(preparation.hls, "clear_for", cleared.append)
    monkeypatch.setattr(preparation.trickplay, "clear_for", lambda _p: None)

    asyncio.run(preparation.prepare(download.id))
    assert download.prepared_at is None
    assert cleared == [str(path)]
