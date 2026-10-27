"""Live remux: HLS segments made on demand from the source, cut at its keyframes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field

from ..config import settings
from .mediainfo import FFMPEG, FFPROBE, PROBE_CACHE

log = logging.getLogger(__name__)

ROOT = os.environ.get("VIBESTREAM_LIVE_CACHE", "/app/data/live")
INIT_ROOT = os.path.join(ROOT, "init")
STREAMS_ROOT = os.path.join(ROOT, "streams")

INDEX_VERSION = 1
TARGET_SEGMENT_SECONDS = 6.0

# Further ahead than this restarts ffmpeg instead of waiting (Jellyfin's figure).
RESTART_AHEAD_SECONDS = 24.0
# The run pauses this far ahead of the player and resumes below the second figure.
PAUSE_AHEAD_SECONDS = 120.0
RESUME_AHEAD_SECONDS = 60.0
IDLE_STOP_SECONDS = 60.0
IDLE_FORGET_SECONDS = 600.0
KEEP_BEHIND_SECONDS = 720.0
SEGMENT_TIMEOUT_SECONDS = 60.0
LANDING_TOLERANCE = 0.004
SEEK_PAST = 0.02
# ffmpeg's own pull-back on input seeks into files with B-frames
# (fftools/ffmpeg_demux.c, "dts_heuristic").
DTS_HEURISTIC = 3 / 23

AUDIO_ARGS = ["-c:a", "aac", "-ac", "2", "-b:a", "192k"]


class LiveError(RuntimeError):
    """A segment that could not be made."""


class Superseded(LiveError):
    """A request overtaken by a newer one (a seek); it must not restart ffmpeg back
    where it was, or two requests would keep restarting it.
    """


@dataclass
class Index:
    """`keyframes` are presentation times in seconds; player times are keyframes minus `start`."""

    duration: float
    keyframes: list[float]
    start: float = 0.0
    size: int = 0
    mtime: float = 0.0

    def time(self, k: int) -> float:
        return self.keyframes[k] - self.start


def _key(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def index_path(path: str) -> str:
    return os.path.join(PROBE_CACHE, _key(path) + ".keyframes.json")


def load_index(path: str) -> Index | None:
    try:
        with open(index_path(path), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") != INDEX_VERSION:
            return None
        index = Index(
            duration=float(data["duration"]),
            keyframes=[float(k) for k in data["keyframes"]],
            start=float(data.get("start") or 0.0),
            size=int(data.get("size") or 0),
            mtime=float(data.get("mtime") or 0.0),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size != index.size or abs(st.st_mtime - index.mtime) > 1:
        return None
    return index if index.keyframes else None


def has_index(path: str) -> bool:
    return load_index(path) is not None


def parse_keyframes(text: str) -> tuple[list[float], float, float]:
    """Fields are read by name: ffprobe prints them in its own order. Flags
    starting with K mark a keyframe.
    """
    keyframes: list[float] = []
    stream_duration = format_duration = start = 0.0
    for line in text.splitlines():
        kind, _, rest = line.strip().partition(",")
        fields = dict(part.split("=", 1) for part in rest.split(",") if "=" in part)

        def number(name: str) -> float | None:
            try:
                return float(fields[name])
            except (KeyError, ValueError):
                return None

        if kind == "packet":
            pts = number("pts_time")
            if pts is not None and fields.get("flags", "").startswith("K"):
                keyframes.append(pts)
        elif kind == "stream":
            stream_duration = number("duration") or stream_duration
        elif kind == "format":
            format_duration = number("duration") or format_duration
            start = number("start_time") or start
    return sorted(set(keyframes)), (stream_duration or format_duration), start


async def build_index(path: str, timeout: float = 600.0) -> Index:
    """Read every keyframe of the file and save the index. Matroska Cues would be
    instant, but need not list every keyframe.
    """
    st = os.stat(path)
    proc = await asyncio.create_subprocess_exec(
        FFPROBE, "-fflags", "+genpts", "-v", "error", "-skip_frame", "nokey",
        "-show_entries", "format=duration,start_time",
        "-show_entries", "stream=duration",
        "-show_entries", "packet=pts_time,flags",
        "-select_streams", "v:0", "-of", "csv=nokey=0", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise LiveError(f"reading the keyframes of {os.path.basename(path)} timed out") from None
    if proc.returncode != 0:
        raise LiveError(f"ffprobe failed: {err.decode('utf-8', 'replace')[:300]}")
    keyframes, duration, start = parse_keyframes(out.decode("utf-8", "replace"))
    if not keyframes or duration <= 0:
        raise LiveError("the file has no keyframes or no duration")
    index = Index(duration=duration, keyframes=keyframes, start=start,
                  size=st.st_size, mtime=st.st_mtime)
    os.makedirs(PROBE_CACHE, exist_ok=True)
    tmp = index_path(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": INDEX_VERSION, "duration": duration, "start": start,
                   "size": index.size, "mtime": index.mtime, "keyframes": keyframes}, fh)
    os.replace(tmp, index_path(path))
    log.info("indexed %s: %s keyframes", os.path.basename(path), len(keyframes))
    return index


_building: dict[str, asyncio.Task] = {}


def start_index(path: str) -> asyncio.Task:
    task = _building.get(path)
    if task is None or task.done():
        task = asyncio.create_task(build_index(path))
        _building[path] = task
    return task


def indexing(path: str) -> bool:
    task = _building.get(path)
    return task is not None and not task.done()


def index_error(path: str) -> str | None:
    task = _building.get(path)
    if task is None or not task.done() or task.cancelled():
        return None
    exc = task.exception()
    return str(exc)[:300] if exc else None


def clear_index(path: str) -> None:
    try:
        os.remove(index_path(path))
    except OSError:
        pass


@dataclass(frozen=True)
class Segment:
    first: int
    end: int
    start: float
    duration: float


def plan(index: Index, target: float = TARGET_SEGMENT_SECONDS) -> list[Segment]:
    """Group the keyframes into segments: Jellyfin's ComputeSegments."""
    times = [index.time(k) for k in range(len(index.keyframes))]
    cuts = [0]
    wanted = target
    for k in range(1, len(times)):
        if times[k] >= wanted:
            cuts.append(k)
            wanted += target
    # The container's duration can end before the last keyframe; every GOP must
    # belong to a segment, so the end moves.
    duration = max(index.duration, times[-1])
    if len(cuts) > 1 and duration - times[cuts[-1]] < 0.5:
        cuts.pop()
    segments = []
    for n, first in enumerate(cuts):
        begin = 0.0 if n == 0 else times[first]
        if n + 1 < len(cuts):
            end, until = cuts[n + 1], times[cuts[n + 1]]
        else:
            end, until = len(times), duration
        segments.append(Segment(first=first, end=end, start=begin, duration=until - begin))
    return segments


