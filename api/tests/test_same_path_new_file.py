from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.routers import player  # noqa: E402
from vibestream.services import live, mediainfo  # noqa: E402


def test_the_init_segment_is_made_again_for_a_new_file(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "INIT_ROOT", str(tmp_path / "init"))
    source = tmp_path / "Film (2010).mkv"
    source.write_bytes(b"old release")
    made: list[bytes] = []

    class Proc:
        returncode = 0

        def __init__(self, content):
            self.content = content

        async def communicate(self):
            folder = live._init_path(str(source), 1) + ".work"
            with open(os.path.join(folder, "init.mp4"), "wb") as fh:
                fh.write(self.content)
            return b"", b""

    async def run(*_args, **_kwargs):
        content = b"init of " + source.read_bytes()
        made.append(content)
        return Proc(content)

    monkeypatch.setattr(live.asyncio, "create_subprocess_exec", run)

    first = asyncio.run(live.init_file(str(source), 1))
    assert open(first, "rb").read() == b"init of old release"
    asyncio.run(live.init_file(str(source), 1))
    assert len(made) == 1

    source.unlink()
    source.write_bytes(b"new release, other codecs")
    again = asyncio.run(live.init_file(str(source), 1))
    assert open(again, "rb").read() == b"init of new release, other codecs"
    assert len(made) == 2

    live.clear_init(str(source))
    assert not os.path.exists(again) and not os.path.exists(again + ".src")


def test_the_probe_is_asked_again_for_a_new_file(monkeypatch, tmp_path):
    monkeypatch.setattr(player, "_info_cache", {})
    source = tmp_path / "Film (2010).mkv"
    source.write_bytes(b"old")
    probes: list[bytes] = []

    async def probe(path):
        probes.append(open(path, "rb").read())
        return probes[-1]

    monkeypatch.setattr(mediainfo, "probe", probe)
    assert asyncio.run(player._info(str(source))) == b"old"
    assert asyncio.run(player._info(str(source))) == b"old"
    source.unlink()
    source.write_bytes(b"newer")
    assert asyncio.run(player._info(str(source))) == b"newer"
    assert probes == [b"old", b"newer"]
