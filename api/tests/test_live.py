"""Live remux, compared packet by packet with the source on clips with awkward keyframes."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time

import pytest

from vibestream import livecheck
from vibestream.services import live, mediainfo

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

KEYFRAMES = "0,0.5,0.55,7,17.3,18,18.05,25,31,40.2,41,52,59,63.5,64,70"
DURATION = 75


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _video_in() -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=24000/1001:duration={DURATION}"]


def _sine(freq: int) -> list[str]:
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={DURATION}"]


X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-bf", "3", "-g", "1000",
        "-sc_threshold", "0", "-force_key_frames", KEYFRAMES]


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    folder = tmp_path_factory.mktemp("clips")
    made = {}

    made["mkv"] = str(folder / "h264.mkv")
    _ffmpeg(*_video_in(), *_sine(440), *_sine(880),
            "-map", "0:v", "-map", "1:a", "-map", "2:a", *X264,
            "-c:a:0", "ac3", "-ac:a:0", "2", "-c:a:1", "eac3", "-ac:a:1", "6",
            "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=fra",
            made["mkv"])

    made["mp4"] = str(folder / "h264.mp4")
    _ffmpeg(*_video_in(), *_sine(440), *X264, "-c:a", "aac", made["mp4"])

    made["hevc"] = str(folder / "hevc.mkv")
    _ffmpeg(*_video_in(), *_sine(440), "-c:v", "libx265", "-preset", "ultrafast",
            "-x265-params", "bframes=3:keyint=1000:scenecut=0:log-level=error",
            "-force_key_frames", KEYFRAMES, "-c:a", "aac", made["hevc"])

    made["clicks"] = str(folder / "clicks.mkv")
    _ffmpeg(*_video_in(), "-f", "lavfi", "-i",
            f"aevalsrc='if(lt(mod(t\\,1)\\,0.01)\\,0.8*sin(2*PI*1000*t)\\,0)':s=48000:d={DURATION}",
            *X264, "-c:a", "ac3", made["clicks"])

    made["silent"] = str(folder / "noaudio.mkv")
    _ffmpeg(*_video_in(), *X264, made["silent"])
    return made


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "ROOT", str(tmp_path / "live"))
    monkeypatch.setattr(live, "INIT_ROOT", str(tmp_path / "live" / "init"))
    monkeypatch.setattr(live, "STREAMS_ROOT", str(tmp_path / "live" / "streams"))
    monkeypatch.setattr(live, "PROBE_CACHE", str(tmp_path / "probe"))
    monkeypatch.setattr(mediainfo, "PROBE_CACHE", str(tmp_path / "probe"))
    live.reset_state()
    yield
    live.reset_state()


def run(scenario):
    async def wrapped():
        try:
            return await scenario()
        finally:
            await live.shutdown()
    return asyncio.run(wrapped())


async def _open(path: str, audio: int | None = None):
    index = live.load_index(path) or await live.build_index(path)
    return index, await live.stream_for(path, audio, live.new_token(), index)


def _audio_index(path: str, n: int) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.split()
    return int(out[n])


def test_keyframes_are_read_from_ffprobe_csv():
    text = "\n".join([
        "packet,pts_time=0.000000,flags=K__", "packet,pts_time=0.083000,flags=___",
        "packet,pts_time=2.002000,flags=K_", "packet,pts_time=N/A,flags=K__",
        "stream,duration=N/A", "format,start_time=0.040000,duration=61.200000",
    ])
    keyframes, duration, start = live.parse_keyframes(text)
    assert keyframes == [0.0, 2.002]
    assert duration == 61.2
    assert start == 0.04


def _index(duration, keyframes):
    return live.Index(duration=duration, keyframes=keyframes)


@pytest.mark.parametrize("duration, keyframes, target, expected", [
    # Jellyfin's own cases for ComputeSegments.
    (35.0, [0, 10.427, 20.854, 31.24], 6, [10.427, 10.427, 10.386, 3.76]),
    (10.0, [0, 1, 2, 3, 4, 5], 2, [2.0, 2.0, 6.0]),
    (10.0, [0], 6, [10.0]),
    (0.0, [10.0], 6, [10.0]),
    (9.9, [0, 5, 10], 6, [10.0]),
])
def test_segments_follow_jellyfin(duration, keyframes, target, expected):
    segments = live.plan(_index(duration, keyframes), target)
    assert [round(s.duration, 3) for s in segments] == expected


def test_segments_cover_every_piece_once():
    import random

    rng = random.Random(7)
    for _ in range(200):
        times, t = [0.0], 0.0
        for _ in range(rng.randrange(1, 300)):
            t += rng.choice([0.042, 0.5, 2.002, 4.004, 6.006, 10.427, rng.uniform(0.04, 12)])
            times.append(round(t, 3))
        duration = times[-1] + rng.uniform(-0.5, 8)
        segments = live.plan(_index(duration, times))
        assert segments[0].first == 0 and segments[-1].end == len(times)
        assert all(x.end == y.first for x, y in zip(segments, segments[1:]))
        assert all(s.duration > 0 for s in segments)
        assert abs(sum(s.duration for s in segments) - max(duration, times[-1])) < 1e-6


def test_playlist_is_complete_vod():
    index = _index(20.0, [0, 6.006, 12.012, 18.018])
    text = live.media_playlist(index, "/api/play/7/live/abc", "?audio=2")
    assert text.startswith("#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:7\n")
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text and text.endswith("#EXT-X-ENDLIST\n")
    assert '#EXT-X-MAP:URI="/api/play/7/live/abc/init.mp4?audio=2"' in text
    assert "/api/play/7/live/abc/2.m4s?audio=2" in text


def test_index_finds_the_forced_keyframes(clips):
    async def scenario():
        index = await live.build_index(clips["mkv"])
        wanted = [float(k) for k in KEYFRAMES.split(",")]
        assert len(index.keyframes) == len(wanted)
        assert all(abs(a - b) < 0.05 for a, b in zip(index.keyframes, wanted))
        assert abs(index.duration - DURATION) < 0.2
        assert live.load_index(clips["mkv"]).keyframes == index.keyframes
    run(scenario)


def test_index_goes_stale_when_the_file_changes(clips, tmp_path):
    copy = str(tmp_path / "copy.mkv")
    shutil.copy(clips["mkv"], copy)

    async def scenario():
        await live.build_index(copy)
        assert live.has_index(copy)
        with open(copy, "ab") as fh:
            fh.write(b"\0")
        assert not live.has_index(copy)
    run(scenario)


@pytest.mark.parametrize("kind", ["mkv", "mp4", "hevc", "silent"])
def test_every_segment_is_the_source_when_asked_cold(clips, kind):
    path = clips[kind]

    async def scenario():
        index = await live.build_index(path)
        segments = live.plan(index)
        assert len(segments) >= 8
        for n, segment in enumerate(segments):
            _index_, stream = await _open(path)
            data = await livecheck.fetch(stream, n)
            assert livecheck.check_segment(path, index, segment, data, kind != "silent") == []
    run(scenario)


@pytest.mark.parametrize("kind", ["mkv", "mp4", "hevc"])
def test_playing_straight_through_is_the_whole_source(clips, kind):
    path = clips[kind]

    async def scenario():
        index, stream = await _open(path)
        data = await live.init_file(path, stream.audio)
        whole = open(data, "rb").read()
        for n, segment in enumerate(stream.segments):
            piece = await livecheck.fetch(stream, n)
            assert livecheck.check_segment(path, index, segment, piece) == []
            whole += piece[os.path.getsize(data):]
        assert len(stream.runs) == 1
        served = [r[3] for r in livecheck.served_packets(whole, "v")]
        assert served == livecheck.source_video(path, index.keyframes[0], None)
        audio = livecheck.served_packets(whole, "a")
        holes = [q - p - d for (p, d, _f, _h), (q, _e, _g, _i) in zip(audio, audio[1:])
                 if q - p - d > 0.005]
        assert holes == []
        assert audio[-1][0] > index.duration - 1
    run(scenario)


def test_seeking_about_serves_the_right_film(clips):
    path = clips["mkv"]

    async def scenario():
        index, stream = await _open(path)
        segments = stream.segments
        last = len(segments) - 1
        served = {}
        for n in [0, 1, last - 1, 2, 3, last, last - 4, 1, 0, 4, 5]:
            data = await livecheck.fetch(stream, n)
            assert livecheck.check_segment(path, index, segments[n], data) == [], n
            served[n] = data
        assert len(stream.runs) >= 3
        for n in served:
            if n + 1 in served:
                assert livecheck.seam(served[n], served[n + 1]) is None, n
    run(scenario)


def test_racing_requests_get_the_same_answer(clips):
    path = clips["mkv"]

    async def scenario():
        index, stream = await _open(path)
        segments = stream.segments
        results = await asyncio.gather(
            livecheck.fetch(stream, 5), livecheck.fetch(stream, 5),
            livecheck.fetch(stream, 6), livecheck.fetch(stream, 1),
        )
        for n, data in zip([5, 5, 6, 1], results):
            assert livecheck.check_segment(path, index, segments[n], data) == [], n
    run(scenario)


def test_a_request_overtaken_by_a_seek_does_not_restart_ffmpeg(clips):
    """A request dropped on seek must give up rather than drag ffmpeg back."""
    path = clips["mkv"]

    async def scenario():
        _index, stream = await _open(path)
        last = len(stream.segments) - 1
        old = asyncio.create_task(live.segment_files(stream, last))
        await asyncio.sleep(0)
        while not stream.runs:
            await asyncio.sleep(0.01)
        newer = await live.segment_files(stream, 0)
        assert newer.files
        try:
            await old
        except live.Superseded:
            pass
        firsts = [r.first for r in stream.runs]
        assert firsts[-1] == 0 and firsts.count(0) == 1
    run(scenario)


def test_a_request_whose_player_left_stops_waiting(clips):
    path = clips["mkv"]
    left = asyncio.Event()

    async def gone():
        return left.is_set()

    async def scenario():
        _index, stream = await _open(path)
        n = len(stream.segments) // 2
        waiting = asyncio.create_task(live.segment_files(stream, n, gone))
        while not stream.runs:
            await asyncio.sleep(0.01)
        stream.runs[-1].pause()
        await asyncio.sleep(0.2)
        assert not waiting.done()
        left.set()
        with pytest.raises(live.Superseded):
            await asyncio.wait_for(waiting, 5)
    run(scenario)


def test_two_viewers_do_not_restart_each_other(clips):
    path = clips["mkv"]

    async def scenario():
        index, one = await _open(path)
        _index, two = await _open(path)
        await livecheck.fetch(one, 0)
        await livecheck.fetch(two, len(two.segments) - 1)
        assert one.folder != two.folder
        assert len(one.runs) == 1 and len(two.runs) == 1
    run(scenario)


def test_a_segment_is_one_styp_then_fragments(clips):
    path = clips["mkv"]

    async def scenario():
        _index, stream = await _open(path)
        n = next(i for i, s in enumerate(stream.segments) if s.end - s.first >= 3)
        pieces = await live.segment_files(stream, n)
        size, parts = live.joined(pieces)
        data = b"".join(live.read_joined(parts, pieces.adjust))
        assert len(data) == size
        boxes, at = [], 0
        while at < len(data):
            length = int.from_bytes(data[at:at + 4], "big")
            boxes.append(data[at + 4:at + 8].decode())
            at += length
        assert boxes[0] == "styp" and boxes.count("styp") == 1
        assert boxes[1:] == ["moof", "mdat"] * (len(pieces.files))
    run(scenario)


def test_init_is_the_same_from_any_run(clips):
    path = clips["mkv"]

    async def scenario():
        _index, stream = await _open(path)
        for n in [0, 4, len(stream.segments) - 1]:
            await live.segment_files(stream, n)
        init = open(await live.init_file(path, stream.audio), "rb").read()
        for run_ in stream.runs:
            assert open(os.path.join(run_.folder, "init.mp4"), "rb").read() == init
    run(scenario)


def _offset_edit_list(init: bytes, track: int, by: int) -> bytes:
    """The init with one track's edit list starting `by` later."""
    data = bytearray(init)
    current = None
    for kind, body, _stop in _walk(data):
        if kind == b"tkhd":
            current = int.from_bytes(data[body + 12:body + 16], "big")
        elif kind == b"elst" and current == track:
            at = body + 8 + 4
            value = int.from_bytes(data[at:at + 4], "big", signed=True) + by
            data[at:at + 4] = value.to_bytes(4, "big", signed=True)
    return bytes(data)