def media_playlist(index: Index, base: str, query: str = "") -> str:
    """The complete VOD playlist, closing tag included, before any of it exists."""
    segments = plan(index)
    target = max(1, math.ceil(max(s.duration for s in segments)))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{base}/init.mp4{query}"',
    ]
    for n, segment in enumerate(segments):
        lines.append(f"#EXTINF:{segment.duration:.6f},")
        lines.append(f"{base}/{n}.m4s{query}")
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def new_token() -> str:
    """One run per playback, so viewers' seeks do not restart each other's runs."""
    return secrets.token_urlsafe(9)


def _ffmpeg_args(path: str, audio: int | None, seek: float | None, first: int,
                 folder: str, duration: float | None = None) -> list[str]:
    args = [FFMPEG, "-nostdin", "-v", "error"]
    if seek is not None:
        args += ["-noaccurate_seek", "-seek_timestamp", "1", "-ss", f"{seek:.6f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-fflags", "+genpts", "-i", path,
             "-map_metadata", "-1", "-map_chapters", "-1", "-map", "0:v:0"]
    if audio is not None:
        args += ["-map", f"0:{audio}"]
    args += [
        "-c:v", "copy", "-start_at_zero",
        *AUDIO_ARGS,
        # Timestamps stay the file's own, so a piece from a run started anywhere
        # sits where it belongs on the timeline.
        "-copyts", "-avoid_negative_ts", "disabled",
        "-max_muxing_queue_size", "2048",
        "-f", "hls", "-max_delay", "5000000",
        # A cut at every keyframe, so a run restarted by a seek keeps the playlist's cuts.
        "-hls_time", "0.001",
        # Each piece appears under its own name only once it is complete.
        "-hls_flags", "+temp_file",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", "init.mp4",
        "-start_number", str(first),
        "-hls_segment_filename", os.path.join(folder, "g%d.m4s"),
        "-hls_playlist_type", "vod", "-hls_list_size", "0",
        # No sidx: writing it rewrites packet times at open-GOP boundaries.
        "-hls_segment_options", "movflags=+frag_discont+skip_sidx",
        "-y", os.path.join(folder, "run.m3u8"),
    ]
    return args


