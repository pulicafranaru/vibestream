"""Cutting a saved moment out of a rendition (or the source of a live title), video copied."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess

from . import hls, mediainfo

CLIPS_DIR = os.environ.get("VIBESTREAM_CLIPS_DIR", "/app/data/clips")
MAX_SECONDS = 120.0
MIN_SECONDS = 2.0


class ClipError(RuntimeError):
    pass


class ClipUnavailable(ClipError):
    """Nothing is left to cut from: no rendition and no source."""


def video_path(clip_id: int) -> str:
    return os.path.join(CLIPS_DIR, f"{clip_id}.mp4")


def thumb_path(clip_id: int) -> str:
    return os.path.join(CLIPS_DIR, f"{clip_id}.jpg")


async def _run(args: list[str], timeout: float) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ClipError("cutting the clip took too long") from None
    if proc.returncode != 0:
        raise ClipError(err.decode("utf-8", "replace")[:300])


def _segments(playlist: str) -> tuple[str, list[tuple[float, float, str]]]:
    folder = os.path.dirname(playlist)
    init, segments, at, length = None, [], 0.0, None
    with open(playlist, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("#EXT-X-MAP:") and 'URI="' in line:
                init = os.path.join(folder, line.split('URI="', 1)[1].split('"', 1)[0])
            elif line.startswith("#EXTINF:"):
                length = float(line[8:].split(",", 1)[0])
            elif line and not line.startswith("#") and length is not None:
                segments.append((at, at + length, os.path.join(folder, line)))
                at += length
                length = None
    if init is None or not segments:
        raise ClipError("the rendition's playlist could not be read")
    return init, segments


async def cut(clip_id: int, info: mediainfo.MediaInfo, start: float, end: float) -> float:
    """Write the clip and its thumbnail, and return its measured length. Raises ClipError.

    Segments are joined behind the init segment by hand: ffmpeg's HLS reader, started part way in, drops the init.
    """
    playlist = hls.playlist_path_for(info.path, None)
    has_rendition = os.path.exists(playlist)
    if not has_rendition and not os.path.exists(info.path):
        raise ClipUnavailable("this title has neither a rendition nor a source to clip from")
    os.makedirs(CLIPS_DIR, exist_ok=True)
    target = video_path(clip_id)
    joined = target + ".src.mp4"
    partial = target + ".part.mp4"
    tag = ["-tag:v", "hvc1"] if info.video and info.video.codec == "hevc" else []
    try:
        if has_rendition:
            await _from_rendition(playlist, joined, partial, tag, start, end)
        else:
            await _from_source(info, partial, tag, start, end)
        os.replace(partial, target)
        await _run([
            mediainfo.FFMPEG, "-nostdin", "-v", "error", "-y",
            "-ss", f"{min(1.0, (end - start) / 2):.3f}", "-i", target,
            "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", thumb_path(clip_id),
        ], timeout=60)
    finally:
        for leftover in (joined, partial):
            if os.path.exists(leftover):
                os.remove(leftover)
    return await asyncio.to_thread(length, clip_id) or (end - start)


async def _from_rendition(playlist: str, joined: str, partial: str, tag: list[str],
                          start: float, end: float) -> None:
    init, segments = _segments(playlist)
    covering = [seg for seg in segments if seg[1] > start and seg[0] < end]
    if not covering:
        raise ClipError("that moment is past the end of the title")
    with open(joined, "wb") as out:
        for path in [init, *(seg[2] for seg in covering)]:
            with open(path, "rb") as part:
                out.write(part.read())
    offset = max(0.0, start - covering[0][0])
    await _run([
        mediainfo.FFMPEG, "-nostdin", "-v", "error", "-y",
        "-ss", f"{offset:.3f}", "-i", joined, "-t", f"{end - start:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", *tag,
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart", partial,
    ], timeout=120)


async def _from_source(info: mediainfo.MediaInfo, partial: str, tag: list[str],
                       start: float, end: float) -> None:
    """Audio is made stereo AAC: a source's TrueHD or DTS would not play on a phone."""
    if start >= info.duration > 0:
        raise ClipError("that moment is past the end of the title")
    audio = info.default_audio()
    await _run([
        mediainfo.FFMPEG, "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-i", info.path, "-t", f"{end - start:.3f}",
        "-map", "0:v:0", *(["-map", f"0:{audio.index}"] if audio else []),
        "-c:v", "copy", *tag, "-c:a", "aac", "-ac", "2", "-b:a", "192k", "-sn", "-dn",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart", partial,
    ], timeout=120)


def length(clip_id: int) -> float | None:
    try:
        out = subprocess.run(
            [mediainfo.FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path(clip_id)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out) if out else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def picture_path(clip_id: int) -> str:
    return os.path.join(CLIPS_DIR, f"{clip_id}.picture.json")


def picture(clip_id: int) -> dict | None:
    """Fraction of the frame that is picture (width, height), found with cropdetect."""
    cache = picture_path(clip_id)
    try:
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass
    source = video_path(clip_id)
    if not os.path.exists(source):
        return None
    try:
        size = subprocess.run(
            [mediainfo.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", source],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip().split(",")
        width, height = int(size[0]), int(size[1])
        found = subprocess.run(
            [mediainfo.FFMPEG, "-nostdin", "-hide_banner", "-i", source,
             "-vf", "fps=1/3,scale=640:-2,cropdetect=limit=24:round=2:reset=0",
             "-frames:v", "12", "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        ).stderr
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    crops = re.findall(r"crop=(\d+):(\d+):\d+:\d+", found)
    if not crops or not width or not height:
        return None
    scaled = 640 / width
    seen_w, seen_h = (int(v) for v in crops[-1])
    result = {
        "width": round(min(1.0, seen_w / (width * scaled)), 4),
        "height": round(min(1.0, seen_h / (height * scaled)), 4),
    }
    # A mostly black scene reads as a tiny picture; trust it only down to the
    # widest film shape there is.
    if result["height"] < 0.6 or result["width"] < 0.6:
        result = {"width": 1.0, "height": 1.0}
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return result


def vertical_path(clip_id: int) -> str:
    return os.path.join(CLIPS_DIR, f"{clip_id}.vertical.json")


def remove(clip_id: int) -> None:
    for path in (video_path(clip_id), thumb_path(clip_id), picture_path(clip_id),
                 vertical_path(clip_id)):
        try:
            os.remove(path)
        except OSError:
            pass