def _walk(data, start=0, end=None):
    for kind, body, stop in live._boxes(data, start, end):
        yield kind, body, stop
        if kind in (b"moov", b"trak", b"mdia", b"edts"):
            yield from _walk(data, body, stop)


def test_runs_whose_init_disagrees_with_the_served_one_are_retimed(clips, monkeypatch):
    """Frames show when the source shows them even against an init whose edit list is 0.08s off every run's."""
    path = clips["mkv"]
    real = live.init_file

    async def offset_init(file, audio):
        made = await real(file, audio)
        moved = made + ".moved.mp4"
        with open(made, "rb") as fh:
            data = _offset_edit_list(fh.read(), track=1, by=1280)
        with open(moved, "wb") as fh:
            fh.write(data)
        return moved

    monkeypatch.setattr(live, "init_file", offset_init)

    async def scenario():
        index, stream = await _open(path)
        for n in [0, 3, len(stream.segments) - 1, 1]:
            data = await livecheck.fetch(stream, n)
            assert livecheck.check_segment(path, index, stream.segments[n], data) == [], n
        assert all(r.adjust.get(1) == 1280 for r in stream.runs)
    run(scenario)


def test_the_chosen_audio_track_is_played(clips):
    path = clips["mkv"]

    def tone(data: bytes) -> float:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-map", "0:a", "-ac", "1",
             "-f", "s16le", "-ar", "8000", "-"], input=data, capture_output=True,
        ).stdout
        import array
        samples = array.array("h", out)
        crossings = sum(1 for x, y in zip(samples, samples[1:]) if (x < 0) != (y < 0))
        return crossings / 2 / (len(samples) / 8000)

    async def scenario():
        _index, first = await _open(path)
        _index, second = await _open(path, _audio_index(path, 1))
        assert abs(tone(await livecheck.fetch(first, 3)) - 440) < 15
        assert abs(tone(await livecheck.fetch(second, 3)) - 880) < 15
    run(scenario)