def seek_points(index: Index, k: int) -> list[float | None]:
    """Aims for keyframe k. ffmpeg may pull a seek back by 3/23s depending on the
    file, so both are tried and the landing is checked.
    """
    if k == 0:
        return [None]
    keyframes = index.keyframes
    gap = (keyframes[k + 1] - keyframes[k]) if k + 1 < len(keyframes) else 1.0
    aim = keyframes[k] + min(SEEK_PAST, gap / 2)
    return [aim + DTS_HEURISTIC, aim]


async def _first_video_time(init: str, piece: str) -> float | None:
    """The first frame stored, not the earliest shown: open GOPs reorder around it."""
    with open(init, "rb") as fh:
        data = fh.read()
    with open(piece, "rb") as fh:
        data += fh.read()
    proc = await asyncio.create_subprocess_exec(
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "packet=pts_time", "-of", "csv=p=0", "-i", "pipe:0",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate(data)
    for line in out.decode().split():
        try:
            return float(line.strip(","))
        except ValueError:
            continue
    return None


_CONTAINERS = {b"moov", b"trak", b"mdia", b"edts", b"moof", b"traf"}


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    at = start
    while at + 8 <= end:
        size = int.from_bytes(data[at:at + 4], "big")
        kind = data[at + 4:at + 8]
        head = 8
        if size == 1:
            size = int.from_bytes(data[at + 8:at + 16], "big")
            head = 16
        elif size == 0:
            size = end - at
        if size < head:
            return
        yield kind, at + head, at + size
        at += size


def edit_offsets(init: bytes) -> dict[int, int]:
    """Edit list start per track: a run from the file's very start writes a different one."""
    offsets: dict[int, int] = {}

    def walk(start: int, end: int, track: list[int]) -> None:
        for kind, body, stop in _boxes(init, start, end):
            if kind == b"trak":
                current = [0]
                walk(body, stop, current)
            elif kind == b"tkhd":
                version = init[body]
                at = body + (20 if version == 1 else 12)
                track[0] = int.from_bytes(init[at:at + 4], "big")
                offsets.setdefault(track[0], 0)
            elif kind == b"elst":
                version = init[body]
                if int.from_bytes(init[body + 4:body + 8], "big"):
                    at = body + 8 + (8 if version == 1 else 4)
                    width = 8 if version == 1 else 4
                    offsets[track[0]] = int.from_bytes(init[at:at + width], "big", signed=True)
            elif kind in _CONTAINERS:
                walk(body, stop, track)

    walk(0, len(init), [0])
    return offsets


def retime(piece: bytes, adjust: dict[int, int]) -> bytes:
    """Retimed for a run whose init disagrees with the one served. Only tfdt changes."""
    if not any(adjust.values()):
        return piece
    data = bytearray(piece)
    for kind, body, stop in _boxes(data):
        if kind != b"moof":
            continue
        for traf, tbody, tstop in _boxes(data, body, stop):
            if traf != b"traf":
                continue
            track = None
            for inner, ibody, _istop in _boxes(data, tbody, tstop):
                if inner == b"tfhd":
                    track = int.from_bytes(data[ibody + 4:ibody + 8], "big")
                elif inner == b"tfdt" and adjust.get(track):
                    width = 8 if data[ibody] == 1 else 4
                    at = ibody + 4
                    value = int.from_bytes(data[at:at + width], "big", signed=True) + adjust[track]
                    data[at:at + width] = max(0, value).to_bytes(width, "big")
    return bytes(data)


def _u32(data, at: int) -> int:
    return int.from_bytes(data[at:at + 4], "big")


def _put32(data: bytearray, at: int, value: int, signed: bool = False) -> None:
    data[at:at + 4] = value.to_bytes(4, "big", signed=signed)


def _before_zero(data: bytes, tbody: int, tstop: int) -> tuple[int, int, int, int] | None:
    """For a traf with a negative decode time: (trun offset, samples to drop,
    first kept decode time, media bytes). None otherwise.
    """
    tfdt = trun = None
    default_duration = default_size = None
    for inner, ibody, _istop in _boxes(data, tbody, tstop):
        if inner == b"tfhd":
            flags = _u32(data, ibody) & 0xFFFFFF
            at = ibody + 8 + (8 if flags & 0x1 else 0) + (4 if flags & 0x2 else 0)
            if flags & 0x8:
                default_duration = _u32(data, at)
                at += 4
            if flags & 0x10:
                default_size = _u32(data, at)
        elif inner == b"tfdt":
            width = 8 if data[ibody] == 1 else 4
            tfdt = int.from_bytes(data[ibody + 4:ibody + 4 + width], "big", signed=True)
        elif inner == b"trun":
            if trun is not None:
                return None
            trun = ibody
    if tfdt is None or tfdt >= 0 or trun is None:
        return None
    flags = _u32(data, trun) & 0xFFFFFF
    count = _u32(data, trun + 4)
    at = trun + 8 + (4 if flags & 0x1 else 0) + (4 if flags & 0x4 else 0)
    stride = 4 * bin(flags & 0xF00).count("1")
    if not flags & 0x1:
        return None
    if (not flags & 0x100 and default_duration is None) or (not flags & 0x200 and default_size is None):
        return None
    size_at = 4 if flags & 0x100 else 0
    time, drop, skipped = tfdt, 0, 0
    while time < 0 and drop < count:
        entry = at + drop * stride
        time += _u32(data, entry) if flags & 0x100 else default_duration
        skipped += _u32(data, entry + size_at) if flags & 0x200 else default_size
        drop += 1
    return trun, drop, time, skipped


def start_at_zero(piece: bytes) -> bytes:
    """ExoPlayer refuses a negative tfdt ("Top bit not zero"), so samples before zero are dropped."""
    if b"tfdt" not in piece:
        return piece
    data = bytearray(piece)
    out = bytearray()
    done = 0
    for kind, body, stop in _boxes(piece):
        if kind != b"moof" or stop > min(len(piece), HEAD_BYTES):
            continue
        cuts = []
        for traf, tbody, tstop in _boxes(piece, body, stop):
            if traf == b"traf":
                found = _before_zero(piece, tbody, tstop)
                if found and found[1]:
                    cuts.append((traf, tbody, tstop, *found))
        if not cuts:
            continue
        head = body - 8
        moof = bytearray(piece[head:stop])
        removed_total = 0
        plan = []
        for _traf, tbody, tstop, trun, drop, time, skipped in cuts:
            flags = _u32(piece, trun) & 0xFFFFFF
            stride = 4 * bin(flags & 0xF00).count("1")
            at = trun + 8 + 4 + (4 if flags & 0x4 else 0)
            if drop == _u32(piece, trun + 4):
                at, cut = tbody - 8, tstop - (tbody - 8)
            else:
                cut = stride * drop
            plan.append((tbody, tstop, trun, drop, time, at, cut, skipped))
            removed_total += cut
        for traf, tbody, tstop in _boxes(piece, body, stop):
            if traf != b"traf":
                continue
            for inner, ibody, _istop in _boxes(piece, tbody, tstop):
                if inner == b"trun" and _u32(piece, ibody) & 0x1:
                    mine = next((p for p in plan if p[2] == ibody), None)
                    offset = int.from_bytes(piece[ibody + 8:ibody + 12], "big", signed=True)
                    offset -= removed_total
                    if mine:
                        offset += mine[7]
                    _put32(moof, ibody + 8 - head, offset, signed=True)
        for tbody, tstop, trun, drop, time, at, cut, _skipped in sorted(plan, key=lambda p: -p[2]):
            if at == tbody - 8:
                del moof[at - head:at - head + cut]
                continue
            _put32(moof, trun + 4 - head, _u32(piece, trun + 4) - drop)
            for inner, ibody, _istop in _boxes(piece, tbody, tstop):
                if inner == b"tfdt":
                    width = 8 if piece[ibody] == 1 else 4
                    moof[ibody + 4 - head:ibody + 4 + width - head] = time.to_bytes(width, "big", signed=True)
            del moof[at - head:at - head + cut]
            for box in (trun - 8, tbody - 8):
                _put32(moof, box - head, _u32(moof, box - head) - cut)
        _put32(moof, 0, len(moof))
        out += data[done:head] + moof
        done = stop
    if done == 0:
        return piece
    out += data[done:]
    return bytes(out)


class Run:
    """Plain subprocess, not asyncio's: on macOS asyncio's child watcher blocks
    the event loop reaping a SIGSTOPped child.
    """

    def __init__(self, folder: str, first: int):
        self.folder = folder
        self.first = first
        self.proc: subprocess.Popen | None = None
        self.paused = False
        self.killed = False
        self.landed = False
        self._error: str | None = None
        self.adjust: dict[int, int] = {}

    def piece(self, k: int) -> str:
        return os.path.join(self.folder, f"g{k}.m4s")

    def has(self, k: int) -> bool:
        """Whether piece k is complete; with temp_file it takes its name only once closed."""
        return k >= self.first and os.path.exists(self.piece(k))

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def finished(self) -> bool:
        return self.proc is not None and self.proc.poll() == 0

    @property
    def error(self) -> str | None:
        if self._error is None and self.proc is not None and not self.killed:
            code = self.proc.poll()
            if code not in (None, 0):
                try:
                    with open(os.path.join(self.folder, "ffmpeg.log"), "rb") as fh:
                        said = fh.read()[-2000:].decode("utf-8", "replace").strip()
                except OSError:
                    said = ""
                self._error = said[-400:] or f"ffmpeg exited {code}"
                log.error("live run in %s failed: %s", self.folder, self._error)
        return self._error

    def newest(self) -> int | None:
        k = self.first
        if not self.has(k):
            return None
        while self.has(k + 1):
            k += 1
        return k

    async def start(self, args: list[str]) -> None:
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, "ffmpeg.log"), "wb") as said:
            self.proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=said, start_new_session=True,
            )

    def pause(self) -> None:
        if self.alive and not self.paused:
            os.kill(self.proc.pid, signal.SIGSTOP)
            self.paused = True

    def resume(self) -> None:
        if self.alive and self.paused:
            os.kill(self.proc.pid, signal.SIGCONT)
            self.paused = False

    async def stop(self) -> None:
        self.killed = True
        if self.alive:
            self.proc.kill()
            while self.proc.poll() is None:
                await asyncio.sleep(0.02)
        self.paused = False


