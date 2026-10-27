"""TorBox: addon releases fetched through it, and filelist ones never sent."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.config import settings  # noqa: E402
from vibestream.models import Base, Download, Media, Torrent  # noqa: E402
from vibestream.services import addons, downloads, linkfetch, torbox  # noqa: E402

FILM = b"x" * 1000
CDN = "https://cdn.torbox.example/dl/film.mkv"
FILES = [{"id": 1, "name": "Night/Sample.mkv", "size": 50},
         {"id": 2, "name": "Night/Night.of.the.Living.Dead.1968.1080p.mkv", "size": 1000},
         {"id": 3, "name": "Night/poster.jpg", "size": 10}]


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    film = Media(title="Night of the Living Dead", media_type="movie", imdb_id="tt0063350")
    session.add(film)
    session.flush()
    torrent = Torrent(id=addons.FIRST_ID, origin="addon", name="Night.of.the.Living.Dead.1968.1080p",
                      media_id=film.id, info_hash="c" * 40, size_bytes=len(FILM),
                      announce=json.dumps(["udp://tracker.example:1337/announce"]))
    private = Torrent(id=1234, origin="filelist", name="Night.of.the.Living.Dead.1968.2160p",
                      media_id=film.id, info_hash="f" * 40, size_bytes=len(FILM))
    download = Download(torrent_id=torrent.id, link="torbox:7", state="downloading")
    session.add_all([torrent, private, download])
    session.commit()

    class Scope:
        def __enter__(self):
            return session

        def __exit__(self, kind, *_exc):
            session.commit() if kind is None else session.rollback()
            return False

    saved = settings.qbit_download_dir, settings.torbox_api_key
    object.__setattr__(settings, "qbit_download_dir", str(tmp_path))
    object.__setattr__(settings, "torbox_api_key", "test-key")
    monkeypatch.setattr(linkfetch, "session_scope", lambda: Scope())
    monkeypatch.setattr(linkfetch, "PLACEHOLDER_BYTES", 100)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(linkfetch.asyncio, "sleep", no_wait)
    yield session, download, torrent, private
    object.__setattr__(settings, "qbit_download_dir", saved[0])
    object.__setattr__(settings, "torbox_api_key", saved[1])
    session.close()


class Service:
    """TorBox and its file server, answering from a script."""

    def __init__(self, states=None, cached=None, links=None):
        self.states = list(states or [{"download_finished": True, "progress": 1.0, "files": FILES}])
        self.cached = cached
        self.links = list(links or [CDN])
        self.calls: list[tuple[str, str]] = []
        self.cdn = [200]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if request.url.host == "cdn.torbox.example":
            status = self.cdn.pop(0) if len(self.cdn) > 1 else self.cdn[0]
            return httpx.Response(status, content=FILM if status == 200 else b"")
        assert request.headers["authorization"] == "Bearer test-key"
        if path.endswith("/torrents/mylist"):
            data = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return httpx.Response(200, json={"success": True, "data": data})
        if path.endswith("/torrents/requestdl"):
            link = self.links.pop(0) if len(self.links) > 1 else self.links[0]
            return httpx.Response(200, json={"success": True, "data": link})
        if path.endswith("/torrents/controltorrent"):
            return httpx.Response(200, json={"success": True, "data": None})
        if path.endswith("/torrents/createtorrent"):
            return httpx.Response(200, json={"success": True, "data": {"torrent_id": 42}})
        if path.endswith("/torrents/checkcached"):
            return httpx.Response(200, json={"success": True, "data": self.cached})
        return httpx.Response(404, json={"success": False, "detail": "unknown"})

    def deleted(self) -> bool:
        return ("POST", "/v1/api/torrents/controltorrent") in self.calls


def serve(monkeypatch, service: Service) -> None:
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(service), **kwargs)

    monkeypatch.setattr(linkfetch, "outbound_client", client)
    monkeypatch.setattr(torbox, "outbound_client", client)


async def _published(session, download, name, wanted=None):
    download.library_path = "/library/Night"
    download.state = "linked"
    return "published"


def test_filelist_releases_are_never_sent_to_torbox(world, monkeypatch):
    session, _, torrent, private = world
    assert torbox.allowed(torrent) and not torbox.allowed(private)
    assert not downloads._by_torbox(private, None, False)
    with pytest.raises(torbox.TorboxError):
        asyncio.run(torbox.add(private))

    sent = []

    async def add(t):
        sent.append(t.id)
        return 1

    async def fetch(torrent_id):
        raise downloads.DownloadError("no tracker in a test")

    monkeypatch.setattr(torbox, "add", add)
    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.request_download(session, private.id))
    assert sent == []


def test_a_release_torbox_holds_is_fetched_and_taken_off_the_account(world, monkeypatch):
    session, download, *_ = world
    service = Service()
    serve(monkeypatch, service)
    monkeypatch.setattr(downloads, "publish", _published)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert download.state == "linked" and download.progress == 1.0
    assert open(download.content_path, "rb").read() == FILM
    assert download.link == "torbox:"
    assert service.deleted()


def test_a_release_torbox_fetches_first_shows_its_progress_and_waits(world, monkeypatch):
    session, download, *_ = world
    progress = []
    service = Service(states=[
        {"download_finished": False, "progress": 0.25, "download_speed": 5_000_000, "eta": 60},
        {"download_finished": False, "progress": 0.75, "download_speed": 5_000_000, "eta": 20},
        {"download_finished": True, "progress": 1.0, "files": FILES},
    ])
    serve(monkeypatch, service)
    saved = linkfetch._save

    async def watch(download_id, **fields):
        if "progress" in fields:
            progress.append(fields["progress"])
        await saved(download_id, **fields)

    monkeypatch.setattr(linkfetch, "_save", watch)
    monkeypatch.setattr(downloads, "publish", _published)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert progress[:2] == [0.25, 0.75] and download.state == "linked"


def test_an_expired_link_is_asked_for_again_from_torbox(world, monkeypatch):
    session, download, *_ = world
    service = Service(links=[CDN, CDN + "?fresh"])
    service.cdn = [403, 200]
    serve(monkeypatch, service)
    monkeypatch.setattr(downloads, "publish", _published)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert download.state == "linked"
    assert service.calls.count(("GET", "/v1/api/torrents/requestdl")) == 2


def test_a_release_nobody_shares_is_given_up_on_and_cleaned_up(world, monkeypatch):
    session, download, *_ = world
    service = Service(states=[{"download_finished": False, "progress": 0.0,
                               "download_state": "stalled (no seeds)"}])
    serve(monkeypatch, service)
    monkeypatch.setattr(linkfetch, "TORBOX_STALL_SECONDS", -1)
    asyncio.run(linkfetch._run(download.id))
    session.refresh(download)
    assert download.state == "error" and "nobody sharing" in download.error
    assert download.link == "torbox:" and service.deleted()


def test_what_torbox_holds_is_read_in_either_shape(world, monkeypatch):
    serve(monkeypatch, Service(cached=[{"hash": "C" * 40, "name": "x"}]))
    assert asyncio.run(torbox.held(["c" * 40, "d" * 40])) == {"c" * 40}
    serve(monkeypatch, Service(cached={"c" * 40: {"name": "x"}, "d" * 40: None}))
    assert asyncio.run(torbox.held(["c" * 40, "d" * 40])) == {"c" * 40}


def test_releases_torbox_holds_count_as_held(world, monkeypatch):
    serve(monkeypatch, Service(cached={"a" * 40: {"name": "x"}}))
    found = [addons.Found(info_hash="a" * 40, name="A"), addons.Found(info_hash="b" * 40, name="B")]
    asyncio.run(addons._mark_torbox(found))
    assert [f.held for f in found] == [True, False]


def test_the_film_is_picked_out_of_what_torbox_holds():
    assert torbox.pick_file(FILES, None)["id"] == 2
    named = FILES + [{"id": 4, "name": "Night/Extras.Making.Of.mkv", "size": 5000}]
    assert torbox.pick_file(named, "Night.of.the.Living.Dead.1968.1080p.mkv")["id"] == 2
    assert torbox.pick_file([{"id": 1, "name": "readme.txt", "size": 9}], None) is None


def test_the_magnet_carries_the_addon_trackers(world):
    _, _, torrent, _ = world
    link = torbox.magnet(torrent)
    assert link.startswith("magnet:?xt=urn:btih:" + "c" * 40)
    assert "tr=udp%3A%2F%2Ftracker.example%3A1337%2Fannounce" in link


def test_an_addon_film_goes_to_torbox_first(world, monkeypatch):
    session, download, torrent, _ = world
    session.delete(download)
    session.commit()
    service = Service()
    serve(monkeypatch, service)
    started = []
    monkeypatch.setattr(linkfetch, "start", lambda download_id: started.append(download_id))
    made = asyncio.run(downloads.request_download(session, torrent.id))
    assert made.link == "torbox:42" and started == [made.id]


def test_when_torbox_refuses_the_other_ways_are_tried(world, monkeypatch):
    session, download, torrent, _ = world
    session.delete(download)
    session.commit()

    async def add(t):
        raise torbox.TorboxError("ACTIVE_LIMIT")

    async def fetch(torrent_id):
        raise downloads.DownloadError("no swarm in a test")

    monkeypatch.setattr(torbox, "add", add)
    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.request_download(session, torrent.id))


def test_cancelling_takes_it_off_torbox(world, monkeypatch):
    session, download, *_ = world
    service = Service()
    serve(monkeypatch, service)
    monkeypatch.setattr(linkfetch, "stop", lambda download_id: None)
    monkeypatch.setattr(linkfetch, "remove_files", lambda download_id: None)
    asyncio.run(downloads.cancel_download(session, download.id))
    assert service.deleted()