def _clicks(data: bytes) -> list[float]:
    first = livecheck.served_packets(data, "a")[0][0]
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-map", "0:a", "-ac", "1",
         "-f", "s16le", "-ar", "48000", "-"], input=data, capture_output=True,
    ).stdout
    import array
    samples = array.array("h", pcm)
    found, quiet = [], 0
    for i, x in enumerate(samples):
        if abs(x) > 8000:
            if quiet > 2400:
                found.append(first + i / 48000)
            quiet = 0
        else:
            quiet += 1
    return found


def test_sound_stays_in_sync_whichever_run_made_it(clips):
    """Clicks on every whole second sound within 20ms of it, across runs and seeks."""
    path = clips["clicks"]

    async def scenario():
        index, stream = await _open(path)
        last = len(stream.segments) - 1
        total = 0
        for n in [0, 1, 2, last - 2, 5, last, 3, 6]:
            data = await livecheck.fetch(stream, n)
            heard = _clicks(data)
            total += len(heard)
            for t in heard:
                assert abs(t + index.start - round(t + index.start)) < 0.02, (n, heard)
        assert total >= 30 and len(stream.runs) >= 3
    run(scenario)


def test_a_run_that_lands_early_is_renumbered_and_still_right(clips, monkeypatch):
    """A seek landing on an earlier keyframe is numbered from where the run really starts."""
    path = clips["mkv"]

    async def scenario():
        index, stream = await _open(path)
        n = 4
        k = stream.segments[n].first
        monkeypatch.setattr(live, "seek_points",
                            lambda idx, kk: [idx.keyframes[kk - 1] + 0.2])
        data = await livecheck.fetch(stream, n)
        assert livecheck.check_segment(path, index, stream.segments[n], data) == []
        assert [r.first for r in stream.runs] == [k - 1]
    run(scenario)