@dataclass
class Stream:
    path: str
    audio: int | None
    token: str
    index: Index
    folder: str
    segments: list[Segment] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float = field(default_factory=time.monotonic)
    position: float = 0.0
    serial: int = 0
    monitor: asyncio.Task | None = None

    def current(self) -> Run | None:
        for run in reversed(self.runs):
            if run.alive:
                return run
        return None

    def complete_in(self, a: int, b: int) -> Run | None:
        """Never stitched from two runs: their pieces carry audio from different encodes."""
        for run in reversed(self.runs):
            if all(run.has(k) for k in range(a, b)):
                return run
        return None


_streams: dict[tuple[str, int | None, str], Stream] = {}
_registry_lock = asyncio.Lock()


def _stream_folder(path: str, audio: int | None, token: str) -> str:
    key = hashlib.sha1(f"{path}:{audio}:{token}".encode()).hexdigest()[:16]
    return os.path.join(STREAMS_ROOT, key)


async def track_for(path: str, audio: int | None) -> int | None:
    if audio is not None:
        return audio
    from . import mediainfo

    info = mediainfo.cached_info(path) or await mediainfo.probe(path)
    default = info.default_audio()
    return default.index if default else None


async def stream_for(path: str, audio: int | None, token: str, index: Index) -> Stream:
    audio = await track_for(path, audio)
    key = (path, audio, token)
    async with _registry_lock:
        stream = _streams.get(key)
        if stream is None:
            stream = Stream(path=path, audio=audio, token=token, index=index,
                            folder=_stream_folder(path, audio, token))
            stream.segments = plan(index)
            _streams[key] = stream
            stream.monitor = asyncio.create_task(_watch(stream))
        return stream


