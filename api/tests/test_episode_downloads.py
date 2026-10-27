"""qBittorrent is replaced by a recorder and the tracker by a .torrent built here."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Episode, Media, Season, Torrent  # noqa: E402
from vibestream.schemas import download_summary  # noqa: E402
from vibestream.services import downloads, library, shows  # noqa: E402
from vibestream.services.qbit import QbitNotFound  # noqa: E402

FILES = [
    "Show.S01E01.Pilot.1080p.WEB-DL.mkv",
    "Show.S01E02.Second.1080p.WEB-DL.mkv",
    "Show.S01E03.Third.1080p.WEB-DL.mkv",
    "Sample/show.sample.mkv",
    "Show.S01E02.Second.1080p.WEB-DL.en.srt",
]


def bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in items) + b"e"
    raise TypeError(value)


TORRENT = bencode({
    "announce": "http://tracker.invalid/announce",
    "info": {
        "name": "Show.S01.1080p.WEB-DL",
        "piece length": 262144,
        "pieces": b"\x00" * 20,
        "files": [{"length": 1000 + i, "path": p.split("/")} for i, p in enumerate(FILES)],
    },
})


class FakeQbit:
    calls: list[tuple] = []
    priorities: dict[int, int] = {}
    progress: dict[int, float] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def add_torrent_file(self, content, **kwargs):
        FakeQbit.calls.append(("add", kwargs.get("paused")))
        FakeQbit.priorities = {i: 1 for i in range(len(FILES))}
        return None

    async def files(self, info_hash):
        return [
            {"index": i, "name": f"Show.S01.1080p.WEB-DL/{p}",
             "priority": FakeQbit.priorities.get(i, 1),
             "progress": FakeQbit.progress.get(i, 0.0)}
            for i, p in enumerate(FILES)
        ]

    async def set_file_priority(self, info_hash, indexes, priority):
        for i in indexes:
            FakeQbit.priorities[i] = priority
        FakeQbit.calls.append(("prio", tuple(indexes), priority))

    async def resume(self, info_hash):
        FakeQbit.calls.append(("resume",))

    async def recheck(self, info_hash):
        FakeQbit.calls.append(("recheck",))

    async def delete(self, info_hash, delete_files=True):
        FakeQbit.calls.append(("delete", delete_files))


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="Show", media_type="tv")
    session.add(media)
    session.flush()
    season = Season(media_id=media.id, number=1)
    session.add(season)
    session.flush()
    eps = []
    for number, name in [(1, "Pilot"), (2, "Second"), (3, "Third")]:
        ep = Episode(media_id=media.id, season_id=season.id, season_number=1,
                     number=number, name=name)
        session.add(ep)
        eps.append(ep)
    torrent = Torrent(id=777, name="Show.S01.1080p.WEB-DL", media_id=media.id,
                      season=1, episode=None, size_bytes=3_000_000_000)
    session.add(torrent)
    session.commit()

    async def fetch(_torrent_id):
        return TORRENT

    async def no_sync(*_args, **_kwargs):
        return None

    FakeQbit.calls = []
    FakeQbit.progress = {}
    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    monkeypatch.setattr(downloads, "cached_meta", lambda _id: None)
    monkeypatch.setattr(downloads, "QbitClient", FakeQbit)
    monkeypatch.setattr(shows, "sync_episodes", no_sync)
    monkeypatch.setattr(downloads, "record_event", lambda *a, **k: None)
    yield session, torrent, eps
    session.close()


def wanted_indexes():
    return sorted(i for i, p in FakeQbit.priorities.items() if p > 0)


def test_one_episode_fetches_only_its_file(world):
    session, torrent, eps = world
    download = asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[1].id))
    assert FakeQbit.calls[0] == ("add", True)
    assert FakeQbit.calls[-1] == ("resume",)
    assert wanted_indexes() == [1, 4]
    assert json.loads(download.wanted_files) == [FILES[1]]
    assert download.primary_file == FILES[1]
    assert download_summary(download)["episodes"] == ["S1:E2"]


def test_a_torrent_not_registered_yet_is_waited_for(world, monkeypatch):
    """Asked for its files at once, qBittorrent answers 404 for the new hash."""
    session, torrent, eps = world
    listed = FakeQbit.files
    unknown = {"left": 2}

    async def not_yet(self, info_hash):
        if unknown["left"]:
            unknown["left"] -= 1
            raise QbitNotFound("qBittorrent endpoint not found: /api/v2/torrents/files")
        return await listed(self, info_hash)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(FakeQbit, "files", not_yet)
    monkeypatch.setattr(downloads.asyncio, "sleep", no_wait)
    download = asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[1].id))
    assert unknown["left"] == 0
    assert wanted_indexes() == [1, 4]
    assert FakeQbit.calls[-1] == ("resume",)
    assert download.state != "error"


def test_a_second_episode_joins_the_same_torrent(world):
    session, torrent, eps = world
    first = asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[1].id))
    first.state = "linked"
    first.prepared_at = first.wanted_at
    session.commit()
    again = asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[2].id))
    assert again.id == first.id
    assert wanted_indexes() == [1, 2, 4]
    assert again.state == "downloading" and again.prepared_at is None
    assert download_summary(again)["episodes"] == ["S1:E2", "S1:E3"]


def test_asking_for_the_whole_season_wants_everything(world):
    session, torrent, eps = world
    asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[0].id))
    whole = asyncio.run(downloads.request_download(session, torrent.id, everything=True))
    assert whole.wanted_files is None
    assert wanted_indexes() == [0, 1, 2, 3, 4]
    assert download_summary(whole)["episodes"] is None


def test_a_plain_request_on_a_partial_pack_changes_nothing(world):
    session, torrent, eps = world
    asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[0].id))
    calls = len(FakeQbit.calls)
    asyncio.run(downloads.request_download(session, torrent.id))
    assert len(FakeQbit.calls) == calls and wanted_indexes() == [0]


def test_an_episode_from_another_show_is_refused(world):
    session, torrent, eps = world
    other = Media(title="Other", media_type="tv")
    session.add(other)
    session.flush()
    stranger = Episode(media_id=other.id, season_id=eps[0].season_id, season_number=1,
                       number=1, name="x")
    session.add(stranger)
    session.commit()
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.request_download(session, torrent.id, episode_id=stranger.id))


@pytest.fixture
def held(world, monkeypatch, tmp_path):
    import dataclasses

    session, torrent, eps = world
    shows_dir = tmp_path / "Shows"
    season_dir = shows_dir / "Show" / "Season 01"
    season_dir.mkdir(parents=True)
    save = tmp_path / "downloads"
    (save / "Show.S01.1080p.WEB-DL").mkdir(parents=True)
    patched = dataclasses.replace(downloads.settings, shows_dir=str(shows_dir))
    monkeypatch.setattr(downloads, "settings", patched)
    monkeypatch.setattr(library, "settings", patched)

    asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[0].id))
    download = asyncio.run(
        downloads.request_download(session, torrent.id, episode_id=eps[1].id)
    )
    for index in (0, 1):
        name = FILES[index]
        (save / "Show.S01.1080p.WEB-DL" / name).write_bytes(b"x" * (1000 + index))
        (season_dir / name).write_bytes(b"x" * (1000 + index))
        FakeQbit.progress[index] = 1.0
        ep = eps[index]
        ep.download_id = download.id
        ep.file_path = str(season_dir / name)
        ep.prepared_at = download.wanted_at
    (season_dir / FILES[4]).write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    download.state = "linked"
    download.library_path = str(season_dir)
    download.save_path = str(save)
    download.content_path = str(save / "Show.S01.1080p.WEB-DL")
    download.prepared_at = download.wanted_at
    session.commit()
    return session, torrent, eps, download, season_dir, save


def test_deleting_one_episode_keeps_the_others(held):
    session, torrent, eps, download, season_dir, save = held
    asyncio.run(downloads.remove_episode(session, download.id, eps[1].id))

    assert not (season_dir / FILES[1]).exists()
    assert not (season_dir / FILES[4]).exists()
    assert (season_dir / FILES[0]).exists()
    assert eps[1].download_id is None and eps[1].prepared_at is None
    assert eps[0].download_id == download.id
    assert json.loads(download.wanted_files) == [FILES[0]]
    assert wanted_indexes() == [0]
    assert FakeQbit.calls[-1] == ("recheck",)
    assert download.state == "linked"
    summary = download_summary(download)
    assert summary["episodes"] == ["S1:E1"] and summary["playable"]


def test_deleting_the_last_episode_deletes_the_download(held):
    session, torrent, eps, download, season_dir, save = held
    asyncio.run(downloads.remove_episode(session, download.id, eps[1].id))
    asyncio.run(downloads.remove_episode(session, download.id, eps[0].id))
    assert download.state == "removed"
    assert ("delete", True) in FakeQbit.calls


def test_a_release_of_one_episode_is_deleted_by_that_episode(world):
    session, _pack, eps = world
    single = Torrent(id=778, name="Show.S01E03.1080p.WEB-DL", media_id=eps[2].media_id,
                     season=1, episode=3, size_bytes=1_000_000_000)
    download = Download(torrent_id=778, state="linked", info_hash="ab" * 20)
    session.add_all([single, download])
    session.flush()
    eps[2].download_id = download.id
    session.commit()
    asyncio.run(downloads.remove_episode(session, download.id, eps[2].id))
    assert download.state == "removed"
    assert ("delete", True) in FakeQbit.calls


def test_another_episode_cannot_delete_a_release_of_one(world):
    session, _pack, eps = world
    single = Torrent(id=779, name="Show.S01E03.1080p.WEB-DL", media_id=eps[2].media_id,
                     season=1, episode=3, size_bytes=1_000_000_000)
    download = Download(torrent_id=779, state="linked", info_hash="cd" * 20)
    session.add_all([single, download])
    session.commit()
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.remove_episode(session, download.id, eps[0].id))
    assert download.state == "linked"


def test_a_whole_pack_can_lose_one_episode(held):
    session, torrent, eps, download, season_dir, save = held
    download.wanted_files = None
    session.commit()
    asyncio.run(downloads.remove_episode(session, download.id, eps[2].id))
    assert sorted(json.loads(download.wanted_files)) == sorted([FILES[0], FILES[1]])
    assert download_summary(download)["episodes"] == ["S1:E1", "S1:E2"]


def test_a_pack_fetching_one_more_episode_stays_in_the_library(held):
    session, torrent, eps, download, season_dir, save = held
    download.state = "downloading"
    download.prepared_at = None
    session.commit()
    summary = download_summary(download)
    assert summary["on_disk"] and summary["playable"]


def test_only_the_shared_pieces_are_kept(tmp_path):
    from vibestream.torrentmeta import TorrentFile

    piece = 4096
    path = tmp_path / "middle.mkv"
    data = bytes(range(256)) * 160
    path.write_bytes(data)
    middle = TorrentFile(path="middle.mkv", length=len(data), offset=piece * 3 + 1000)
    downloads._keep_shared_pieces(str(path), middle, piece, piece * 100)

    after = path.read_bytes()
    assert len(after) == len(data)
    head = piece - 1000
    tail = (middle.offset + middle.length) % piece
    assert after[:head] == data[:head]
    assert after[-tail:] == data[-tail:]
    assert after[head:-tail] == b"\0" * (len(data) - head - tail)


def test_a_failure_after_the_add_takes_the_stopped_torrent_out(world, monkeypatch):
    from vibestream.services.qbit import QbitError

    session, torrent, eps = world
    real = FakeQbit.set_file_priority

    async def broken(self, info_hash, indexes, priority):
        raise QbitError("qBittorrent /torrents/filePrio returned HTTP 500")

    monkeypatch.setattr(FakeQbit, "set_file_priority", broken)
    with pytest.raises(downloads.DownloadError):
        asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[0].id))
    download = session.query(Download).one()
    assert download.state == "error" and download.error
    assert download.info_hash is None
    assert ("delete", False) in FakeQbit.calls

    monkeypatch.setattr(FakeQbit, "set_file_priority", real)
    asyncio.run(downloads.request_download(session, torrent.id, episode_id=eps[0].id))
    assert download.state == "downloading" and download.info_hash
