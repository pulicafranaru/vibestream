from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Episode, Media, Season, Torrent, utcnow  # noqa: E402
from vibestream.services import shows  # noqa: E402


def test_each_single_episode_download_claims_only_its_episode(tmp_path, monkeypatch):
    async def no_sync(*_a, **_k):
        return None

    monkeypatch.setattr(shows, "sync_episodes", no_sync)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="Show", media_type="tv")
    session.add(media)
    session.flush()
    season = Season(media_id=media.id, number=1)
    session.add(season)
    session.flush()
    folder = tmp_path / "Show" / "Season 01"
    folder.mkdir(parents=True)
    downloads = []
    for number in (1, 2):
        (folder / f"Show.S01E0{number}.1080p.mkv").write_bytes(b"x")
        session.add(Episode(media_id=media.id, season_id=season.id,
                            season_number=1, number=number, name=f"E{number}"))
        session.add(Torrent(id=number, name=f"Show.S01E0{number}.1080p",
                            media_id=media.id, season=1, episode=number))
        download = Download(torrent_id=number, state="linked", library_path=str(folder))
        session.add(download)
        downloads.append(download)
    session.commit()

    for _ in range(2):
        for download in downloads:
            asyncio.run(shows.attach_files(session, download))

    owners = {e.number: e.download_id for e in session.query(Episode)}
    assert owners == {1: downloads[0].id, 2: downloads[1].id}
    episode = session.query(Episode).filter_by(number=1).one()
    episode.prepared_at = utcnow()
    session.commit()
    asyncio.run(shows.attach_files(session, downloads[1]))
    assert episode.prepared_at is not None
