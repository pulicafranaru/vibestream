from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Media, Torrent  # noqa: E402
from vibestream.services import (  # noqa: E402
    downloads, hls, mediainfo, sources, streaming, subtitles, trickplay,
)
from tests.test_episode_downloads import FILES, FakeQbit, world  # noqa: E402,F401

PROBE = {
    "format": {"duration": "60.0", "format_name": "matroska", "bit_rate": "8000000"},
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
        {"index": 1, "codec_type": "audio", "codec_name": "eac3", "channels": 6,
         "tags": {"language": "eng"}, "disposition": {"default": 1}},
        {"index": 2, "codec_type": "subtitle", "codec_name": "subrip",
         "tags": {"language": "eng"}},
    ],
}


@pytest.fixture
def caches(monkeypatch, tmp_path):
    monkeypatch.setattr(hls, "CACHE_ROOT", str(tmp_path / "hls"))
    monkeypatch.setattr(trickplay, "CACHE_ROOT", str(tmp_path / "thumbs"))
    monkeypatch.setattr(subtitles, "CACHE_DIR", str(tmp_path / "subs"))
    monkeypatch.setattr(mediainfo, "PROBE_CACHE", str(tmp_path / "probe"))
    monkeypatch.setattr(sources, "record_event", lambda *a, **k: None)
    return tmp_path


def build(path: str, probe: dict = PROBE, subs: bool = True) -> None:
    playlist = hls.playlist_path_for(path, None)
    os.makedirs(os.path.dirname(playlist), exist_ok=True)
    Path(playlist).write_text("#EXTM3U\n#EXT-X-ENDLIST\n")
    manifest = trickplay.manifest_path_for(path)
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    Path(manifest).write_text("{}")
    os.makedirs(mediainfo.PROBE_CACHE, exist_ok=True)
    Path(mediainfo._probe_cache_path(path)).write_text(json.dumps(probe))
    if subs:
        target = subtitles.embedded_target(path, 2)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        Path(target).write_text("WEBVTT\n\n")


@pytest.fixture
def film(caches, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="Film", media_type="movie")
    session.add(media)
    session.flush()
    session.add(Torrent(id=5, name="Film.2020.1080p", media_id=media.id, size_bytes=10))
    library = caches / "library" / "Film (2020)"
    library.mkdir(parents=True)
    path = str(library / "Film.mkv")
    Path(path).write_bytes(b"x" * 4096)
    download = Download(torrent_id=5, info_hash="abc", state="linked",
                        library_path=str(library), prepared_at=downloads.utcnow())
    session.add(download)
    session.commit()
    FakeQbit.calls = []
    monkeypatch.setattr("vibestream.services.qbit.QbitClient", FakeQbit)
    yield session, download, path
    session.close()


def run(coro):
    return asyncio.run(coro)


def test_waits_for_seeding_unless_forced(film):
    session, download, path = film
    build(path)
    assert run(sources.removable(session, download))
    with pytest.raises(downloads.DownloadError, match="still seeding"):
        run(sources.remove_source(session, download))
    assert os.path.exists(path)


def test_a_seeded_source_goes_and_the_title_still_plays(film):
    session, download, path = film
    build(path)
    download.seeding_seconds = 48 * 3600
    session.commit()

    freed = run(sources.remove_source(session, download))

    assert freed == 4096
    assert not os.path.exists(path)
    assert ("delete", True) in FakeQbit.calls
    assert download.source_removed_at is not None and download.play_path == path
    assert streaming.canonical_path(download) == path
    info = run(mediainfo.probe(path))
    assert info.duration == 60.0 and [a.index for a in info.audio] == [1]
    assert subtitles.all_extracted(info)


def test_nothing_goes_while_something_was_not_kept(film):
    session, download, path = film
    build(path, subs=False)
    download.seeding_seconds = 48 * 3600
    session.commit()
    assert not run(sources.removable(session, download))
    assert run(sources.remove_finished(session)) == {"removed": 0, "freed_bytes": 0}
    assert os.path.exists(path)


def test_finished_ones_go_on_their_own(film):
    session, download, path = film
    build(path)
    download.ratio = 1.2
    session.commit()
    assert run(sources.remove_finished(session))["removed"] == 1
    assert not os.path.exists(path)


