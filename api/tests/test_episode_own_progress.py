"""A pack's progress counts every wanted file, so an episode shows its own file's."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.routers import catalog  # noqa: E402
from vibestream.services import qbit  # noqa: E402

FILES = [
    {"name": "Show.S01/Show.S01E01.1080p.mkv", "size": 1000, "progress": 1.0, "priority": 1},
    {"name": "Show.S01/Show.S01E02.1080p.mkv", "size": 1000, "progress": 0.25, "priority": 1},
    {"name": "Show.S01/Show.S01E02.1080p.en.srt", "size": 10, "progress": 1.0, "priority": 1},
    {"name": "Show.S01/Show.S01E03.1080p.mkv", "size": 1000, "progress": 0.0, "priority": 0},
]


def episode(number, id=None):
    return SimpleNamespace(id=id or number, season_number=1, number=number)


def test_the_percent_is_the_episodes_own_file():
    assert catalog.episode_file_percent(episode(2), FILES) == 25.0
    assert catalog.episode_file_percent(episode(1), FILES) == 100.0
    assert catalog.episode_file_percent(episode(9), FILES) is None


def test_a_pack_at_100_shows_the_new_episode_at_its_own_progress(monkeypatch):
    class FakeQbit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def files(self, info_hash):
            assert info_hash == "abc"
            return FILES

    monkeypatch.setattr(qbit, "QbitClient", FakeQbit)
    pack = SimpleNamespace(id=7, info_hash="abc", torrent=SimpleNamespace(episode=None))
    payloads = [
        {"id": 1, "available": True, "download": {"id": 7, "state": "downloading", "percent": 100.0}},
        {"id": 2, "available": False, "download": {"id": 7, "state": "downloading", "percent": 100.0}},
    ]
    asyncio.run(catalog._own_progress([episode(1), episode(2)], payloads, {50: pack}))
    assert payloads[1]["download"]["percent"] == 25.0
    assert payloads[1]["download"]["progress"] == 0.25
    assert payloads[0]["download"]["percent"] == 100.0
