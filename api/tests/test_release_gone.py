"""The tracker never says a release is gone: download.php answers with an HTML page instead."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Episode, Media, Season, Torrent  # noqa: E402
from vibestream.schemas import download_summary  # noqa: E402
from vibestream.services import downloads, shows  # noqa: E402
from vibestream.services.filelist import GONE_PAGE  # noqa: E402

from .test_episode_downloads import FakeQbit, bencode  # noqa: E402

GONE_HTML = (
    b"\n<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Transitional//EN\">"
    b"<div>Eroare interna</div><div>Nu pot gasi fisierul .torrent</div>"
)

FILM = bencode({
    "announce": "http://tracker.invalid/announce",
    "info": {"name": "Film.2010.1080p.mkv", "piece length": 262144,
             "pieces": b"\x00" * 20, "length": 5000},
})


def test_the_deleted_page_is_recognised():
    assert GONE_PAGE.search(GONE_HTML)
    assert not GONE_PAGE.search(b"<html>Login</html>")


def test_errors_read_as_words():
    raw = ("could not fetch .torrent for 703584: torrent download returned "
           "non-bencoded data: b'\\n<!DOCTYPE html PUBLIC'")
    assert downloads.friendly_error(raw) == \
        "The tracker did not hand over the download. Try again in a minute."
    assert downloads.friendly_error("the tracker no longer has this release (1)") == \
        "This release was removed from the tracker."
    assert downloads.friendly_error("no copy left on the tracker") == \
        "None of this title's releases are on the tracker any more."
    assert downloads.friendly_error("something nobody foresaw") == \
        "The download could not start. Try again."
    assert downloads.friendly_error(None) is None


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    deleted: set[int] = set()

    async def fetch(torrent_id):
        if torrent_id in deleted:
            raise downloads.ReleaseGone(f"the tracker no longer has this release ({torrent_id})")
        return FILM

    FakeQbit.calls = []
    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    monkeypatch.setattr(downloads, "QbitClient", FakeQbit)
    monkeypatch.setattr(downloads, "record_event", lambda *a, **k: None)
    yield session, deleted
    session.close()


def film(session):
    media = Media(title="Inception", media_type="movie")
    session.add(media)
    session.flush()
    best = Torrent(id=703584, name="Inception.2010.2160p.UHD.BluRay.x265", media_id=media.id,
                   resolution="2160p", source="BluRay", size_bytes=30 * 1024 ** 3)
    other = Torrent(id=776902, name="Inception.2010.1080p.BluRay.x264", media_id=media.id,
                    resolution="1080p", source="BluRay", size_bytes=17 * 1024 ** 3, seeders=126)
    session.add_all([best, other])
    session.commit()
    return media, best, other


def test_a_deleted_film_release_gives_way_to_the_next(world):
    session, deleted = world
    media, best, other = film(session)
    deleted.add(best.id)

    download = asyncio.run(downloads.request_with_fallback(session, best.id))

    assert download.torrent_id == other.id
    assert download_summary(download)["error_message"] is None
    gone = session.get(Torrent, best.id)
    assert gone.gone_at is not None and gone.media_id is None
    assert session.scalar(select(Download).where(Download.torrent_id == best.id)) is None


def test_nothing_left_says_so(world):
    session, deleted = world
    media, best, other = film(session)
    deleted.update({best.id, other.id})

    with pytest.raises(downloads.DownloadError) as caught:
        asyncio.run(downloads.request_with_fallback(session, best.id))
    assert downloads.friendly_error(str(caught.value)) == \
        "None of this title's releases are on the tracker any more."
    assert all(session.get(Torrent, t).media_id is None for t in (best.id, other.id))


def test_a_deleted_pack_gives_way_to_the_episode_on_its_own(world, monkeypatch):
    session, deleted = world
    media = Media(title="Show", media_type="tv")
    session.add(media)
    session.flush()
    season = Season(media_id=media.id, number=1)
    session.add(season)
    session.flush()
    episode = Episode(media_id=media.id, season_id=season.id, season_number=1, number=2)
    session.add(episode)
    pack = Torrent(id=10, name="Show.S01.2160p.WEB-DL", media_id=media.id,
                   season=1, resolution="2160p", source="WEB-DL", size_bytes=40 * 1024 ** 3)
    single = Torrent(id=11, name="Show.S01E02.1080p.WEB-DL", media_id=media.id,
                     season=1, episode=2, resolution="1080p", source="WEB-DL",
                     size_bytes=3 * 1024 ** 3)
    unrelated = Torrent(id=12, name="Show.S01E03.1080p.WEB-DL", media_id=media.id,
                        season=1, episode=3, resolution="1080p", source="WEB-DL",
                        size_bytes=3 * 1024 ** 3)
    session.add_all([pack, single, unrelated])
    session.commit()
    deleted.add(pack.id)

    async def no_sync(*_args, **_kwargs):
        return None

    monkeypatch.setattr(shows, "sync_episodes", no_sync)
    download = asyncio.run(downloads.request_with_fallback(session, pack.id, episode_id=episode.id))
    assert download.torrent_id == single.id
