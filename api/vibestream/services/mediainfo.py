"""ffprobe wrapper: what is actually inside a file."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

FFPROBE = os.environ.get("VIBESTREAM_FFPROBE", "ffprobe")
FFMPEG = os.environ.get("VIBESTREAM_FFMPEG", "ffmpeg")

# Codecs an LG webOS TV browser decodes in hardware.
WEBOS_VIDEO = {"h264", "hevc", "vp9", "av1", "mpeg2video"}
WEBOS_AUDIO = {"aac", "mp3", "ac3", "eac3", "opus", "vorbis", "flac"}
# Formats a browser will not render. Re-encoded to AAC, never forcing a video transcode.
AUDIO_NEEDS_ENCODE = {"dts", "truehd", "mlp", "pcm_s16le", "pcm_s24le", "pcm_bluray"}

TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
# Bitmap subtitles cannot be converted to WebVTT.
IMAGE_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


class ProbeError(RuntimeError):
    pass


@dataclass
class VideoStream:
    index: int
    codec: str
    profile: str | None
    width: int
    height: int
    pix_fmt: str | None
    bit_depth: int
    frame_rate: float | None
    is_hdr: bool
    is_dolby_vision: bool
    color_transfer: str | None = None

    @property
    def video_range(self) -> str:
        """SDR, PQ or HLG, in the spelling EXT-X-STREAM-INF uses."""
        transfer = (self.color_transfer or "").lower()
        if transfer == "arib-std-b67":
            return "HLG"
        if transfer == "smpte2084" or self.is_hdr:
            return "PQ"
        return "SDR"

    @property
    def resolution_label(self) -> str:
        """By width, not height: a letterboxed 1080p film is 1920x800."""
        if self.width >= 3000 or self.height >= 1700:
            return "2160p"
        if self.width >= 1800 or self.height >= 1000:
            return "1080p"
        if self.width >= 1200 or self.height >= 700:
            return "720p"
        if self.width >= 900:
            return "576p"
        return f"{self.height}p" if self.height else "unknown"


@dataclass
class AudioStream:
    index: int
    codec: str
    channels: int
    language: str | None
    title: str | None
    is_default: bool

    @property
    def label(self) -> str:
        parts = [(self.language or "und").upper(), self.codec.upper()]
        if self.channels:
            parts.append(
                {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}.get(
                    self.channels, f"{self.channels}ch"
                )
            )
        if self.title:
            parts.append(self.title)
        return " ".join(parts)


@dataclass
class SubtitleStream:
    index: int
    codec: str
    language: str | None
    title: str | None
    is_default: bool
    is_forced: bool
    is_hearing_impaired: bool

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_SUBTITLE_CODECS

    @property
    def is_image(self) -> bool:
        return self.codec in IMAGE_SUBTITLE_CODECS

    @property
    def label(self) -> str:
        name = (self.language or "und").upper()
        if self.title:
            name = f"{name} {self.title}"
        if self.is_forced:
            name += " (Forced)"
        if self.is_hearing_impaired:
            name += " (SDH)"
        return name


@dataclass
class MediaInfo:
    path: str
    duration: float
    container: str
    bitrate: int
    video: VideoStream | None = None
    audio: list[AudioStream] = field(default_factory=list)
    subtitles: list[SubtitleStream] = field(default_factory=list)

    @property
    def needs_video_transcode(self) -> bool:
        return bool(self.video and self.video.codec not in WEBOS_VIDEO)

    def audio_needs_encode(self, index: int | None = None) -> bool:
        track = self._audio_by_index(index)
        if track is None:
            return False
        return track.codec not in WEBOS_AUDIO

    def _audio_by_index(self, index: int | None) -> AudioStream | None:
        if index is not None:
            for track in self.audio:
                if track.index == index:
                    return track
        for track in self.audio:
            if track.is_default:
                return track
        return self.audio[0] if self.audio else None

    def default_audio(self) -> AudioStream | None:
        return self._audio_by_index(None)


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_frame_rate(raw: str | None) -> float | None:
    if not raw or "/" not in raw:
        return None
    num, _, den = raw.partition("/")
    try:
        n, d = float(num), float(den)
        return round(n / d, 3) if d else None
    except ValueError:
        return None


def _bit_depth(stream: dict) -> int:
    explicit = _to_int(stream.get("bits_per_raw_sample"))
    if explicit:
        return explicit
    pix_fmt = (stream.get("pix_fmt") or "").lower()
    if "p10" in pix_fmt or "10le" in pix_fmt or "10be" in pix_fmt:
        return 10
    if "p12" in pix_fmt or "12le" in pix_fmt:
        return 12
    return 8


def _detect_hdr(stream: dict) -> tuple[bool, bool]:
    transfer = (stream.get("color_transfer") or "").lower()
    primaries = (stream.get("color_primaries") or "").lower()
    hdr = transfer in ("smpte2084", "arib-std-b67") or primaries == "bt2020"

    dovi = False
    for side in stream.get("side_data_list") or []:
        side_type = (side.get("side_data_type") or "").lower()
        if "dovi" in side_type or "dolby vision" in side_type:
            dovi = True
            hdr = True
    return hdr, dovi


# The saved ffprobe result: a title whose source was removed still needs it.
PROBE_CACHE = os.environ.get("VIBESTREAM_PROBE_CACHE", "/app/data/probe")


def _probe_cache_path(path: str) -> str:
    import hashlib

    return os.path.join(PROBE_CACHE, hashlib.sha1(path.encode()).hexdigest()[:16] + ".json")


def probe_cached(path: str) -> bool:
    return os.path.exists(_probe_cache_path(path))


def cached_info(path: str) -> "MediaInfo | None":
    try:
        with open(_probe_cache_path(path), encoding="utf-8") as fh:
            return _parse(json.load(fh), path)
    except (OSError, ValueError):
        return None


def clear_probe(path: str) -> None:
    try:
        os.remove(_probe_cache_path(path))
    except OSError:
        pass


async def probe(path: str, timeout: float = 60.0) -> MediaInfo:
    if not os.path.exists(path):
        try:
            with open(_probe_cache_path(path), encoding="utf-8") as fh:
                return _parse(json.load(fh), path)
        except (OSError, ValueError):
            raise ProbeError(f"file does not exist: {path}") from None

    proc = await asyncio.create_subprocess_exec(
        FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ProbeError(f"ffprobe timed out on {path}") from None

    if proc.returncode != 0:
        raise ProbeError(f"ffprobe failed: {stderr.decode('utf-8', 'replace')[:300]}")

    try:
        payload = json.loads(stdout)
    except ValueError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON: {exc}") from exc

    try:
        os.makedirs(PROBE_CACHE, exist_ok=True)
        with open(_probe_cache_path(path), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError as exc:
        log.warning("could not keep the probe of %s: %s", path, exc)

    return _parse(payload, path)


def _parse(payload: dict, path: str) -> MediaInfo:
    fmt = payload.get("format") or {}
    info = MediaInfo(
        path=path,
        duration=float(fmt.get("duration") or 0.0),
        container=fmt.get("format_name") or "",
        bitrate=_to_int(fmt.get("bit_rate")),
    )

    for stream in payload.get("streams") or []:
        kind = stream.get("codec_type")
        tags = {k.lower(): v for k, v in (stream.get("tags") or {}).items()}
        disposition = stream.get("disposition") or {}
        index = _to_int(stream.get("index"))
        codec = (stream.get("codec_name") or "").lower()

        if kind == "video":
            if disposition.get("attached_pic"):
                continue
            if info.video is not None:
                continue
            hdr, dovi = _detect_hdr(stream)
            info.video = VideoStream(
                index=index,
                codec=codec,
                profile=stream.get("profile"),
                width=_to_int(stream.get("width")),
                height=_to_int(stream.get("height")),
                pix_fmt=stream.get("pix_fmt"),
                bit_depth=_bit_depth(stream),
                frame_rate=_parse_frame_rate(stream.get("r_frame_rate")),
                is_hdr=hdr,
                is_dolby_vision=dovi,
                color_transfer=stream.get("color_transfer"),
            )
        elif kind == "audio":
            info.audio.append(
                AudioStream(
                    index=index,
                    codec=codec,
                    channels=_to_int(stream.get("channels")),
                    language=tags.get("language"),
                    title=tags.get("title"),
                    is_default=bool(disposition.get("default")),
                )
            )
        elif kind == "subtitle":
            title = (tags.get("title") or "")
            info.subtitles.append(
                SubtitleStream(
                    index=index,
                    codec=codec,
                    language=tags.get("language"),
                    title=title or None,
                    is_default=bool(disposition.get("default")),
                    is_forced=bool(disposition.get("forced"))
                    or "forced" in title.lower(),
                    is_hearing_impaired=bool(disposition.get("hearing_impaired"))
                    or "sdh" in title.lower(),
                )
            )

    return info


def summarise(info: MediaInfo) -> dict:
    return {
        "duration": round(info.duration, 3),
        "container": info.container,
        "bitrate": info.bitrate,
        "video": (
            {
                "codec": info.video.codec,
                "profile": info.video.profile,
                "width": info.video.width,
                "height": info.video.height,
                "resolution": info.video.resolution_label,
                "bit_depth": info.video.bit_depth,
                "frame_rate": info.video.frame_rate,
                "hdr": info.video.is_hdr,
                "dolby_vision": info.video.is_dolby_vision,
            }
            if info.video
            else None
        ),
        "audio": [
            {
                "index": a.index, "codec": a.codec, "channels": a.channels,
                "language": a.language, "title": a.title,
                "default": a.is_default, "label": a.label,
                "needs_encode": a.codec not in WEBOS_AUDIO,
            }
            for a in info.audio
        ],
        "subtitles": [
            {
                "index": s.index, "codec": s.codec, "language": s.language,
                "title": s.title, "default": s.is_default, "forced": s.is_forced,
                "sdh": s.is_hearing_impaired, "label": s.label,
                "text": s.is_text, "image": s.is_image,
            }
            for s in info.subtitles
        ],
    }