MAX_EARLY_SECONDS = 60.0


def _keyframe_at(index: Index, t: float) -> int | None:
    import bisect

    times = [index.time(k) for k in range(len(index.keyframes))]
    at = bisect.bisect_left(times, t - LANDING_TOLERANCE)
    if at < len(times) and abs(times[at] - t) <= LANDING_TOLERANCE:
        return at
    return None


async def _launch(stream: Stream, seek: float | None, first: int) -> tuple[Run, float | None]:
    served = await init_file(stream.path, stream.audio)
    stream.serial += 1
    run = Run(os.path.join(stream.folder, f"r{stream.serial}"), first)
    await run.start(_ffmpeg_args(stream.path, stream.audio, seek, first, run.folder))
    deadline = time.monotonic() + SEGMENT_TIMEOUT_SECONDS
    own = os.path.join(run.folder, "init.mp4")
    while not (run.has(first) and os.path.exists(own)):
        if not run.alive:
            await asyncio.sleep(0.05)
            if run.has(first) and os.path.exists(own):
                break
            raise LiveError(run.error or "ffmpeg stopped before writing anything")
        if time.monotonic() > deadline:
            await run.stop()
            raise LiveError("ffmpeg took too long to start")
        await asyncio.sleep(0.03)
    with open(served, "rb") as fh:
        wanted = edit_offsets(fh.read())
    with open(own, "rb") as fh:
        mine = edit_offsets(fh.read())
    run.adjust = {track: wanted.get(track, 0) - mine.get(track, 0) for track in mine}
    return run, await _first_video_time(own, run.piece(first))


