"""Which release represents a title: best resolution, with oversized releases demoted, not hidden."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from ..models import Torrent

RESOLUTION_RANK = {"2160p": 400, "1080p": 300, "720p": 200, "576p": 100, "480p": 50}

# Best first. The size penalty below keeps remuxes from winning by default.
SOURCE_RANK = {
    "BluRay": 60, "Remux": 55, "WEB-DL": 50, "WEBRip": 35, "BDRip": 30,
    "BRRip": 25, "HDTV": 15, "DVDRip": 10, "HDRip": 5, "DVD": 5,
    "CAM": -100, "TS": -100,
}

CODEC_RANK = {"H.265": 20, "x265": 20, "AV1": 15, "H.264": 12, "x264": 12}

HDR_BONUS = {"DV HDR": 25, "DV": 22, "HDR10+": 20, "HDR10": 16, "HDR": 15, "HLG": 8}

GB = 1024 ** 3

# Disqualifying (no seeders, CAM): pushed below everything viable, order kept.
DISQUALIFIED = -1000.0

# Filelist over an addon's public release: half a resolution step, so a lower
# resolution never wins.
FILELIST_BONUS = 50.0
UNPLAYABLE_SOURCES = {"CAM", "TS"}


@dataclass
class Scored:
    torrent: Torrent
    score: float
    reasons: list[str]


def _size_penalty(size_bytes: int, resolution: str | None) -> tuple[float, str | None]:
    if not size_bytes:
        return 0.0, None
    cap = settings.quality_max_gb * GB
    size_gb = size_bytes / GB

    if size_bytes <= cap:
        return 0.0, None
    over = (size_bytes - cap) / cap
    penalty = min(220.0, 60.0 + over * 120.0)
    return -penalty, f"{size_gb:.0f}GB exceeds the {settings.quality_max_gb}GB ceiling"


def _seeder_bonus(seeders: int) -> float:
    """Diminishing returns, so a huge swarm cannot outweigh a resolution difference."""
    if seeders <= 0:
        return -40.0
    if seeders < 3:
        return -15.0
    if seeders < 10:
        return 0.0
    if seeders < 30:
        return 6.0
    if seeders < 100:
        return 10.0
    return 14.0


def score_release(torrent: Torrent) -> Scored:
    reasons: list[str] = []
    score = 0.0
    disqualified = False

    # A debrid copy the addon already holds downloads at line speed, so seeders do
    # not matter. Not for season packs, fetched from the swarm per episode.
    linked = bool(getattr(torrent, "held", False)) and (
        torrent.season is None or torrent.episode is not None
    )
    if (torrent.seeders or 0) <= 0 and not linked:
        disqualified = True
        reasons.append("no seeders, cannot be downloaded")
    if torrent.source in UNPLAYABLE_SOURCES:
        disqualified = True
        reasons.append(f"{torrent.source} source")

    resolution = torrent.resolution
    score += RESOLUTION_RANK.get(resolution or "", 0)
    if resolution:
        reasons.append(resolution)

    if torrent.source:
        score += SOURCE_RANK.get(torrent.source, 0)
        reasons.append(torrent.source)

    if torrent.video_codec:
        score += CODEC_RANK.get(torrent.video_codec, 0)

    if torrent.hdr:
        score += HDR_BONUS.get(torrent.hdr, 10)
        reasons.append(torrent.hdr)

    penalty, why = _size_penalty(torrent.size_bytes or 0, resolution)
    score += penalty
    if why:
        reasons.append(why)

    if linked:
        score += _seeder_bonus(1000) + 4.0
        reasons.append("debrid")
    else:
        score += _seeder_bonus(torrent.seeders or 0)

    if (torrent.times_completed or 0) > 20:
        score += 4.0

    if torrent.internal:
        score += 8.0
        reasons.append("internal")
    if torrent.moderated:
        score += 3.0

    if torrent.freeleech:
        score += 2.0

    if (torrent.file_count or 1) > 8 and torrent.season is None:
        score -= 25.0
        reasons.append("multi-file disc structure")

    if (torrent.origin or "filelist") == "filelist":
        score += FILELIST_BONUS
        reasons.append("filelist")

    if disqualified:
        score += DISQUALIFIED

    return Scored(torrent=torrent, score=round(score, 2), reasons=reasons)


def rank(torrents: list[Torrent]) -> list[Scored]:
    scored = [score_release(t) for t in torrents]
    scored.sort(key=lambda s: (s.score, s.torrent.seeders or 0), reverse=True)
    return scored


def pick_primary(torrents: list[Torrent]) -> Torrent | None:
    ranked = rank(torrents)
    return ranked[0].torrent if ranked else None


def group_alternatives(torrents: list[Torrent]) -> dict:
    ranked = rank(torrents)
    if not ranked:
        return {"primary": None, "alternatives": [], "by_resolution": {}}

    primary = ranked[0]
    by_resolution: dict[str, list] = {}
    for item in ranked:
        key = item.torrent.resolution or "other"
        by_resolution.setdefault(key, []).append(item)

    return {
        "primary": primary,
        "alternatives": ranked[1:],
        "by_resolution": by_resolution,
    }
