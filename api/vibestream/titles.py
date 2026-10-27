"""Scene release name parsing. Dots are load bearing: "H.265" and "DDP5.1" are single tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# Bounds the year, so "Blade Runner 2049" does not parse as year 2049.
MAX_YEAR = date.today().year + 2
MIN_YEAR = 1900

RESOLUTIONS = {
    "2160p": "2160p", "4k": "2160p", "uhd": "2160p",
    "1080p": "1080p", "1080i": "1080p",
    "720p": "720p", "576p": "576p", "480p": "480p",
}

SOURCES = {
    "bluray": "BluRay", "blu-ray": "BluRay", "bdrip": "BDRip", "brrip": "BRRip",
    "bdremux": "Remux", "remux": "Remux", "uhdremux": "Remux",
    "web-dl": "WEB-DL", "webdl": "WEB-DL", "web": "WEB-DL", "webrip": "WEBRip",
    "hdtv": "HDTV", "pdtv": "HDTV",
    "dvdrip": "DVDRip", "dvd": "DVD", "dvd9": "DVD", "dvd5": "DVD",
    "hdrip": "HDRip", "cam": "CAM", "telesync": "TS", "hdcam": "CAM",
}

VIDEO_CODECS = {
    "x264": "x264", "h264": "H.264", "avc": "H.264",
    "x265": "x265", "h265": "H.265", "hevc": "H.265",
    "av1": "AV1", "xvid": "XviD", "divx": "DivX", "mpeg2": "MPEG-2", "vc1": "VC-1",
}

# The channel layout is glued on (DDP5.1, DTS-HD-MA5.1). Longest alternatives first.
AUDIO_RE = re.compile(
    r"^(dts-hd-ma|dts-hd|dts-x|dtsx|truehd|atmos|eac3|e-ac3|ddp|dd\+|ac3|dd|dts|"
    r"aac|flac|opus|mp3|lpcm|pcm)(\d{2,3})?$",
    re.I,
)
AUDIO_LABELS = {
    "dts-hd-ma": "DTS-HD MA", "dts-hd": "DTS-HD", "dts-x": "DTS:X", "dtsx": "DTS:X",
    "truehd": "TrueHD", "atmos": "Atmos", "eac3": "DDP", "e-ac3": "DDP",
    "ddp": "DDP", "dd+": "DDP", "ac3": "DD", "dd": "DD", "dts": "DTS",
    "aac": "AAC", "flac": "FLAC", "opus": "Opus", "mp3": "MP3",
    "lpcm": "LPCM", "pcm": "PCM",
}

HDR_TOKENS = {
    "dv": "DV", "dovi": "DV", "dolbyvision": "DV",
    "hdr10plus": "HDR10+", "hdr10": "HDR10", "hdr": "HDR", "hlg": "HLG", "sdr": "SDR",
}

SERVICES = {
    "nf", "amzn", "hmax", "max", "dsnp", "atvp", "appletv", "apps", "pcok", "stan",
    "hulu", "ma", "itunes", "it", "cr", "vdl", "skst", "cnlp", "red", "pmtp", "hbo",
    "pcok", "roku", "tvnz", "sho", "strp", "cbs", "bbc",
}

EDITIONS = {
    "extended", "unrated", "directors", "director's", "theatrical", "uncut",
    "remastered", "criterion", "imax", "restored", "anniversary", "despecialized",
    "international", "ultimate", "collectors", "redux", "recut",
}

OTHER_TAGS = {
    "repack", "proper", "internal", "limited", "complete", "subbed", "dubbed",
    "multi", "dual", "rosubbed", "romanian", "hybrid", "10bit", "8bit", "12bit",
    "bit", "rerip", "readnfo", "extras", "3d", "hsbs", "sbs", "half", "open",
    "matinee", "final", "special", "cut", "edition", "version", "audio",
}

SEASON_EPISODE = re.compile(r"^s(\d{1,3})(?:\s*e(\d{1,3}))?$", re.I)
SEASON_RANGE = re.compile(r"^s(\d{1,3})-s?(\d{1,3})$", re.I)
EPISODE_ALT = re.compile(r"^(\d{1,2})x(\d{2})$", re.I)
YEAR_RE = re.compile(r"^(\d{4})$")
CHANNELS_RE = re.compile(r"^\d{2,3}$")


@dataclass
class ParsedRelease:
    title: str
    year: int | None = None
    resolution: str | None = None
    source: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    hdr: str | None = None
    release_group: str | None = None
    season: int | None = None
    episode: int | None = None
    season_end: int | None = None
    edition: str | None = None
    is_tv: bool = False


def _is_year(tok: str) -> bool:
    m = YEAR_RE.match(tok)
    return bool(m) and MIN_YEAR <= int(m.group(1)) <= MAX_YEAR


def _strip_extension(name: str) -> str:
    return re.sub(r"\.(mkv|mp4|avi|ts|m2ts|iso|wmv|mov)$", "", name, flags=re.I)


def _split_group(name: str) -> tuple[str, str | None]:
    m = re.search(r"-([A-Za-z0-9_]{2,20})$", name)
    if not m:
        return name, None
    candidate = m.group(1)
    lowered = candidate.lower()
    # Guard against eating the tail of a hyphenated technical token.
    if lowered in ("ray", "dl", "hd", "ma", "x", "dts", "hdma"):
        return name, None
    if _is_year(lowered) or lowered in RESOLUTIONS:
        return name, None
    return name[: m.start()], candidate


def _normalise(name: str) -> str:
    s = name
    # Protect the dot inside codec names before the generic dot pass.
    s = re.sub(r"\bH\.(26[45])\b", r"H\1", s, flags=re.I)
    s = re.sub(r"\bDTS[.\-]HD[.\-]MA\b", "DTS-HD-MA", s, flags=re.I)
    s = re.sub(r"\bDTS[.\-]HD\b", "DTS-HD", s, flags=re.I)
    s = re.sub(r"\bDTS[.\-]X\b", "DTS-X", s, flags=re.I)
    s = re.sub(r"\bE[.\-]AC3\b", "EAC3", s, flags=re.I)
    s = re.sub(r"\bWEB[.\-]DL\b", "WEB-DL", s, flags=re.I)
    s = re.sub(r"\bBlu[.\-]Ray\b", "BluRay", s, flags=re.I)
    s = re.sub(r"\bHDR10\+", "HDR10PLUS", s, flags=re.I)
    # Channel layouts: 5.1 -> 51. Lone digits only, or "1990.2160p" would weld into one token.
    s = re.sub(r"(?<!\d)(\d)\.(\d)(?!\d)", r"\1\2", s)
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"[._]+", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def parse_release(name: str) -> ParsedRelease:
    if not name or not name.strip():
        return ParsedRelease(title="")

    working, group = _split_group(_strip_extension(name.strip()))
    tokens = _normalise(working).split(" ")

    out = ParsedRelease(title="", release_group=group)
    title_tokens: list[str] = []
    editions: list[str] = []
    boundary = False
    audio_base: str | None = None
    atmos = False

    i = 0
    while i < len(tokens):
        raw = tokens[i]
        tok = raw.lower().strip("-")
        nxt = tokens[i + 1].lower().strip("-") if i + 1 < len(tokens) else ""
        matched = True

        if not title_tokens:
            # Nothing is structural before the title starts, or "Uncut.Gems" parses to an empty title.
            matched = False
        elif _is_year(tok) and out.year is None:
            # A leading year belongs to the title ("1917"), as does the first of two years.
            if not title_tokens or _is_year(nxt):
                matched = False
            else:
                out.year = int(tok)
                boundary = True
        elif tok in RESOLUTIONS:
            out.resolution = RESOLUTIONS[tok]
            boundary = True
        elif tok in SOURCES:
            out.source = SOURCES[tok]
            boundary = True
        elif tok in VIDEO_CODECS:
            out.video_codec = VIDEO_CODECS[tok]
            boundary = True
        elif tok in HDR_TOKENS:
            label = HDR_TOKENS[tok]
            out.hdr = label if not out.hdr else f"{out.hdr} {label}"
            boundary = True
        elif AUDIO_RE.match(tok):
            label = AUDIO_LABELS[AUDIO_RE.match(tok).group(1).lower()]
            # Atmos is a modifier that appears on either side of the codec, so compose it at the end.
            if label == "Atmos":
                atmos = True
            elif not audio_base or len(label) > len(audio_base):
                audio_base = label
            boundary = True
        elif SEASON_EPISODE.match(tok):
            m = SEASON_EPISODE.match(tok)
            out.season = int(m.group(1))
            if m.group(2):
                out.episode = int(m.group(2))
            boundary = True
        elif SEASON_RANGE.match(tok):
            m = SEASON_RANGE.match(tok)
            out.season = int(m.group(1))
            out.season_end = int(m.group(2))
            boundary = True
        elif EPISODE_ALT.match(tok):
            m = EPISODE_ALT.match(tok)
            out.season, out.episode = int(m.group(1)), int(m.group(2))
            boundary = True
        elif tok in EDITIONS:
            editions.append(raw.title())
            boundary = True
        elif boundary and (tok in SERVICES or tok in OTHER_TAGS or CHANNELS_RE.match(tok)):
            pass
        else:
            matched = False

        if not matched and not boundary:
            title_tokens.append(raw)
        i += 1

    title = " ".join(title_tokens).strip(" -.")
    m = re.match(r"^(.*),\s*(The|A|An)$", title, re.I)
    if m:
        title = f"{m.group(2)} {m.group(1)}"

    out.title = re.sub(r"\s{2,}", " ", title).strip()
    if audio_base and atmos:
        out.audio_codec = f"{audio_base} Atmos"
    elif audio_base:
        out.audio_codec = audio_base
    elif atmos:
        out.audio_codec = "Atmos"
    if editions:
        out.edition = " ".join(dict.fromkeys(editions))
    out.is_tv = out.season is not None

    return out


def library_folder_name(title: str, year: int | None) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "Unknown").strip()
    clean = re.sub(r"\s{2,}", " ", clean).rstrip(". ")
    return f"{clean} ({year})" if year else clean