async def _discard(run: Run) -> None:
    await run.stop()
    shutil.rmtree(run.folder, ignore_errors=True)


async def _start_run(stream: Stream, k: int) -> Run:
    """A seek lands only on a seek index entry, so the run is restarted numbered
    from where it landed. A landing off a known keyframe is never served.
    """
    for seek in seek_points(stream.index, k):
        run, landed = await _launch(stream, seek, k)
        if landed is not None and abs(landed - stream.index.time(k)) <= LANDING_TOLERANCE:
            run.landed = True
            stream.runs.append(run)
            return run
        await _discard(run)
        j = _keyframe_at(stream.index, landed) if landed is not None else None
        if j is not None and j < k and stream.index.time(k) - stream.index.time(j) <= MAX_EARLY_SECONDS:
            run, again = await _launch(stream, seek, j)
            if again is not None and abs(again - stream.index.time(j)) <= LANDING_TOLERANCE:
                run.landed = True
                stream.runs.append(run)
                return run
            await _discard(run)
        log.warning(
            "live run for %s aimed at %.3f landed at %s, trying the next seek point",
            os.path.basename(stream.path), stream.index.time(k), landed,
        )
    raise LiveError(f"could not start on keyframe {k} of {os.path.basename(stream.path)}")


@dataclass
class Pieces:
    files: list[str]
    adjust: dict[int, int]


