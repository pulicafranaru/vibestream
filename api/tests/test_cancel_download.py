from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Episode, Media, Season, Torrent, utcnow  # noqa: E402
from vibestream.services import downloads, library, reaper  # noqa: E402

from .test_episode_downloads import FakeQbit  # noqa: E402


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    patched = dataclasses.replace(downloads.settings, shows_dir=str(tmp_path / "Shows"),
                                  movies_dir=str(tmp_path / "Movies"))
    monkeypatch.setattr(downloads, "settings", patched)
    monkeypatch.setattr(library, "settings", patched)
    monkeypatch.setattr(downloads, "QbitClient", FakeQbit)
    monkeypatch.setattr(downloads, "record_event", lambda *a, **k: None)
    forgotten: list[str] = []
    monkeypatch.setattr(downloads, "_forget_artefacts", forgotten.append)
    FakeQbit.calls = []
    yield session, tmp_path, forgotten
    session.close()


def two_episodes(session, tmp_path):
    media = Media(title="Show", media_type="tv")
    session.add(media)
    session.flush()
    season = Season(media_id=media.id, number=1)
    session.add(season)
    session.flush()
    folder = tmp_path / "Shows" / "Show" / "Season 01"
    folder.mkdir(parents=True)
    rows = []
    for number in (1, 2):
        name = f"Show.S01E0{number}.1080p.mkv"
        save = tmp_path / "downloads" / name
        save.parent.mkdir(exist_ok=True)
        save.write_bytes(b"x" * number)
        (folder / name).hardlink_to(save)
        (folder / f"Show.S01E0{number}.1080p.en.srt").write_text("subs")
        episode = Episode(media_id=media.id, season_id=season.id, season_number=1,
                          number=number, file_path=str(folder / name), prepared_at=utcnow())
        session.add(episode)
        session.add(Torrent(id=number, name=name, media_id=media.id, season=1, episode=number))
        download = Download(torrent_id=number, state="linked", info_hash=f"{number:040d}",
                            library_path=str(folder), content_path=str(save),
                            save_path=str(save.parent))
        session.add(download)
        session.flush()
        episode.download_id = download.id
        rows.append((download, episode, folder / name))
    session.commit()
    return folder, rows


def test_deleting_one_episode_keeps_the_other_in_the_shared_folder(world):
    session, tmp_path, forgotten = world
    folder, [(first, ep1, file1), (second, ep2, file2)] = two_episodes(session, tmp_path)

    asyncio.run(downloads.cancel_download(session, first.id))

    assert not file1.exists()
    assert not (folder / "Show.S01E01.1080p.en.srt").exists()
    assert file2.exists() and (folder / "Show.S01E02.1080p.en.srt").exists()
    assert ep2.download_id == second.id and ep2.file_path == str(file2)
    assert ep1.download_id is None and ep1.file_path is None
    # The episode's rendition was forgotten by the path it was built from,
    # worked out before the file went.
    assert str(file1) in forgotten
    assert str(file2) not in forgotten

    asyncio.run(downloads.cancel_download(session, second.id))
    assert not folder.exists()
    assert not folder.parent.exists()
    assert (tmp_path / "Shows").exists()       # never the root


def test_a_film_goes_with_its_folder(world):
    session, tmp_path, forgotten = world
    media = Media(title="Film", year=2010, media_type="movie")
    session.add(media)
    session.flush()
    save = tmp_path / "downloads" / "Film.2010.1080p.mkv"
    save.parent.mkdir()
    save.write_bytes(b"film")
    folder = tmp_path / "Movies" / "Film (2010)"
    folder.mkdir(parents=True)
    (folder / "Film (2010).mkv").hardlink_to(save)
    session.add(Torrent(id=9, name="Film.2010.1080p", media_id=media.id))
    download = Download(torrent_id=9, state="linked", info_hash="9" * 40,
                        library_path=str(folder), content_path=str(save))
    session.add(download)
    session.commit()

    asyncio.run(downloads.cancel_download(session, download.id))
    assert not folder.exists()
    assert str(folder / "Film (2010).mkv") in forgotten