def test_a_run_that_lands_anywhere_unknown_is_never_served(clips, monkeypatch):
    path = clips["mkv"]

    async def nowhere(init, piece):
        return 12.345

    async def scenario():
        _index, stream = await _open(path)
        stream.shift = 0.0
        monkeypatch.setattr(live, "_first_video_time", nowhere)
        with pytest.raises(live.LiveError):
            await live.segment_files(stream, 4)
        assert stream.runs == [] and live.running() == 0
    run(scenario)


def test_a_run_that_lands_too_far_back_is_never_served(clips, monkeypatch):
    path = clips["mkv"]
    monkeypatch.setattr(live, "MAX_EARLY_SECONDS", 5.0)

    async def scenario():
        _index, stream = await _open(path)
        n = len(stream.segments) - 1
        monkeypatch.setattr(live, "seek_points", lambda idx, kk: [idx.keyframes[0] + 0.2])
        with pytest.raises(live.LiveError):
            await live.segment_files(stream, n)
    run(scenario)


def _state(pid: int) -> str:
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                          capture_output=True, text=True).stdout.strip()


def test_a_run_pauses_ahead_of_the_player_and_stops_when_idle(clips, monkeypatch):
    path = clips["mkv"]
    real = live._ffmpeg_args
    monkeypatch.setattr(live, "_ffmpeg_args", lambda *a, **k: (
        lambda args: args[:args.index("-i")] + ["-readrate", "4"] + args[args.index("-i"):]
    )(real(*a, **k)))
    monkeypatch.setattr(live, "PAUSE_AHEAD_SECONDS", 12.0)
    monkeypatch.setattr(live, "RESUME_AHEAD_SECONDS", 6.0)
    monkeypatch.setattr(live, "IDLE_STOP_SECONDS", 4.0)

    async def scenario():
        _index, stream = await _open(path)
        await live.segment_files(stream, 0)
        run_ = stream.current()
        for _ in range(100):
            if run_.paused:
                break
            stream.last_request = time.monotonic()
            await asyncio.sleep(0.1)
        assert run_.paused and "T" in _state(run_.proc.pid)
        n = next(i for i, s in enumerate(stream.segments) if s.start > 8)
        await live.segment_files(stream, n)
        for _ in range(30):
            if not run_.paused:
                break
            await asyncio.sleep(0.1)
        assert not run_.paused and "T" not in _state(run_.proc.pid)
        await asyncio.sleep(6.5)
        assert not run_.alive
    run(scenario)


