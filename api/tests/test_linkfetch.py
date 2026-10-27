"""Debrid links: a file fetched over HTTPS instead of from the swarm."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.config import settings  # noqa: E402
from vibestream.models import Base, Download, Media, Torrent  # noqa: E402
from vibestream.services import addons, downloads, linkfetch  # noqa: E402

FILM = b"x" * 1000


@pytest.fixture
def world(monkeypatch, tmp_path):
    # One connection for every thread: progress is written from a thread.
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    film = Media(title="Night of the Living Dead", media_type="movie", imdb_id="tt0063350")
    session.add(film)
    session.flush()
    torrent = Torrent(id=addons.FIRST_ID, origin="addon", name="Night.of.the.Living.Dead.1968.1080p",
                      media_id=film.id, info_hash="c" * 40, linkable=True, size_bytes=len(FILM))
    download = Download(torrent_id=torrent.id, link="https://debrid.example/d/1", state="downloading")
    session.add_all([torrent, download])
    session.commit()

    class Scope:
        """Committed on success, rolled back on error, as session_scope does."""

        def __enter__(self):
            return session

        def __exit__(self, kind, *_exc):
            if kind is None:
                session.commit()
            else:
                session.rollback()
            return False

    saved = settings.qbit_download_dir
    object.__setattr__(settings, "qbit_download_dir", str(tmp_path))
    monkeypatch.setattr(linkfetch, "session_scope", lambda: Scope())
    monkeypatch.setattr(linkfetch, "PLACEHOLDER_BYTES", 100)
    yield session, download
    object.__setattr__(settings, "qbit_download_dir", saved)
    session.close()


def serve(monkeypatch, handler):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(linkfetch, "outbound_client", client)


def test_a_link_is_fetched_under_the_name_the_service_gives(world, monkeypatch):
    _, download = world
    serve(monkeypatch, lambda request: httpx.Response(
        200, content=FILM,
        headers={"content-disposition": 'attachment; filename="Night.1968.1080p.mkv"'}))
    path, size = asyncio.run(linkfetch._fetch(download.id, download.link, "fallback"))
    assert os.path.basename(path) == "Night.1968.1080p.mkv" and size == len(FILM)
    assert open(path, "rb").read() == FILM
    assert not os.path.exists(os.path.join(linkfetch.folder(download.id), linkfetch.PARTIAL))


def test_an_interrupted_fetch_carries_on_where_it_stopped(world, monkeypatch):
    _, download = world
    os.makedirs(linkfetch.folder(download.id))
    with open(os.path.join(linkfetch.folder(download.id), linkfetch.PARTIAL), "wb") as fh:
        fh.write(FILM[:400])
    asked = []

    def handler(request):
        asked.append(request.headers.get("range"))
        return httpx.Response(206, content=FILM[400:], headers={"content-type": "video/x-matroska"})

    serve(monkeypatch, handler)
    path, size = asyncio.run(linkfetch._fetch(download.id, "https://debrid.example/d/1", "Film 1968"))
    assert asked == ["bytes=400-"]
    assert size == len(FILM) and open(path, "rb").read() == FILM
    assert os.path.basename(path) == "Film 1968.mkv"


def test_a_stand_in_video_is_not_taken_for_the_film(world, monkeypatch):
    _, download = world
    serve(monkeypatch, lambda request: httpx.Response(200, content=b"tiny"))
    with pytest.raises(linkfetch.Placeholder):
        asyncio.run(linkfetch._fetch(download.id, download.link, "x"))


def test_a_dead_link_is_told_apart(world, monkeypatch):
    _, download = world
    serve(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(linkfetch.LinkGone):
        asyncio.run(linkfetch._fetch(download.id, download.link, "x"))


def test_a_dead_link_is_asked_for_again_once(world, monkeypatch):
    session, download = world
    asked = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, content=FILM) if "fresh" in str(request.url) \
            else httpx.Response(410)

    serve(monkeypatch, handler)

    async def link_for(torrent, season=None, episode=None):
        return "https://debrid.example/fresh/Night.1968.mkv"

    async def publish(session, download, name, wanted=None):
        download.state = "linked"
        return "published"

    monkeypatch.setattr(addons, "link_for", link_for)
    monkeypatch.setattr(downloads, "publish", publish)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert asked[-1].endswith("/fresh/Night.1968.mkv")
    # Whole, so the link, which holds the service's key, is down to its host.
    assert download.link == "https://debrid.example/"
    assert download.state == "linked" and download.progress == 1.0
    assert download.content_path.endswith("Night.1968.mkv")
    assert download.primary_file_size == len(FILM)


def test_a_link_download_shows_as_a_torrent_would(world):
    _, download = world
    download.progress, download.downloaded_bytes = 0.5, 500
    status = linkfetch.status(download)
    assert status.progress == 0.5 and status.size == len(FILM)
    assert linkfetch.status(Download(torrent_id=1)) is None


def test_a_416_is_only_the_end_when_the_sizes_agree(world, monkeypatch):
    _, download = world
    where = linkfetch.folder(download.id)
    os.makedirs(where)
    partial = os.path.join(where, linkfetch.PARTIAL)
    with open(partial, "wb") as fh:
        fh.write(FILM)

    serve(monkeypatch, lambda request: httpx.Response(416, headers={"content-range": "bytes */5"}))
    with pytest.raises(linkfetch.LinkError):
        asyncio.run(linkfetch._fetch(download.id, download.link, "Film"))
    assert not os.path.exists(partial)

    with open(partial, "wb") as fh:
        fh.write(FILM)
    serve(monkeypatch, lambda request: httpx.Response(
        416, headers={"content-range": f"bytes */{len(FILM)}"}))
    path, size = asyncio.run(linkfetch._fetch(download.id, download.link, "Film"))
    assert size == len(FILM) and open(path, "rb").read() == FILM


def test_a_failed_publish_never_fetches_the_file_again(world, monkeypatch):
    session, download = world
    served = []

    def handler(request):
        served.append(1)
        return httpx.Response(200, content=FILM)

    serve(monkeypatch, handler)
    publishes = []

    async def publish(session, download, name, wanted=None):
        publishes.append(download.id)
        if len(publishes) == 1:
            raise OSError("No space left on device")
        download.library_path = "/library/Film"
        download.state = "linked"
        return "published"

    monkeypatch.setattr(downloads, "publish", publish)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert download.state == "completed" and download.progress == 1.0
    assert download.link == "https://debrid.example/"

    assert linkfetch.ensure_running(session) == 0
    monkeypatch.setattr(linkfetch, "REPUBLISH_SECONDS", 0)
    assert asyncio.run(linkfetch.publish_stragglers(session)) == 1
    assert served == [1] and download.state == "linked"


def test_a_long_fetch_on_a_poor_line_keeps_going_while_it_gets_somewhere(world, monkeypatch):
    session, download = world
    monkeypatch.setattr(linkfetch, "MOST_FAILURES", 2)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(linkfetch.asyncio, "sleep", no_wait)

    def handler(request):
        start = int((request.headers.get("range") or "bytes=0-")[6:].rstrip("-") or 0)
        return httpx.Response(206 if start else 200, content=FILM[start:start + 100],
                              headers={"content-length": str(len(FILM) - start)})

    serve(monkeypatch, handler)

    async def publish(session, download, name, wanted=None):
        return "published"

    monkeypatch.setattr(downloads, "publish", publish)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert download.state == "completed"
    assert open(download.content_path, "rb").read() == FILM


def test_a_restart_still_prepares_what_came_by_link(world, monkeypatch):
    session, download = world
    download.state, download.progress = "linked", 1.0
    session.commit()
    pending = []

    class Preparation:
        def ensure_pending(self, session):
            pending.append(True)

    monkeypatch.setattr(downloads, "preparation", lambda: Preparation())
    monkeypatch.setattr(downloads, "SOURCES_EVERY_SECONDS", 10 ** 9)
    asyncio.run(downloads.sync_active(session))
    assert pending == [True]


def test_asking_for_a_link_that_breaks_falls_back_to_the_torrent(world, monkeypatch):
    session, download = world
    download.state, download.link = "error", "https://debrid.example/"
    session.commit()
    os.makedirs(linkfetch.folder(download.id))

    async def link_for(torrent, season=None, episode=None):
        raise ValueError("an addon said something odd")

    async def fetch(torrent_id):
        raise downloads.DownloadError("nobody sharing this release answered")

    monkeypatch.setattr(addons, "link_for", link_for)
    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.request_download(session, download.torrent_id))
    session.refresh(download)
    assert download.state == "error" and download.link is None
    assert not os.path.exists(linkfetch.folder(download.id))


def _meta(*files):
    from vibestream.torrentmeta import TorrentFile, TorrentMeta

    offset, out = 0, []
    for path, length in files:
        out.append(TorrentFile(path=path, length=length, offset=offset))
        offset += length
    return TorrentMeta(infohash="d" * 40, name="box", piece_length=1 << 20,
                       total_length=offset, files=out)


def test_a_box_set_film_is_found_by_its_name_or_refused():
    box = _meta(("Box/Night.of.the.Living.Dead.1968.mkv", 4_000), ("Box/Dawn.of.the.Dead.1978.mkv", 5_000))
    torrent = Torrent(name="Romero Collection", file_name="night of the living dead 1968.mkv")
    assert downloads._film_in_box_set(torrent, box).path.endswith("Night.of.the.Living.Dead.1968.mkv")
    torrent.file_name = "Day.of.the.Dead.1985.mkv"
    with pytest.raises(downloads.DownloadError):
        downloads._film_in_box_set(torrent, box)
    extras = _meta(("Film/Film.2020.mkv", 9_000), ("Film/Behind.the.Scenes.mkv", 1_000))
    torrent.file_name = "Film.2020.1080p.mkv"
    assert downloads._film_in_box_set(torrent, extras) is None


def test_two_films_of_one_box_set_are_not_fetched_as_one(world, monkeypatch):
    session, first = world
    first.state, first.info_hash, first.link = "downloading", "d" * 40, None
    second = Torrent(id=addons.FIRST_ID + 1, origin="addon", name="Romero Collection",
                     media_id=first.torrent.media_id, info_hash="d" * 40,
                     file_name="Dawn.of.the.Dead.1978.mkv")
    session.add(second)
    session.commit()

    async def fetch(torrent_id):
        return b"x"

    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    monkeypatch.setattr(downloads, "parse_torrent", lambda content: _meta(
        ("Box/Night.mkv", 4_000), ("Box/Dawn.of.the.Dead.1978.mkv", 5_000)))
    with pytest.raises(downloads.DownloadError, match="same torrent"):
        asyncio.run(downloads.request_download(session, second.id))
    row = session.scalar(select(Download).where(Download.torrent_id == second.id))
    assert row.state == "error" and row.info_hash is None


def test_a_link_kept_whole_by_an_older_download_is_cut_down(world, monkeypatch):
    session, download = world
    download.state, download.link = "linked", "https://debrid.example/d/KEY/film.mkv"
    session.commit()
    monkeypatch.setattr(linkfetch, "_redacted_old", False)
    linkfetch.ensure_running(session)
    assert download.link == "https://debrid.example/"
