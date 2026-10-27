"""Trickplay thumbnails: scrubber previews in sprite sheets, with a manifest.

Frame times are read back from showinfo, because the fps filter's slots do not
match seek positions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import shutil
import statistics
import time

from .mediainfo import FFMPEG, FFPROBE, MediaInfo

log = logging.getLogger(__name__)

CACHE_ROOT = os.environ.get("VIBESTREAM_THUMB_CACHE", "/app/data/thumbs")
MANIFEST_NAME = "index.json"

TARGET_THUMBS = 600
MIN_INTERVAL = 5
MAX_INTERVAL = 20

COLUMNS = 8
ROWS = 8
PER_SHEET = COLUMNS * ROWS

# 256px wide: a full sheet decodes to about 9MB, so webOS can hold the few
# around the cursor.
THUMB_WIDTH = 256
JPEG_QUALITY = 6  # ffmpeg -qscale:v, 2 best .. 31 worst


def cache_key(path: str) -> str:
    """Keyed on the file only: thumbnails do not depend on the audio track."""
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def interval_for(duration: float) -> int:
    if not duration or duration <= 0:
        return MIN_INTERVAL
    return max(MIN_INTERVAL, min(MAX_INTERVAL, math.ceil(duration / TARGET_THUMBS)))


class Job:
    def __init__(self, info: MediaInfo):
        self.info = info
        self.key = cache_key(info.path)
        self.dir = os.path.join(CACHE_ROOT, self.key)
        self.interval = interval_for(info.duration)
        self.count = max(1, math.ceil((info.duration or 0) / self.interval))
        self.sheets = max(1, math.ceil(self.count / PER_SHEET))
        self.proc: asyncio.subprocess.Process | None = None
        self.started_at = 0.0
        self.error: str | None = None

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.dir, MANIFEST_NAME)

    @property
    def ready(self) -> bool:
        """The manifest is the readiness marker, and it is written last."""
        return os.path.exists(self.manifest_path)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def sheet_path(self, index: int) -> str:
        return os.path.join(self.dir, f"sheet{index + 1:04d}.jpg")

    def manifest(self) -> dict | None:
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def progress(self) -> dict:
        written = 0
        try:
            written = len([n for n in os.listdir(self.dir) if n.endswith(".jpg")])
        except OSError:
            pass
        return {
            "ready": self.ready,
            "running": self.running,
            "percent": round(min(99.0, written / self.sheets * 100), 1),
            "error": self.error,
        }

    def _args(self) -> list[str]:
        # The first frame, then the next at least `interval` after the last taken. showinfo
        # right behind it logs the frames' own timestamps, before tiling loses them.
        select = (
            f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{self.interval})'"
        )
        chain = (
            f"{select},showinfo,"
            f"scale={THUMB_WIDTH}:-2,"
            f"tile={COLUMNS}x{ROWS}"
        )
        return [
            FFMPEG, "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", "-y",
            # Before -i: an input option, so the decoder itself skips non-keyframes.
            "-skip_frame", "nokey",
            "-i", self.info.path,
            "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", chain,
            "-fps_mode", "passthrough",
            "-qscale:v", str(JPEG_QUALITY),
            os.path.join(self.dir, "sheet%04d.jpg"),
        ]

    async def run(self) -> None:
        os.makedirs(self.dir, exist_ok=True)
        # Start clean: a killed run's leftover sheets would make the manifest's sheet
        # count wrong.
        for name in os.listdir(self.dir):
            if name.endswith(".jpg"):
                try:
                    os.remove(os.path.join(self.dir, name))
                except OSError:
                    pass
        self.started_at = time.monotonic()
        log.info(
            "generating trickplay for %s (>=%ss apart, ~%d thumbs)",
            os.path.basename(self.info.path), self.interval, self.count,
        )
        self.proc = await asyncio.create_subprocess_exec(
            *self._args(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Read as it goes: hundreds of showinfo lines would fill the pipe and deadlock ffmpeg.
        times: list[float] = []
        tail: list[str] = []
        pattern = re.compile(rb"pts_time:(-?[0-9.]+)")
        while True:
            try:
                line = await self.proc.stderr.readline()
            except (ValueError, asyncio.LimitOverrunError):
                continue  # one absurdly long log line is not worth failing over
            if not line:
                break
            found = pattern.search(line)
            if found:
                try:
                    times.append(round(float(found.group(1)), 2))
                except ValueError:
                    pass
            elif len(tail) < 40:
                tail.append(line.decode("utf-8", "replace").rstrip())

        code = await self.proc.wait()
        if code != 0:
            self.error = "\n".join(tail)[:400]
            log.error("trickplay failed for %s: %s", self.info.path, self.error)
            return

        tile = await _tile_size(self.sheet_path(0))
        if tile is None or not times:
            self.error = "no sheets were produced"
            log.error("trickplay produced nothing for %s", self.info.path)
            return

        produced = len([n for n in os.listdir(self.dir) if n.endswith(".jpg")])
        # Selection lands on keyframes, so the real spacing is measured, not assumed.
        # The D-pad uses it as its step.
        gaps = [b - a for a, b in zip(times, times[1:])]
        spacing = round(statistics.median(gaps), 3) if gaps else float(self.interval)

        payload = {
            "ready": True,
            "interval": spacing,
            "count": len(times),
            "times": times,
            "sheets": produced,
            "per_sheet": PER_SHEET,
            "columns": COLUMNS,
            "rows": ROWS,
            "tile_width": tile[0],
            "tile_height": tile[1],
            "duration": round(self.info.duration or 0, 3),
        }
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        log.info(
            "trickplay ready for %s in %.0fs (%d thumbs every ~%.1fs, %d sheets)",
            os.path.basename(self.info.path), time.monotonic() - self.started_at,
            len(times), spacing, produced,
        )


async def _tile_size(sheet: str) -> tuple[int, int] | None:
    """Tile dimensions, read back from a real sheet: scale=W:-2 rounds the height."""
    if not os.path.exists(sheet):
        return None
    proc = await asyncio.create_subprocess_exec(
        FFPROBE, "-v", "error", "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x", sheet,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        width, height = (int(v) for v in out.decode().strip().split("x")[:2])
    except (ValueError, AttributeError):
        return None
    return width // COLUMNS, height // ROWS


_jobs: dict[str, Job] = {}
_lock = asyncio.Lock()


def peek(info: MediaInfo) -> Job | None:
    existing = _jobs.get(cache_key(info.path))
    if existing:
        return existing
    candidate = Job(info)
    return candidate if candidate.ready else None


async def ensure(info: MediaInfo) -> Job:
    key = cache_key(info.path)
    async with _lock:
        existing = _jobs.get(key)
        if existing and (existing.running or existing.ready):
            return existing

        job = Job(info)
        if job.ready:
            _jobs[key] = job
            return job
        _jobs[key] = job
        asyncio.create_task(job.run())
        return job


async def generate_now(info: MediaInfo) -> Job:
    job = await ensure(info)
    while job.running:
        await asyncio.sleep(2)
    return job


def clear_for(path: str) -> None:
    key = cache_key(path)
    job = _jobs.pop(key, None)
    if job and job.running and job.proc:
        job.proc.kill()
    target = os.path.join(CACHE_ROOT, key)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)


def manifest_path_for(path: str) -> str:
    """Where the manifest for a source file lives. Use this rather than guessing the name."""
    return os.path.join(CACHE_ROOT, cache_key(path), MANIFEST_NAME)
