"""HLS renditions: one continuous ffmpeg remux per title (video copied, audio to AAC), served as VOD."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time

from .mediainfo import FFMPEG, MediaInfo

log = logging.getLogger(__name__)

CACHE_ROOT = os.environ.get("VIBESTREAM_HLS_CACHE", "/app/data/hls")
TARGET_SEGMENT_SECONDS = 6
SEGMENT_TTL_SECONDS = 24 * 3600
MAX_CACHE_BYTES = 40 * 1024 ** 3


def cache_key(path: str, audio_index: int | None) -> str:
    return hashlib.sha1(f"{path}:{audio_index}".encode()).hexdigest()[:16]


PLAYLIST_NAME = "index.m3u8"


def _session_dir(key: str) -> str:
    return os.path.join(CACHE_ROOT, key)


def playlist_path_for(path: str, audio_index: int | None = None) -> str:
    return os.path.join(_session_dir(cache_key(path, audio_index)), PLAYLIST_NAME)


class Session:
    def __init__(self, info: MediaInfo, audio_index: int | None):
        self.info = info
        self.audio_index = audio_index
        self.key = cache_key(info.path, audio_index)
        self.dir = _session_dir(self.key)
        self.proc: asyncio.subprocess.Process | None = None
        self.started_at = 0.0
        self.error: str | None = None

    @property
    def playlist_path(self) -> str:
        return os.path.join(self.dir, PLAYLIST_NAME)

    @property
    def complete(self) -> bool:
        try:
            with open(self.playlist_path, "r", encoding="utf-8") as fh:
                return "#EXT-X-ENDLIST" in fh.read()
        except OSError:
            return False

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def progress(self) -> dict:
        try:
            written = len([n for n in os.listdir(self.dir) if n.endswith(".m4s")])
        except OSError:
            written = 0

        total = self.info.duration or 0
        seconds_ready = written * TARGET_SEGMENT_SECONDS
        percent = min(99.0, (seconds_ready / total) * 100) if total else 0.0

        if self.complete:
            percent = 100.0

        eta = None
        elapsed = time.monotonic() - self.started_at if self.started_at else 0
        if elapsed > 3 and seconds_ready > 0 and total > seconds_ready:
            rate = seconds_ready / elapsed  # seconds of video per second
            if rate > 0:
                eta = int((total - seconds_ready) / rate)

        return {
            "ready": self.complete,
            "running": self.running,
            "percent": round(percent, 1),
            "seconds_ready": round(seconds_ready),
            "duration": round(total),
            "eta_seconds": eta,
            "error": self.error,
        }

    def _args(self) -> list[str]:
        audio = self.audio_index
        if audio is None:
            default = self.info.default_audio()
            audio = default.index if default else None

        args = [FFMPEG, "-nostdin", "-v", "error", "-i", self.info.path, "-map", "0:v:0"]
        if audio is not None:
            args += ["-map", f"0:{audio}"]
        args += [
            "-c:v", "copy",
            # Audio is re-encoded in ONE continuous encode, so no per-segment priming
            # delay accumulates. Stereo, since a browser cannot render 5.1 usefully.
            "-c:a", "aac", "-ac", "2", "-b:a", "192k",
            "-f", "hls",
            "-hls_time", str(TARGET_SEGMENT_SECONDS),
            # VOD, never EVENT: players join a playlist with no closing tag at the live
            # edge instead of at zero, which breaks start position and Replay.
            "-hls_playlist_type", "vod",
            "-hls_segment_type", "fmp4",
            "-hls_flags", "independent_segments",
            "-hls_list_size", "0",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", os.path.join(self.dir, "seg%05d.m4s"),
            self.playlist_path,
        ]
        return args

    async def start(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        self.started_at = time.monotonic()
        log.info(
            "starting HLS session for %s (audio=%s)",
            os.path.basename(self.info.path), self.audio_index,
        )
        self.proc = await asyncio.create_subprocess_exec(
            *self._args(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        assert self.proc is not None
        stderr = await self.proc.stderr.read()
        code = await self.proc.wait()
        if code != 0:
            self.error = stderr.decode("utf-8", "replace")[:400]
            log.error("HLS session failed for %s: %s", self.info.path, self.error)
        else:
            log.info(
                "HLS session complete for %s in %.0fs",
                os.path.basename(self.info.path), time.monotonic() - self.started_at,
            )

    async def wait(self) -> None:
        while self.running:
            await asyncio.sleep(2)

    def stop(self) -> None:
        if self.running and self.proc:
            self.proc.kill()


_sessions: dict[str, Session] = {}
_session_lock = asyncio.Lock()


class SourceGone(RuntimeError):
    """A rendition was asked for that was never built, from a source that is gone."""


def _normal(info: MediaInfo, audio_index: int | None) -> int | None:
    """Otherwise choosing the playing track built a second copy of the title."""
    default = info.default_audio()
    if audio_index is not None and default is not None and audio_index == default.index:
        return None
    return audio_index


def extra_audio(info: MediaInfo) -> list[int]:
    """One per language the default is not in: every rendition carries the whole video."""
    default = info.default_audio()
    seen = {(default.language or "und") if default else None}
    kept = []
    for track in info.audio:
        language = track.language or "und"
        if language in seen or "commentary" in (track.title or "").lower():
            continue
        seen.add(language)
        kept.append(track.index)
    return kept


def kept_audio(info: MediaInfo) -> list[int]:
    default = info.default_audio()
    return ([default.index] if default else []) + extra_audio(info)


def peek_session(info: MediaInfo, audio_index: int | None) -> Session | None:
    audio_index = _normal(info, audio_index)
    existing = _sessions.get(cache_key(info.path, audio_index))
    if existing:
        return existing
    candidate = Session(info, audio_index)
    return candidate if candidate.complete else None


async def ensure_session(info: MediaInfo, audio_index: int | None) -> Session:
    audio_index = _normal(info, audio_index)
    key = cache_key(info.path, audio_index)
    async with _session_lock:
        existing = _sessions.get(key)
        if existing and (existing.running or existing.complete):
            return existing

        session = Session(info, audio_index)
        if session.complete:
            _sessions[key] = session
            return session
        if not os.path.exists(info.path):
            raise SourceGone("that audio track was not kept when the source was removed")
        await session.start()
        _sessions[key] = session
        return session


async def wait_for_file(path: str, timeout: float = 90.0) -> bool:
    """Players request slightly ahead of muxing; a 404 would make them abandon the stream."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            await asyncio.sleep(0.05)  # let the writer finish flushing
            return True
        await asyncio.sleep(0.25)
    return False


