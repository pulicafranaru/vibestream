"""Renditions stay the default unless the live engine is switched on."""

from __future__ import annotations

import os
import re
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibestream import livecheck
from vibestream.db import get_session
from vibestream.routers import player
from vibestream.services import hls, live, mediainfo

from .test_live import clips, scratch  # noqa: F401  (fixtures)


def _settings(engine="renditions", trial=()):
    return SimpleNamespace(playback_engine=engine, live_trial=list(trial))


@pytest.fixture
def api(monkeypatch, clips):  # noqa: F811
    paths = {"7": clips["mkv"], "e9": clips["hevc"], "8": "/nowhere/gone.mkv"}

    def load(_session, play_id):
        if play_id not in paths:
            raise player.HTTPException(404, "unknown")
        episode = SimpleNamespace(id=int(play_id[1:])) if play_id.startswith("e") else None
        number = 1 if episode else int(play_id)
        return player.Target(download=SimpleNamespace(id=number, torrent=None),
                             path=paths[play_id], episode=episode)

    monkeypatch.setattr(player, "_load", load)
    monkeypatch.setattr(player, "_info_cache", {})
    app = FastAPI()
    app.include_router(player.router)
    app.dependency_overrides[get_session] = lambda: None
    with TestClient(app) as client:
        yield client
    live.reset_state()


class FakeRendition:
    complete = True
    error = None

    def __init__(self, folder):
        self.playlist_path = os.path.join(folder, "index.m3u8")
        with open(self.playlist_path, "w") as fh:
            fh.write("#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:6.0,\nseg00000.m4s\n#EXT-X-ENDLIST\n")

    def progress(self):
        return {"ready": True, "percent": 100.0}


@pytest.fixture
def rendition(monkeypatch, tmp_path):
    made = FakeRendition(str(tmp_path))
    calls = []

    async def ensure(info, audio):
        calls.append((info.path, audio))
        return made

    monkeypatch.setattr(hls, "ensure_session", ensure)
    monkeypatch.setattr(hls, "peek_session", lambda info, audio: made)
    return calls


def test_renditions_are_the_default_and_nothing_live_happens(api, rendition, monkeypatch):
    monkeypatch.setattr(live, "settings", _settings())
    body = api.get("/api/play/7/index.m3u8").text
    assert "/api/play/7/seg00000.m4s" in body and "/live/" not in body
    assert api.get("/api/play/7/prepare").json()["ready"] is True
    assert rendition and not live.has_index(clips_path(api))


def clips_path(_api):
    return player._load(None, "7").path


def _wait_ready(api, play_id):
    for _ in range(200):
        state = api.get(f"/api/play/{play_id}/prepare").json()
        if state["ready"]:
            return state
        time.sleep(0.05)
    raise AssertionError(f"never ready: {state}")


def test_a_trial_title_plays_live_and_every_segment_is_the_source(api, rendition, monkeypatch, clips):  # noqa: F811
    monkeypatch.setattr(live, "settings", _settings(trial=["7"]))
    monkeypatch.setattr(hls, "peek_session", lambda info, audio: None)
    first = api.get("/api/play/7/prepare").json()
    assert first["ready"] is False
    _wait_ready(api, "7")

    body = api.get("/api/play/7/index.m3u8").text
    assert body.startswith("#EXTM3U") and body.rstrip().endswith("#EXT-X-ENDLIST")
    init_url = re.search(r'URI="([^"]+)"', body).group(1)
    urls = [line for line in body.splitlines() if line.endswith(".m4s")]
    assert init_url.startswith("/api/play/7/live/") and urls[0].startswith("/api/play/7/live/")
    assert rendition == []

    init = api.get(init_url)
    assert init.status_code == 200
    index = live.load_index(clips["mkv"])
    segments = live.plan(index)
    assert len(urls) == len(segments)
    for n in [0, 1, 2, len(urls) - 1, 3]:
        reply = api.get(urls[n])
        assert reply.status_code == 200
        assert int(reply.headers["content-length"]) == len(reply.content)
        assert livecheck.check_segment(clips["mkv"], index, segments[n],
                                       init.content + reply.content) == [], n
    token_base = urls[0].rsplit("/", 1)[0]
    assert api.get(f"{token_base}/{len(urls)}.m4s").status_code == 404
    assert api.get(f"{token_base}/x.m4s").status_code == 404


def test_other_titles_stay_on_renditions_during_a_trial(api, rendition, monkeypatch):
    monkeypatch.setattr(live, "settings", _settings(trial=["7"]))
    body = api.get("/api/play/e9/index.m3u8").text
    assert "/live/" not in body and rendition


def test_a_title_whose_source_is_gone_keeps_its_rendition(api, rendition, monkeypatch):
    monkeypatch.setattr(live, "settings", _settings(engine="live"))
    monkeypatch.setattr(mediainfo, "probe", _fake_probe)
    body = api.get("/api/play/8/index.m3u8").text
    assert "/live/" not in body and rendition


async def _fake_probe(path, timeout=60.0):
    return mediainfo.MediaInfo(path=path, duration=60.0, container="matroska", bitrate=0)


def test_the_chosen_audio_track_reaches_every_segment_url(api, rendition, monkeypatch, clips):  # noqa: F811
    monkeypatch.setattr(live, "settings", _settings(engine="live"))
    monkeypatch.setattr(hls, "peek_session", lambda info, audio: None)
    _wait_ready(api, "7")
    body = api.get("/api/play/7/index.m3u8?audio=2").text
    lines = [l for l in body.splitlines() if "/live/" in l]
    assert lines and all("?audio=2" in l for l in lines)


def test_until_the_index_exists_a_finished_rendition_still_plays(api, rendition, monkeypatch):
    monkeypatch.setattr(live, "settings", _settings(engine="live"))
    slow = []
    monkeypatch.setattr(live, "start_index", lambda path: slow.append(path))
    body = api.get("/api/play/7/index.m3u8").text
    assert "/api/play/7/seg00000.m4s" in body and slow


def test_an_audio_track_the_file_does_not_have_starts_nothing(api, rendition, monkeypatch):
    """The clip has video at 0 and audio at 1 and 2."""
    monkeypatch.setattr(live, "settings", _settings())
    for url in ("prepare", "index.m3u8", "init.mp4", "seg00000.m4s", "master.m3u8"):
        assert api.get(f"/api/play/7/{url}?audio=99").status_code == 404, url
        assert api.get(f"/api/play/7/{url}?audio=0").status_code == 404, url
    assert rendition == []
    assert api.get("/api/play/7/prepare?audio=2").status_code == 200
    assert rendition[-1][1] == 2


def test_clearing_a_file_takes_every_audio_rendition(monkeypatch, tmp_path):
    monkeypatch.setattr(hls, "CACHE_ROOT", str(tmp_path / "hls"))
    monkeypatch.setattr(mediainfo, "cached_info",
                        lambda _p: SimpleNamespace(audio=[SimpleNamespace(index=140)]))
    path = "/library/Film (2010)/Film (2010).mkv"
    folders = [os.path.join(hls.CACHE_ROOT, hls.cache_key(path, a)) for a in (None, 3, 23, 140)]
    other = os.path.join(hls.CACHE_ROOT, hls.cache_key("/library/Other.mkv", 3))
    for folder in [*folders, other]:
        os.makedirs(folder)
    hls.clear_for(path)
    assert not any(os.path.exists(f) for f in folders)
    assert os.path.exists(other)
