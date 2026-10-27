"""Switching engines both ways: live never removes a source, since renditions are built from them."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from vibestream.services import live, preparation, sources

from .test_live import clips, scratch  # noqa: F401  (fixtures)


def _engine(monkeypatch, engine):
    monkeypatch.setattr(live, "settings", SimpleNamespace(playback_engine=engine, live_trial=[]))


def test_ready_means_indexed_live_and_rendered_otherwise(monkeypatch, clips):  # noqa: F811
    path = clips["mkv"]
    asyncio.run(live.build_index(path))
    _engine(monkeypatch, "live")
    assert preparation.artefacts_ready(path)
    _engine(monkeypatch, "renditions")
    assert not preparation.artefacts_ready(path)


def test_a_file_without_its_source_needs_its_rendition_even_live(monkeypatch, tmp_path):
    _engine(monkeypatch, "live")
    assert not preparation.artefacts_ready(str(tmp_path / "gone.mkv"))


def test_live_never_removes_a_source(monkeypatch):
    download = SimpleNamespace(source_removed_at=None, prepared_at=object(), state="seeding")
    _engine(monkeypatch, "live")
    assert asyncio.run(sources.removable(None, download)) is False


def test_space_is_planned_for_one_copy_live_and_two_otherwise(monkeypatch):
    torrent = SimpleNamespace(size_bytes=10)
    _engine(monkeypatch, "live")
    assert sources.cost_of(torrent) == 10
    _engine(monkeypatch, "renditions")
    assert sources.cost_of(torrent) == 20


def test_live_builds_no_rendition_for_other_languages(monkeypatch):
    built = []

    async def ensure(info, index):
        built.append(index)

    async def extract_all(info):
        return None

    monkeypatch.setattr(sources.hls, "ensure_session", ensure)
    monkeypatch.setattr(sources.hls, "extra_audio", lambda info: [3, 4])
    monkeypatch.setattr(sources.subtitles, "extract_all", extract_all)
    _engine(monkeypatch, "live")
    assert asyncio.run(sources.build_extras(SimpleNamespace(path="x"))) is None
    assert built == []


def test_the_backlog_moves_past_a_file_it_cannot_index(monkeypatch, tmp_path):
    bad, good = tmp_path / "bad.mkv", tmp_path / "good.mkv"
    bad.write_bytes(b"x")
    good.write_bytes(b"x")
    tried = []

    async def build(path):
        tried.append(path)
        if path == str(bad):
            raise live.LiveError("no keyframes")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def scalars(self, _query):
            return [object()]

    monkeypatch.setattr(preparation, "session_scope", Session)
    monkeypatch.setattr(preparation, "targets_for", lambda s, d: [(None, str(bad)), (None, str(good))])
    monkeypatch.setattr(preparation.live, "has_index", lambda path: path in tried and path == str(good))
    monkeypatch.setattr(preparation.live, "build_index", build)
    monkeypatch.setattr(preparation, "_unindexable", set())
    for _ in range(3):
        asyncio.run(preparation.index_backlog())
    assert tried == [str(bad), str(good)]
