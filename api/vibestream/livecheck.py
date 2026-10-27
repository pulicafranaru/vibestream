"""Checks that live remux serves the source's video packets bit for bit.

Usage: python -m vibestream.livecheck FILE.mkv [--seeks 40] [--audio N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import subprocess
import sys
import tempfile
import time

from .services import live, mediainfo
from .services.mediainfo import FFPROBE

# Longest tolerated audio hole, in seconds (an AAC frame is 21ms).
AUDIO_GAP = 0.05
AUDIO_LATE = 0.1
# The muxer cuts at the keyframe in decode order, so with B-frames the
# last fraction of a second of audio travels with the next segment.
AUDIO_TAIL = 0.35


def _packets(args: list[str], data: bytes | None = None) -> list[tuple[float, str, str, str]]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", *args,
         "-show_entries", "packet=pts_time,duration_time,flags,data_hash",
         "-show_data_hash", "MD5", "-of", "csv=p=0"],
        input=data, capture_output=True, check=True,
    ).stdout.decode()
    rows = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) < 4 or parts[0] in ("", "N/A"):
            continue
        rows.append((float(parts[0]), _seconds(parts[1]), parts[2], parts[3]))
    return rows


def _seconds(raw: str) -> float:
    """ffmpeg 7.1 leaves some durations unset; one AAC frame at 48kHz is assumed."""
    try:
        return float(raw)
    except ValueError:
        return 1024 / 48000


def served_packets(data: bytes, kind: str) -> list[tuple[float, str, str, str]]:
    return _packets(["-select_streams", f"{kind}:0", "-i", "pipe:0"], data)


def source_video(path: str, begin: float, end: float | None) -> list[str]:
    """Stored order, not display order: an open GOP's leading pictures belong with the keyframe's piece."""
    until = (end if end is not None else begin + 100000) + 15
    rows = _packets(["-read_intervals", f"{max(0.0, begin - 15):.3f}%{until:.3f}",
                     "-select_streams", "v:0", path])

    def at(t: float) -> int | None:
        return next((i for i, r in enumerate(rows)
                     if r[2].startswith("K") and abs(r[0] - t) < 0.0005), None)

    first = at(begin)
    last = at(end) if end is not None else len(rows)
    if first is None or last is None:
        return []
    return [r[3] for r in rows[first:last]]


def check_segment(path: str, index: live.Index, segment: live.Segment,
                  data: bytes, audio: bool = True) -> list[str]:
    problems = []
    a, b = segment.first, segment.end
    begin = index.keyframes[a]
    end = index.keyframes[b] if b < len(index.keyframes) else None
    source = source_video(path, begin, end)
    video = served_packets(data, "v")
    if [r[3] for r in video] != source or not source:
        problems.append(
            f"segment {a}-{b}: video differs, served {len(video)} packets "
            f"from {video[0][0] + index.start if video else None}, source has "
            f"{len(source)} from {begin}"
        )
    if video and abs(video[0][0] + index.start - begin) > live.LANDING_TOLERANCE:
        problems.append(f"segment {a}-{b}: starts at {video[0][0] + index.start:.3f}, "
                        f"its keyframe is at {begin:.3f}")
    if audio:
        sound = served_packets(data, "a")
        if not sound:
            problems.append(f"segment {a}-{b}: no audio")
        else:
            first = sound[0][0] + index.start
            last = sound[-1][0] + sound[-1][1] + index.start
            if first > begin + AUDIO_LATE:
                problems.append(f"segment {a}-{b}: audio starts {first - begin:.3f}s late")
            if end is not None and last < end - AUDIO_TAIL:
                problems.append(f"segment {a}-{b}: audio ends {end - last:.3f}s early")
            hole = _hole(sound)
            if hole:
                problems.append(f"segment {a}-{b}: {hole}")
    return problems


def _hole(sound) -> str | None:
    for (p, d, _f, _h), (q, _e, _g, _i) in zip(sound, sound[1:]):
        if q - (p + d) > AUDIO_GAP:
            return f"audio hole of {q - p - d:.3f}s at {p + d:.3f}"
    return None


def seam(before: bytes, after: bytes) -> str | None:
    one = served_packets(before, "a")
    two = served_packets(after, "a")
    if not one or not two:
        return None
    end = one[-1][0] + one[-1][1]
    if two[0][0] - end > AUDIO_GAP:
        return f"audio hole of {two[0][0] - end:.3f}s at {end:.3f}"
    return None


async def fetch(stream: live.Stream, n: int) -> bytes:
    init = await live.init_file(stream.path, stream.audio)
    for attempt in range(5):
        try:
            pieces = await live.segment_files(stream, n)
            break
        except live.Superseded:
            if attempt == 4:
                raise
    _total, parts = live.joined(pieces)
    with open(init, "rb") as fh:
        data = fh.read()
    return data + b"".join(live.read_joined(parts, pieces.adjust))


async def run(path: str, seeks: int, audio: int | None, sequential: int) -> int:
    started = time.monotonic()
    live.reset_state()
    index = live.load_index(path) or await live.build_index(path)
    with_audio = audio is not None or _has_audio(path)
    print(f"{os.path.basename(path)}: {len(index.keyframes)} keyframes, "
          f"indexed in {time.monotonic() - started:.1f}s")
    stream = await live.stream_for(path, audio, live.new_token(), index)
    segments = stream.segments
    rng = random.Random(len(index.keyframes))
    order = rng.sample(range(len(segments)), min(seeks, len(segments)))
    straight = rng.randrange(0, max(1, len(segments) - sequential))
    order += list(range(straight, min(len(segments), straight + sequential)))
    order += [max(0, straight - 3), len(segments) - 1]
    problems = 0
    for n in order:
        t = time.monotonic()
        data = await fetch(stream, n)
        found = check_segment(path, index, segments[n], data, with_audio)
        problems += len(found)
        print(f"  segment {n:5d} ({segments[n].start:8.2f}s, {len(data) / 1e6:6.1f} MB) "
              f"in {time.monotonic() - t:5.2f}s {'OK' if not found else found}")
    await live.forget(stream)
    print(f"{problems} problem(s) in {len(order)} segments")
    return problems


def _has_audio(path: str) -> bool:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True).stdout
    return bool(out.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--seeks", type=int, default=30)
    parser.add_argument("--sequential", type=int, default=15)
    parser.add_argument("--audio", type=int, default=None)
    args = parser.parse_args()
    scratch = tempfile.mkdtemp(prefix="livecheck-")
    live.ROOT = scratch
    live.INIT_ROOT = os.path.join(scratch, "init")
    live.STREAMS_ROOT = os.path.join(scratch, "streams")
    live.PROBE_CACHE = scratch
    mediainfo.PROBE_CACHE = scratch
    total = 0
    try:
        for path in args.paths:
            total += asyncio.run(run(path, args.seeks, args.audio, args.sequential))
    finally:
        subprocess.run(["rm", "-rf", scratch])
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