def test_pieces_long_behind_the_player_are_deleted(clips, monkeypatch):
    path = clips["mkv"]
    monkeypatch.setattr(live, "KEEP_BEHIND_SECONDS", 20.0)

    async def scenario():
        _index, stream = await _open(path)
        last = len(stream.segments) - 1
        await live.segment_files(stream, last)
        await live.segment_files(stream, 0)
        stream.position = stream.segments[last].start
        live._trim(stream)
        left = sorted(int(n[1:-4]) for r in stream.runs for n in os.listdir(r.folder)
                      if n.endswith(".m4s"))
        assert left and all(stream.index.time(k + 1) >= stream.position - 20
                            for k in left if k + 1 < len(stream.index.keyframes))
    run(scenario)


def test_a_stream_nobody_watches_is_forgotten(clips, monkeypatch):
    path = clips["mkv"]
    monkeypatch.setattr(live, "IDLE_FORGET_SECONDS", 2.0)

    async def scenario():
        _index, stream = await _open(path)
        await live.segment_files(stream, 1)
        assert os.path.isdir(stream.folder)
        await asyncio.sleep(3.5)
        assert not os.path.isdir(stream.folder)
        assert live.running() == 0
    run(scenario)


def _decode_times(data: bytes) -> list[int]:
    times = []
    for kind, body, stop in live._boxes(data):
        if kind != b"moof":
            continue
        for traf, tbody, tstop in live._boxes(data, body, stop):
            for inner, ibody, _istop in live._boxes(data, tbody, tstop) if traf == b"traf" else ():
                if inner == b"tfdt":
                    width = 8 if data[ibody] == 1 else 4
                    times.append(int.from_bytes(data[ibody + 4:ibody + 4 + width], "big", signed=True))
    return times


