"""Episode stills taken from the video, for episodes TMDB has none for.

Without the source, init.mp4 and one HLS segment are piped in together:
ffmpeg's playlist reader misreads these fragmented segments.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass

from ..models import Episode
from . import hls
from .mediainfo import FFMPEG
from .tmdb import still_url

log = logging.getLogger(__name__)

STILLS_ROOT = os.environ.get("VIBESTREAM_STILL_CACHE", "/app/data/stills")
FFPROBE = os.environ.get("VIBESTREAM_FFPROBE", "ffprobe")
CANDIDATES = 24
FIRST, LAST = 0.08, 0.72
MEASURE_WIDTH = 480
STILL_WIDTH = 1280

# HDR, PQ or HLG, to SDR: linear light, BT.709 primaries, Hable's curve.
TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
)

# Episodes that already failed, so the backfill skips them. Forgotten on restart.
_failed: set[int] = set()


def still_path(episode_id: int) -> str:
    return os.path.join(STILLS_ROOT, f"e{episode_id}.jpg")


def episode_still(episode: Episode) -> str | None:
    """The still for an episode, versioned by its time so caches do not serve an old one."""
    if episode.still_path:
        return still_url(episode.still_path)
    path = still_path(episode.id)
    try:
        version = int(os.path.getmtime(path))
    except OSError:
        return None
    return f"/api/catalog/episodes/{episode.id}/still.jpg?v={version}"


@dataclass
class Frame:
    time: float
    luma: float        # average, 0..255
    low: float         # 10th percentile
    high: float        # 90th percentile
    saturation: float  # average
    entropy: float     # normalised, 0..1
    blur: float        # blurdetect, higher is blurrier
    left: float = 0.0
    top: float = 0.0
    width: float = 1.0
    height: float = 1.0


def score(frame: Frame) -> float:
    if frame.luma < 18:
        return -1.0
    coverage = max(0.0, min(1.0, frame.width * frame.height)) ** 0.5
    contrast = max(0.0, frame.high - frame.low) / 255
    exposure = 1 - min(1.0, abs(frame.luma - 118) / 118)
    colour = 0.7 + 0.3 * min(frame.saturation, 40) / 40
    sharpness = 1 / (1 + max(0.0, frame.blur - 2) / 3)
    return frame.entropy * (0.4 + contrast) * (0.3 + exposure) * colour * sharpness * coverage


def candidate_times(duration: float) -> list[float]:
    if duration <= 0:
        return []
    step = (LAST - FIRST) / (CANDIDATES - 1)
    return [duration * (FIRST + step * i) for i in range(CANDIDATES)]


def parse_metadata(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        try:
            values[key.strip()] = float(value)
        except ValueError:
            continue
    return values


@dataclass
class Segment:
    start: float
    duration: float
    path: str


class Source:
    def __init__(self, path: str):
        self.path = path
        self.file = path if os.path.exists(path) else None
        self.segments: list[Segment] = []
        self.init: str | None = None
        if self.file is None:
            self._read_playlist(hls.playlist_path_for(path))
        self.duration = 0.0
        self.hdr = False

    def _read_playlist(self, playlist: str) -> None:
        try:
            with open(playlist, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return
        folder = os.path.dirname(playlist)
        at, pending = 0.0, None
        for line in lines:
            if line.startswith("#EXT-X-MAP:") and 'URI="' in line:
                self.init = os.path.join(folder, line.split('URI="', 1)[1].split('"', 1)[0])
            elif line.startswith("#EXTINF:"):
                try:
                    pending = float(line[8:].split(",", 1)[0])
                except ValueError:
                    pending = None
            elif line and not line.startswith("#") and pending is not None:
                self.segments.append(Segment(at, pending, os.path.join(folder, line)))
                at += pending
                pending = None

    @property
    def usable(self) -> bool:
        return self.file is not None or bool(self.segments and self.init)

    async def load(self) -> None:
        if self.file is None:
            self.duration = sum(s.duration for s in self.segments)
            stream = await self._probe(self._piece(self.segments[0]) if self.segments else b"")
        else:
            stream = await self._probe(None)
            try:
                self.duration = float(stream.get("duration") or 0) or await self._file_duration()
            except ValueError:
                self.duration = await self._file_duration()
        transfer = (stream.get("color_transfer") or "").lower()
        self.hdr = transfer in ("smpte2084", "arib-std-b67")

    async def _file_duration(self) -> float:
        out, _ = await _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                             "-of", "json", self.file or ""], None)
        try:
            return float(json.loads(out or b"{}").get("format", {}).get("duration") or 0)
        except ValueError:
            return 0.0

    async def _probe(self, data: bytes | None) -> dict:
        target = "pipe:0" if data is not None else (self.file or "")
        out, _ = await _run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=color_transfer,duration", "-of", "json", target], data)
        try:
            streams = json.loads(out or b"{}").get("streams") or []
        except ValueError:
            streams = []
        return streams[0] if streams else {}

    def _piece(self, segment: Segment) -> bytes:
        with open(self.init or "", "rb") as head, open(segment.path, "rb") as body:
            return head.read() + body.read()

    def input_for(self, time: float) -> tuple[list[str], bytes | None]:
        if self.file is not None:
            # Before -i, without accurate seeking: the keyframe at or before the time.
            return ["-noaccurate_seek", "-ss", f"{time:.3f}", "-i", self.file], None
        segment = next((s for s in self.segments if s.start + s.duration > time), self.segments[-1])
        return ["-i", "pipe:0"], self._piece(segment)


async def _run(args: list[str], data: bytes | None) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        return await asyncio.wait_for(proc.communicate(data), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return b"", b"timed out"


async def _measure(source: Source, time: float) -> Frame | None:
    tone = TONEMAP if source.hdr else ""
    inputs, data = source.input_for(time)
    chain = (f"scale={MEASURE_WIDTH}:-2,{tone}format=yuv420p,"
             "signalstats,entropy,blurdetect,cropdetect=limit=24:round=2:reset=1:skip=0,"
             "metadata=print:file=-")
    out, _ = await _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *inputs,
                         "-map", "0:v:0", "-frames:v", "1", "-vf", chain, "-f", "null", "/dev/null"],
                        data)
    values = parse_metadata(out.decode("utf-8", "replace"))
    if "lavfi.signalstats.YAVG" not in values:
        return None
    picture = crop_of(values)
    return Frame(
        time=time,
        luma=values["lavfi.signalstats.YAVG"],
        low=values.get("lavfi.signalstats.YLOW", 0.0),
        high=values.get("lavfi.signalstats.YHIGH", 255.0),
        saturation=values.get("lavfi.signalstats.SATAVG", 0.0),
        entropy=values.get("lavfi.entropy.normalized_entropy.normal.Y", 0.0),
        blur=values.get("lavfi.blur", 0.0),
        **picture,
    )


def crop_of(values: dict[str, float]) -> dict[str, float]:
    whole = {"left": 0.0, "top": 0.0, "width": 1.0, "height": 1.0}
    try:
        frame_w = values["lavfi.cropdetect.x2"] + values["lavfi.cropdetect.x1"]
        w, h = values["lavfi.cropdetect.w"], values["lavfi.cropdetect.h"]
        x, y = values["lavfi.cropdetect.x"], values["lavfi.cropdetect.y"]
        frame_h = values["lavfi.cropdetect.y2"] + values["lavfi.cropdetect.y1"]
    except KeyError:
        return whole
    if frame_w <= 0 or frame_h <= 0 or w < frame_w * 0.4 or h < frame_h * 0.4:
        return whole
    # x2 and y2 are inclusive: the frame is one wider than their sum less x1.
    frame_w = max(frame_w, x + w)
    frame_h = max(frame_h, y + h)
    return {"left": x / frame_w, "top": y / frame_h,
            "width": min(1.0, w / frame_w), "height": min(1.0, h / frame_h)}


def fill_chain(frame: Frame) -> str:
    crop = ""
    if frame.width < 0.98 or frame.height < 0.98:
        crop = (f"crop=iw*{frame.width:.4f}:ih*{frame.height:.4f}:"
                f"iw*{frame.left:.4f}:ih*{frame.top:.4f},")
    return (f"{crop}crop='min(iw,ih*16/9)':'min(ih,iw*9/16)',"
            f"scale={STILL_WIDTH}:{STILL_WIDTH * 9 // 16}")


async def _write(source: Source, frame: Frame, destination: str) -> bool:
    tone = TONEMAP if source.hdr else ""
    inputs, data = source.input_for(frame.time)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = destination + ".part.jpg"
    await _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *inputs,
                "-map", "0:v:0", "-frames:v", "1",
                "-vf", f"{fill_chain(frame)},{tone}format=yuvj420p",
                "-q:v", "3", temporary], data)
    if not os.path.exists(temporary) or os.path.getsize(temporary) == 0:
        return False
    os.replace(temporary, destination)
    return True


async def make(episode_id: int, path: str) -> bool:
    destination = still_path(episode_id)
    if os.path.exists(destination):
        return True
    source = Source(path)
    if not source.usable:
        return False
    await source.load()
    frames = []
    for time in candidate_times(source.duration):
        frame = await _measure(source, time)
        if frame is not None:
            frames.append(frame)
    if not frames:
        return False
    best = max(frames, key=score)
    if score(best) < 0:
        return False
    made = await _write(source, best, destination)
    if made:
        log.info("made a still for episode %s from %.0fs (score %.3f)", episode_id, best.time, score(best))
    return made


async def ensure(episode_id: int, path: str) -> None:
    if episode_id in _failed:
        return
    try:
        if not await make(episode_id, path):
            _failed.add(episode_id)
    except Exception:  # noqa: BLE001 - a missing picture must not break anything
        log.exception("could not make a still for episode %s", episode_id)
        _failed.add(episode_id)


async def backfill(limit: int = 6) -> int:
    from sqlalchemy import select

    from ..db import session_scope
    from .preparation import _resolve_path
    from ..models import Download

    with session_scope() as session:
        rows = session.scalars(
            select(Episode).where(
                Episode.file_path.is_not(None),
                Episode.prepared_at.is_not(None),
                Episode.still_path.is_(None),
            )
        ).all()
        wanted = []
        for episode in rows:
            if episode.id in _failed or os.path.exists(still_path(episode.id)):
                continue
            download = session.get(Download, episode.download_id) if episode.download_id else None
            path = _resolve_path(download, episode) if download else episode.file_path
            if path:
                wanted.append((episode.id, path))
            if len(wanted) >= limit:
                break
    for episode_id, path in wanted:
        await ensure(episode_id, path)
    return len(wanted)