async def segment_files(stream: Stream, n: int, gone=None) -> Pieces:
    """The pieces of segment n, in order. Jellyfin's restart rule: no run, a
    request before it, or one further ahead than RESTART_AHEAD_SECONDS.
    """
    if n < 0 or n >= len(stream.segments):
        raise LiveError("no such segment")
    segment = stream.segments[n]
    a, b = segment.first, segment.end
    stream.last_request = time.monotonic()
    stream.position = max(segment.start, 0.0)

    deadline = time.monotonic() + SEGMENT_TIMEOUT_SECONDS
    async with stream.lock:
        done = stream.complete_in(a, b)
        if done is not None:
            return Pieces([done.piece(k) for k in range(a, b)], done.adjust)
        run = stream.current()
        if run is not None and run.first <= a:
            newest = run.newest()
            reached = stream.index.time(newest) if newest is not None else stream.index.time(run.first)
            if stream.index.time(a) - reached > RESTART_AHEAD_SECONDS:
                run = None
        else:
            run = None
        if run is None:
            previous = stream.current()
            if previous is not None:
                await previous.stop()
            run = await _start_run(stream, a)
        run.resume()
    checked = time.monotonic()
    while not all(run.has(k) for k in range(a, b)):
        if not run.alive:
            if run.error:
                raise LiveError(run.error)
            await asyncio.sleep(0.05)  # a last piece is renamed as ffmpeg exits
            if all(run.has(k) for k in range(a, b)):
                break
            if run.killed:
                raise Superseded(f"segment {n}: a newer request moved ffmpeg elsewhere")
            raise LiveError(f"segment {n}: ffmpeg stopped before it")
        if time.monotonic() > deadline:
            raise LiveError(f"segment {n} took too long")
        if gone is not None and time.monotonic() - checked > 0.5:
            checked = time.monotonic()
            if await gone():
                raise Superseded(f"segment {n}: the player stopped waiting")
        stream.last_request = time.monotonic()
        await asyncio.sleep(0.05)
    return Pieces([run.piece(k) for k in range(a, b)], run.adjust)


HEAD_BYTES = 256 * 1024


def joined(pieces: Pieces) -> tuple[int, list[tuple[str, int]]]:
    """The first piece's styp is kept and the others skipped, making one fMP4 segment."""
    parts = []
    total = 0
    for n, path in enumerate(pieces.files):
        size = os.path.getsize(path)
        offset = 0
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES)
        if n > 0 and len(head) >= 8 and head[4:8] == b"styp":
            offset = int.from_bytes(head[:4], "big")
        parts.append((path, offset))
        total += size - offset - (len(head) - len(start_at_zero(head)))
    return total, parts


def read_joined(parts: list[tuple[str, int]], adjust: dict[int, int] | None = None):
    for path, offset in parts:
        with open(path, "rb") as fh:
            fh.seek(offset)
            yield start_at_zero(retime(fh.read(), adjust or {}))


_init_locks: dict[str, asyncio.Lock] = {}


def _init_path(path: str, audio: int | None) -> str:
    key = hashlib.sha1(f"{path}:{audio}".encode()).hexdigest()[:16]
    return os.path.join(INIT_ROOT, key + ".mp4")


async def init_file(path: str, audio: int | None) -> str:
    """The same bytes from every run, so made once by a short run and kept."""
    target = _init_path(path, audio)
    if _init_current(path, target):
        return target
    lock = _init_locks.setdefault(target, asyncio.Lock())
    async with lock:
        if _init_current(path, target):
            return target
        folder = target + ".work"
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder, exist_ok=True)
        args = _ffmpeg_args(path, audio, None, 0, folder, duration=0.3)
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        made = os.path.join(folder, "init.mp4")
        if proc.returncode != 0 or not os.path.exists(made):
            shutil.rmtree(folder, ignore_errors=True)
            raise LiveError(f"could not make the init segment: {err.decode('utf-8', 'replace')[-300:]}")
        os.replace(made, target)
        shutil.rmtree(folder, ignore_errors=True)
        with open(target + ".src", "w", encoding="utf-8") as fh:
            fh.write(_source_stamp(path) or "")
        return target


