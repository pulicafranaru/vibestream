"""Subtitles: extract embedded tracks, fetch missing ones from OpenSubtitles, all as WebVTT."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field


from ..config import settings
from .mediainfo import FFMPEG, MediaInfo, SubtitleStream
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

OPENSUBTITLES_API = "https://api.opensubtitles.com/api/v1"

CACHE_DIR = os.environ.get("VIBESTREAM_SUBTITLE_CACHE", "/app/data/subtitles")

# ISO 639-2/B to 639-1, for the languages that actually turn up here.
LANG_ALIASES = {
    "eng": "en", "rum": "ro", "ron": "ro", "fre": "fr", "fra": "fr",
    "ger": "de", "deu": "de", "spa": "es", "ita": "it", "por": "pt",
    "dut": "nl", "nld": "nl", "rus": "ru", "pol": "pl", "hun": "hu",
    "cze": "cs", "ces": "cs", "gre": "el", "ell": "el", "tur": "tr",
    "swe": "sv", "dan": "da", "nor": "no", "fin": "fi", "ara": "ar",
    "heb": "he", "jpn": "ja", "kor": "ko", "chi": "zh", "zho": "zh",
    "bul": "bg", "hrv": "hr", "srp": "sr", "ukr": "uk",
}

LANGUAGE_NAMES = {
    "en": "English", "ro": "Romanian", "fr": "French", "de": "German",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "ru": "Russian", "pl": "Polish", "hu": "Hungarian", "cs": "Czech",
    "el": "Greek", "tr": "Turkish", "sv": "Swedish", "da": "Danish",
    "no": "Norwegian", "fi": "Finnish", "ar": "Arabic", "he": "Hebrew",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "bg": "Bulgarian",
    "hr": "Croatian", "sr": "Serbian", "uk": "Ukrainian",
}


def normalise_language(code: str | None) -> str:
    if not code:
        return "und"
    code = code.strip().lower()
    return LANG_ALIASES.get(code, code[:2] if len(code) >= 2 else "und")


def language_name(code: str | None) -> str:
    norm = normalise_language(code)
    return LANGUAGE_NAMES.get(norm, norm.upper())


class SubtitleError(RuntimeError):
    pass


@dataclass
class SubtitleTrack:
    id: str
    label: str
    language: str
    source: str            # "embedded" or "opensubtitles"
    forced: bool = False
    sdh: bool = False
    default: bool = False
    stream_index: int | None = None
    file_id: int | None = None      # OpenSubtitles file id
    path: str | None = None         # cached .vtt on disk


@dataclass
class SubtitleSet:
    tracks: list[SubtitleTrack] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)


def embedded_tracks(info: MediaInfo, preferred: list[str] | None = None) -> SubtitleSet:
    preferred = preferred or ["en", "ro"]
    result = SubtitleSet()

    for stream in info.subtitles:
        lang = normalise_language(stream.language)
        if stream.is_image:
            result.unavailable.append(
                {
                    "index": stream.index,
                    "language": lang,
                    "label": f"{language_name(lang)} (image based)",
                    "reason": (
                        f"{stream.codec} is a bitmap format and cannot be converted "
                        "to text without OCR"
                    ),
                }
            )
            continue
        if not stream.is_text:
            continue

        result.tracks.append(
            SubtitleTrack(
                id=f"emb{stream.index}",
                label=_track_label(stream, lang),
                language=lang,
                source="embedded",
                forced=stream.is_forced,
                sdh=stream.is_hearing_impaired,
                default=stream.is_default or lang == preferred[0],
                stream_index=stream.index,
            )
        )

    result.tracks.sort(key=lambda t: _preference_key(t, preferred))
    _disambiguate(result.tracks)
    return result


def _disambiguate(tracks: list[SubtitleTrack]) -> None:
    """Make every label distinct: AVFoundation rejects a master playlist with duplicate NAMEs (-17223)."""
    used: set[str] = set()
    for track in tracks:
        if track.label not in used:
            used.add(track.label)
            continue
        # The suffix can collide too (a track titled "Spanish 2"), so count past it.
        suffix = 2
        while f"{track.label} {suffix}" in used:
            suffix += 1
        track.label = f"{track.label} {suffix}"
        used.add(track.label)


def _track_label(stream: SubtitleStream, lang: str) -> str:
    """Human label for a track. A title that restates a flag is dropped (no "SDH, SDH")."""
    label = language_name(lang)
    extras: list[str] = []

    if stream.is_forced:
        extras.append("Forced")
    if stream.is_hearing_impaired:
        extras.append("SDH")

    title = (stream.title or "").strip()
    if title and title.lower() not in ("", "subtitle", "subtitles"):
        redundant = {e.lower() for e in extras} | {label.lower(), lang.lower()}
        if title.lower() not in redundant:
            extras.append(title)

    seen: set[str] = set()
    unique = [e for e in extras if not (e.lower() in seen or seen.add(e.lower()))]
    return f"{label} ({', '.join(unique)})" if unique else label


def _preference_key(track: SubtitleTrack, preferred: list[str]) -> tuple:
    try:
        rank = preferred.index(track.language)
    except ValueError:
        rank = len(preferred)
    return (rank, track.forced, track.sdh, track.label)


def embedded_target(source_path: str, stream_index: int) -> str:
    import hashlib

    digest = hashlib.sha1(f"{source_path}:{stream_index}".encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{digest}.vtt")


def _extracted(target: str) -> bool:
    return os.path.exists(target) and os.path.getsize(target) > 0


def text_streams(info: MediaInfo) -> list[int]:
    return [s.index for s in info.subtitles if s.is_text and not s.is_image]


def all_extracted(info: MediaInfo) -> bool:
    return all(_extracted(embedded_target(info.path, i)) for i in text_streams(info))


async def extract_all(info: MediaInfo, timeout: float = 3600.0) -> str | None:
    """Every text track of a file to WebVTT, in one ffmpeg run. Returns an error, or None."""
    missing = [i for i in text_streams(info) if not _extracted(embedded_target(info.path, i))]
    if not missing:
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    args = [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", info.path]
    # Written under a temporary name and renamed once ffmpeg has finished, so a
    # run cut short never leaves a truncated file that counts as extracted.
    partial = {index: embedded_target(info.path, index) + ".part" for index in missing}
    for index in missing:
        args += ["-map", f"0:{index}", "-c:s", "webvtt", "-f", "webvtt", partial[index]]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "subtitle extraction timed out"
    if proc.returncode != 0:
        for path in partial.values():
            try:
                os.remove(path)
            except OSError:
                pass
        return f"subtitle extraction failed: {err.decode('utf-8', 'replace')[:200]}"
    for index in missing:
        target = embedded_target(info.path, index)
        if _extracted(partial[index]):
            os.replace(partial[index], target)
        else:
            # A track with no cues is kept empty but valid.
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("WEBVTT\n\n")
            try:
                os.remove(partial[index])
            except OSError:
                pass
    return None


def clear_for(source_path: str, info: MediaInfo | None = None) -> None:
    if info is None:
        return
    for index in text_streams(info):
        try:
            os.remove(embedded_target(source_path, index))
        except OSError:
            pass


async def extract_embedded(
    source_path: str, stream_index: int, timeout: float = 300.0
) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    target = embedded_target(source_path, stream_index)
    if _extracted(target):
        return target
    if not os.path.exists(source_path):
        raise SubtitleError("this track was not kept when the source was removed")

    # Temporary name, renamed when whole, as in extract_all.
    partial = target + ".part"
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-v", "error", "-nostdin", "-y",
        "-i", source_path,
        "-map", f"0:{stream_index}",
        "-c:s", "webvtt",
        "-f", "webvtt", partial,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        _remove(partial)
        raise SubtitleError("subtitle extraction timed out") from None
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        _remove(partial)
        raise

    if proc.returncode != 0 or not os.path.exists(partial):
        _remove(partial)
        raise SubtitleError(
            f"could not extract subtitle stream {stream_index}: "
            f"{err.decode('utf-8', 'replace')[:200]}"
        )
    os.replace(partial, target)
    return target


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


class OpenSubtitlesClient:
    """Minimal OpenSubtitles REST client. Results are cached: downloads are rate limited."""

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key if api_key is not None else settings.opensubtitles_api_key
        self.timeout = timeout
        if not self.api_key:
            raise SubtitleError("OPENSUBTITLES_API_KEY is not set")

    def _headers(self) -> dict:
        return {
            "Api-Key": self.api_key,
            "Accept": "application/json",
        }

    async def search(
        self, imdb_id: str | None, query: str | None, languages: list[str],
        season: int | None = None, episode: int | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {"languages": ",".join(languages)}
        if imdb_id:
            params["imdb_id"] = imdb_id.removeprefix("tt")
        elif query:
            params["query"] = query
        else:
            return []
        if season is not None:
            params["season_number"] = str(season)
        if episode is not None:
            params["episode_number"] = str(episode)

        async with outbound_client(timeout=self.timeout) as client:
            resp = await client.get(
                f"{OPENSUBTITLES_API}/subtitles", params=params, headers=self._headers()
            )
        if resp.status_code == 401:
            raise SubtitleError("OpenSubtitles rejected the API key")
        if resp.status_code == 429:
            raise SubtitleError("OpenSubtitles rate limit reached")
        if resp.status_code != 200:
            raise SubtitleError(f"OpenSubtitles search failed: HTTP {resp.status_code}")

        results = []
        for item in (resp.json().get("data") or []):
            attrs = item.get("attributes") or {}
            files = attrs.get("files") or []
            if not files:
                continue
            results.append(
                {
                    "file_id": files[0].get("file_id"),
                    "language": normalise_language(attrs.get("language")),
                    "release": attrs.get("release") or "",
                    "downloads": attrs.get("download_count") or 0,
                    "hearing_impaired": bool(attrs.get("hearing_impaired")),
                    "ratings": attrs.get("ratings") or 0,
                    "from_trusted": bool(attrs.get("from_trusted")),
                }
            )
        results.sort(key=lambda r: (r["from_trusted"], r["downloads"]), reverse=True)
        return results

    async def download_link(self, file_id: int) -> str:
        async with outbound_client(timeout=self.timeout) as client:
            resp = await client.post(
                f"{OPENSUBTITLES_API}/download",
                json={"file_id": file_id},
                headers={**self._headers(), "Content-Type": "application/json"},
            )
        if resp.status_code == 406:
            raise SubtitleError("OpenSubtitles download quota exhausted for today")
        if resp.status_code != 200:
            raise SubtitleError(f"OpenSubtitles download failed: HTTP {resp.status_code}")
        link = resp.json().get("link")
        if not link:
            raise SubtitleError("OpenSubtitles returned no download link")
        return link

    async def fetch_vtt(self, file_id: int) -> str:
        os.makedirs(CACHE_DIR, exist_ok=True)
        target = os.path.join(CACHE_DIR, f"os{file_id}.vtt")
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return target

        link = await self.download_link(file_id)
        async with outbound_client(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(link)
        if resp.status_code != 200:
            raise SubtitleError(f"subtitle fetch failed: HTTP {resp.status_code}")

        text = _decode_subtitle(resp.content)
        vtt = srt_to_vtt(text) if not text.lstrip().startswith("WEBVTT") else text
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(vtt)
        return target

    async def check(self) -> tuple[bool, str]:
        try:
            await self.search(imdb_id="tt0111161", query=None, languages=["en"])
            return True, "ok"
        except SubtitleError as exc:
            return False, str(exc)


def _decode_subtitle(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "cp1251", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


TIMING_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})"
)


def srt_to_vtt(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    converted = TIMING_RE.sub(r"\1.\2 --> \3.\4", text)
    if not converted.lstrip().startswith("WEBVTT"):
        converted = "WEBVTT\n\n" + converted.lstrip("﻿\n")
    return converted


def vtt_playlist(base_url: str, track_id: str, duration: float) -> str:
    return (
        "#EXTM3U\n"
        "#EXT-X-VERSION:7\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        f"#EXT-X-TARGETDURATION:{int(duration) + 1}\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        f"#EXTINF:{duration:.3f},\n"
        f"{base_url}/subs/{track_id}.vtt\n"
        "#EXT-X-ENDLIST\n"
    )