def master_playlist(
    info: MediaInfo, base_url: str, subtitle_tracks: list[dict] | None = None,
    query: str = "",
) -> str:
    video = info.video
    width = video.width if video else 1920
    height = video.height if video else 1080
    bandwidth = info.bitrate or (18_000_000 if height > 1440 else 6_000_000)
    codec_tag = "hvc1.2.4.L153.B0" if (video and video.codec == "hevc") else "avc1.640028"
    # Apple clients refuse an HDR variant without VIDEO-RANGE (CoreMediaErrorDomain
    # -12927) or FRAME-RATE (-12646), before fetching any video.
    video_range = video.video_range if video else "SDR"
    frame_rate = video.frame_rate if video else None

    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS"]

    group = ""
    for track in subtitle_tracks or []:
        group = "subs"
        lines.append(
            '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
            f'NAME="{track["label"]}",LANGUAGE="{track.get("language") or "und"}",'
            f'DEFAULT={"YES" if track.get("default") else "NO"},'
            f'FORCED={"YES" if track.get("forced") else "NO"},AUTOSELECT=YES,'
            f'URI="{base_url}/subs/{track["id"]}.m3u8"'
        )

    stream_inf = (
        f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
        f"RESOLUTION={width}x{height},"
        f"VIDEO-RANGE={video_range},"
        f'CODECS="{codec_tag},mp4a.40.2"'
    )
    if frame_rate:
        stream_inf += f",FRAME-RATE={frame_rate:.3f}"
    if group:
        stream_inf += f',SUBTITLES="{group}"'
    lines.append(stream_inf)
    lines.append(f"{base_url}/index.m3u8{query}")
    return "\n".join(lines) + "\n"


def sweep_cache() -> None:
    """NOT CALLED: evicting a prepared download's rendition removes the title from the library."""
    if not os.path.isdir(CACHE_ROOT):
        return

    renditions: list[tuple[float, int, str]] = []
    total = 0
    active = {s.dir for s in _sessions.values() if s.running}

    for name in os.listdir(CACHE_ROOT):
        target = os.path.join(CACHE_ROOT, name)
        if not os.path.isdir(target):
            continue
        size = 0
        newest = 0.0
        for root, _dirs, files in os.walk(target):
            for fname in files:
                try:
                    st = os.stat(os.path.join(root, fname))
                except OSError:
                    continue
                size += st.st_size
                newest = max(newest, st.st_mtime)
        total += size
        if target not in active:
            renditions.append((newest, size, target))

    if total <= MAX_CACHE_BYTES:
        return

    for _mtime, size, target in sorted(renditions):
        if total <= MAX_CACHE_BYTES:
            break
        shutil.rmtree(target, ignore_errors=True)
        total -= size
        log.info("swept HLS rendition %s (%.1f GB)", target, size / 1024 ** 3)


def clear_for(path: str) -> None:
    """Folders are hashed by path and audio stream index, so every plausible index is tried."""
    from .mediainfo import cached_info

    info = cached_info(path)
    indexes = {None, *range(0, 64), *(a.index for a in (info.audio if info else []))}
    for key, session in list(_sessions.items()):
        if session.info.path == path:
            _sessions.pop(key, None)
            session.stop()
    for audio in indexes:
        target = _session_dir(cache_key(path, audio))
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
