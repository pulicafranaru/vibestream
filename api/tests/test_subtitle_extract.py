from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services import subtitles  # noqa: E402


class FakeProc:
    def __init__(self, output: str, hang: bool, code: int = 0):
        self.output, self.hang, self.code = output, hang, code
        self.returncode = None

    async def communicate(self):
        with open(self.output, "w") as fh:
            fh.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhalf")
        if self.hang:
            await asyncio.sleep(10)
        self.returncode = self.code
        return b"", b"boom"

    def kill(self):
        self.returncode = -9


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setattr(subtitles, "CACHE_DIR", str(tmp_path / "subs"))
    path = tmp_path / "Film.mkv"
    path.write_bytes(b"x")
    return str(path)


def fake_ffmpeg(monkeypatch, hang: bool, code: int = 0):
    async def run(*args, **_kwargs):
        return FakeProc(args[-1], hang, code)

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", run)


def test_an_interrupted_extraction_leaves_nothing_behind(monkeypatch, source):
    fake_ffmpeg(monkeypatch, hang=True)
    target = subtitles.embedded_target(source, 3)
    with pytest.raises(subtitles.SubtitleError):
        asyncio.run(subtitles.extract_embedded(source, 3, timeout=0.05))
    assert not os.path.exists(target)
    assert not os.path.exists(target + ".part")


def test_a_failed_extraction_leaves_nothing_behind(monkeypatch, source):
    fake_ffmpeg(monkeypatch, hang=False, code=1)
    target = subtitles.embedded_target(source, 3)
    with pytest.raises(subtitles.SubtitleError):
        asyncio.run(subtitles.extract_embedded(source, 3))
    assert not os.path.exists(target) and not os.path.exists(target + ".part")


def test_a_finished_extraction_is_kept(monkeypatch, source):
    fake_ffmpeg(monkeypatch, hang=False)
    target = asyncio.run(subtitles.extract_embedded(source, 3))
    assert target == subtitles.embedded_target(source, 3)
    assert open(target).read().startswith("WEBVTT")
    assert not os.path.exists(target + ".part")