def _source_stamp(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{st.st_size} {st.st_mtime_ns}"


def _init_current(path: str, target: str) -> bool:
    if not os.path.exists(target):
        return False
    stamp = _source_stamp(path)
    if stamp is None:
        return True  # the source is gone: what was made from it is all there is
    try:
        with open(target + ".src", encoding="utf-8") as fh:
            return fh.read() == stamp
    except OSError:
        return False


def clear_init(path: str) -> None:
    for audio in (None, *range(0, 32)):
        for suffix in ("", ".src", ".first.m4s"):
            try:
                os.remove(_init_path(path, audio) + suffix)
            except OSError:
                pass


async def _watch(stream: Stream) -> None:
    """Signals, not keys on ffmpeg's stdin, which changed between versions."""
    try:
        while True:
            await asyncio.sleep(1.0)
            idle = time.monotonic() - stream.last_request
            run = stream.current()
            if idle > IDLE_FORGET_SECONDS:
                await forget(stream)
                return
            if run is not None and idle > IDLE_STOP_SECONDS:
                await run.stop()
                continue
            if run is not None:
                newest = run.newest()
                if newest is not None:
                    ahead = stream.index.time(newest) - stream.position
                    if ahead > PAUSE_AHEAD_SECONDS:
                        run.pause()
                    elif ahead < RESUME_AHEAD_SECONDS:
                        run.resume()
            _trim(stream)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - upkeep must not die quietly mid-film
        log.exception("live upkeep failed for %s", stream.folder)


def _trim(stream: Stream) -> None:
    floor = stream.position - KEEP_BEHIND_SECONDS
    if floor <= 0:
        return
    for run in list(stream.runs):
        try:
            names = os.listdir(run.folder)
        except OSError:
            names = []
        for name in names:
            if not (name.startswith("g") and name.endswith(".m4s")):
                continue
            try:
                k = int(name[1:-4])
            except ValueError:
                continue
            if k + 1 < len(stream.index.keyframes) and stream.index.time(k + 1) < floor:
                try:
                    os.remove(os.path.join(run.folder, name))
                except OSError:
                    pass
        try:
            left = [n for n in os.listdir(run.folder) if n.endswith(".m4s")]
        except OSError:
            left = []
        if not run.alive and not left:
            stream.runs.remove(run)
            shutil.rmtree(run.folder, ignore_errors=True)


async def forget(stream: Stream) -> None:
    for run in stream.runs:
        await run.stop()
    _streams.pop((stream.path, stream.audio, stream.token), None)
    shutil.rmtree(stream.folder, ignore_errors=True)


async def shutdown() -> None:
    for stream in list(_streams.values()):
        if stream.monitor:
            stream.monitor.cancel()
        for run in stream.runs:
            await run.stop()
    _streams.clear()


def reset() -> None:
    shutil.rmtree(STREAMS_ROOT, ignore_errors=True)


def reset_state() -> None:
    """An asyncio.Lock used under one loop refuses the next; tests run one per case."""
    global _registry_lock
    _streams.clear()
    _building.clear()
    _init_locks.clear()
    _registry_lock = asyncio.Lock()


def running() -> int:
    return sum(1 for s in _streams.values() if s.current() is not None)


def enabled(play_id: str) -> bool:
    """PLAYBACK_ENGINE=live, or LIVE_TRIAL with play ids. A title whose source is
    gone keeps playing from its rendition.
    """
    return settings.playback_engine == "live" or play_id in settings.live_trial


def everywhere() -> bool:
    return settings.playback_engine == "live"