def test_a_removed_source_is_forgotten_with_the_download(world):
    session, tmp_path, _forgotten = world
    _folder, [(first, ep1, _file1), _] = two_episodes(session, tmp_path)
    first.source_removed_at = utcnow()
    first.play_path = "/somewhere/old.mkv"
    ep1.source_removed_at = utcnow()
    session.commit()

    asyncio.run(downloads.cancel_download(session, first.id))
    assert first.source_removed_at is None and first.play_path is None
    assert ep1.source_removed_at is None


def test_asking_again_after_a_removed_source_fetches_afresh(world, monkeypatch):
    from .test_release_gone import FILM

    session, _tmp_path, _forgotten = world

    async def fetch(_torrent_id):
        return FILM

    monkeypatch.setattr(downloads, "fetch_torrent_bytes", fetch)
    media = Media(title="Film", media_type="movie")
    session.add(media)
    session.flush()
    session.add(Torrent(id=5, name="Film.2010.1080p", media_id=media.id))
    download = Download(torrent_id=5, state="removed", source_removed_at=utcnow(),
                        play_path="/old/Film.mkv", reaped_at=utcnow())
    session.add(download)
    session.commit()

    asyncio.run(downloads.request_download(session, 5))
    assert download.state == "downloading"
    assert download.source_removed_at is None and download.play_path is None


def test_the_reaper_forgets_what_it_removes(world, monkeypatch):
    session, tmp_path, forgotten = world
    folder, [(first, ep1, file1), (_second, ep2, file2)] = two_episodes(session, tmp_path)

    class Client:
        async def delete(self, *_a, **_k):
            return None

        async def close(self):
            return None

    candidate = reaper.Candidate(download=first, reason="watched", bytes_freed=1,
                                 last_played=utcnow() - timedelta(days=30))
    monkeypatch.setattr(reaper, "find_candidates", lambda *_a, **_k: ([candidate], []))
    monkeypatch.setattr(reaper, "QbitClient", Client)
    monkeypatch.setattr(reaper, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(reaper.library, "free_bytes", lambda *_a: 10 ** 12)

    asyncio.run(reaper.run_reaper(session, dry_run=False))
    assert first.state == "removed" and first.reaped_at is not None
    assert ep1.file_path is None and ep1.prepared_at is None
    assert str(file1) in forgotten
    assert not file1.exists() and file2.exists()
    assert ep2.file_path == str(file2)


def test_publishing_links_off_the_event_loop(world, monkeypatch):
    """Copying when hardlinking fails must not block the event loop."""
    import threading
    from types import SimpleNamespace

    session, tmp_path, _forgotten = world
    media = Media(title="Film", year=2010, media_type="movie")
    session.add(media)
    session.flush()
    save = tmp_path / "downloads" / "Film.2010.1080p.mkv"
    save.parent.mkdir()
    save.write_bytes(b"film")
    session.add(Torrent(id=9, name="Film.2010.1080p", media_id=media.id))
    download = Download(torrent_id=9, state="completed", content_path=str(save))
    session.add(download)
    session.commit()

    threads = []
    real = library._link_or_copy

    def link(src, dst):
        threads.append(threading.get_ident())
        return real(src, dst)

    monkeypatch.setattr(library, "_link_or_copy", link)
    monkeypatch.setattr(downloads, "preparation", lambda: SimpleNamespace(start=lambda _id: None))

    async def run():
        outcome = await downloads.publish(session, download, "Film")
        return outcome, threading.get_ident()

    outcome, loop_thread = asyncio.run(run())
    assert outcome == "published"
    assert threads and loop_thread not in threads
    assert (tmp_path / "Movies" / "Film (2010)" / "Film (2010).mkv").exists()
    assert download.library_path == str(tmp_path / "Movies" / "Film (2010)")