def test_only_another_language_gets_a_rendition_of_its_own():
    info = mediainfo._parse({
        "format": {"duration": "1"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "truehd",
             "tags": {"language": "eng"}, "disposition": {"default": 1}},
            {"index": 2, "codec_type": "audio", "codec_name": "ac3", "tags": {"language": "eng"}},
            {"index": 3, "codec_type": "audio", "codec_name": "ac3",
             "tags": {"language": "ger", "title": "Commentary"}},
            {"index": 4, "codec_type": "audio", "codec_name": "ac3", "tags": {"language": "ger"}},
        ],
    }, "/x.mkv")
    assert hls.extra_audio(info) == [4]
    assert hls.kept_audio(info) == [1, 4]


def test_a_track_never_built_is_not_built_from_a_missing_source(caches):
    info = mediainfo._parse(PROBE, str(caches / "gone.mkv"))
    build(info.path)
    session = run(hls.ensure_session(info, 1))
    assert session.complete and session.audio_index is None
    with pytest.raises(hls.SourceGone):
        run(hls.ensure_session(info, 7))


def test_low_space_says_what_removing_sources_would_free(film, monkeypatch):
    session, download, path = film
    build(path)
    download.seeding_seconds = 48 * 3600
    session.commit()
    monkeypatch.setattr(sources, "free_bytes", lambda: 50 * 1024 ** 3)
    shortfall = run(sources.space_check(session, 20 * 1024 ** 3))
    assert shortfall["code"] == "low_space" and shortfall["fits"]
    assert shortfall["removable_seeded"] == {"count": 1, "bytes": 4096}
    monkeypatch.setattr(sources, "free_bytes", lambda: 900 * 1024 ** 3)
    assert run(sources.space_check(session, 20 * 1024 ** 3)) is None


def test_more_of_a_pack_after_its_source_went_fetches_only_the_new_episode(world):
    session, torrent, eps = world
    download = Download(torrent_id=torrent.id, info_hash="old", state="linked",
                        library_path="/library/Show/Season 01",
                        source_removed_at=downloads.utcnow(),
                        prepared_at=downloads.utcnow())
    session.add(download)
    session.flush()
    eps[0].download_id = download.id
    eps[0].file_path = "/library/Show/Season 01/Show.S01E01.Pilot.1080p.WEB-DL.mkv"
    eps[0].source_removed_at = downloads.utcnow()
    session.commit()

    again = run(downloads.request_download(session, torrent.id, episode_id=eps[1].id))

    assert again.id == download.id and again.source_removed_at is None
    assert again.state == "downloading" and again.prepared_at is None
    assert json.loads(again.wanted_files) == [FILES[1]]
    assert FakeQbit.calls[0] == ("add", True)
    assert eps[0].source_removed_at is not None


def test_deleting_an_episode_whose_source_went_touches_no_torrent(world, caches):
    session, torrent, eps = world
    download = Download(torrent_id=torrent.id, info_hash="old", state="linked",
                        source_removed_at=downloads.utcnow())
    session.add(download)
    session.flush()
    for episode in eps[:2]:
        episode.download_id = download.id
        episode.file_path = f"/library/{episode.number}.mkv"
        episode.source_removed_at = downloads.utcnow()
    session.commit()

    run(downloads.remove_episode(session, download.id, eps[0].id))

    assert eps[0].file_path is None and eps[1].file_path is not None
    assert FakeQbit.calls == []
    assert download.state == "linked"


def test_usage_counts_a_hardlinked_file_once(tmp_path):
    from vibestream.services import sources

    downloads, library = tmp_path / "downloads", tmp_path / "library"
    downloads.mkdir()
    library.mkdir()
    (downloads / "film.mkv").write_bytes(b"x" * 100_000)
    os.link(downloads / "film.mkv", library / "film.mkv")
    seen: set = set()
    once = sources._allocated(str(downloads), seen)
    assert once >= 100_000
    assert sources._allocated(str(library), seen) == 0


def test_the_source_is_marked_removed_before_its_torrent_goes(film, monkeypatch):
    session, download, path = film
    build(path)
    download.seeding_seconds = 48 * 3600
    session.commit()
    seen = []

    async def delete(self, info_hash, delete_files=True):
        seen.append(download.source_removed_at is not None and download not in session.dirty)

    monkeypatch.setattr(FakeQbit, "delete", delete)
    run(sources.remove_source(session, download))
    assert seen == [True]