def test_nothing_is_served_before_zero(clips):
    """ExoPlayer refuses a negative tfdt, so the first segment starts every track at zero or later."""
    path = clips["mkv"]

    async def scenario():
        index, stream = await _open(path)
        raw = b""
        pieces = await live.segment_files(stream, 0)
        _total, parts = live.joined(pieces)
        for part, offset in parts:
            with open(part, "rb") as fh:
                fh.seek(offset)
                raw += fh.read()
        assert min(_decode_times(raw)) < 0, "the clip no longer shows the case"
        data = await livecheck.fetch(stream, 0)
        assert min(_decode_times(data)) >= 0
        assert livecheck.check_segment(path, index, stream.segments[0], data) == []
        decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "null", "-"],
                                 input=data, capture_output=True)
        assert decoded.returncode == 0 and not decoded.stderr, decoded.stderr
    run(scenario)


def _box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def test_priming_is_dropped_when_sizes_are_the_tfhd_defaults():
    """An audio trun with no sizes or durations whose only sample is the priming frame at -1024."""
    tfhd = _box(b"tfhd", (0x20018).to_bytes(4, "big") + (2).to_bytes(4, "big")
                + (1024).to_bytes(4, "big") + (300).to_bytes(4, "big"))
    tfdt = _box(b"tfdt", b"\x01\x00\x00\x00" + (-1024).to_bytes(8, "big", signed=True))
    def piece(samples):
        trun = _box(b"trun", (0x1).to_bytes(4, "big") + samples.to_bytes(4, "big") + (500).to_bytes(4, "big"))
        video = _box(b"traf", _box(b"tfhd", (0x20000).to_bytes(4, "big") + (1).to_bytes(4, "big"))
                     + _box(b"tfdt", bytes(12)) + _box(b"trun", (0x1).to_bytes(4, "big") + bytes(4) + (900).to_bytes(4, "big")))
        moof = _box(b"moof", _box(b"mfhd", bytes(8)) + video + _box(b"traf", tfhd + tfdt + trun))
        return _box(b"styp", b"msdh" + bytes(4)) + moof + _box(b"mdat", bytes(600))

    two = piece(2)
    out = live.start_at_zero(two)
    assert len(out) == len(two)
    assert _decode_times(out) == [0, 0]
    at = out.rindex(b"trun") + 4
    assert live._u32(out, at + 4) == 1
    assert live._u32(out, at + 8) == 800

    # Priming alone: the audio traf goes, since ExoPlayer cannot take a trun
    # with no samples, and the video's data offset moves back with the moof.
    one = piece(1)
    traf = len(_box(b"traf", tfhd + tfdt + _box(b"trun", bytes(12))))
    out = live.start_at_zero(one)
    assert len(out) == len(one) - traf
    assert _decode_times(out) == [0]
    assert out.count(b"traf") == 1
    assert live._u32(out, out.index(b"trun") + 4 + 8) == 900 - traf
