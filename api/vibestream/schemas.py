from __future__ import annotations

import json

from .models import Download, Media, Torrent
from .services.tmdb import backdrop_url, logo_url, poster_url

COMPLETE = 0.98


def _genres(media: Media | None) -> list[str]:
    if not media or not media.genres:
        return []
    try:
        return json.loads(media.genres)
    except (ValueError, TypeError):
        return []


def _facts(media: Media | None) -> dict:
    if not media or not media.facts:
        return {}
    try:
        facts = json.loads(media.facts)
    except (ValueError, TypeError):
        return {}
    return facts if isinstance(facts, dict) else {}


def torrent_summary(torrent: Torrent, download: Download | None = None) -> dict:
    return {
        "id": torrent.id,
        "name": torrent.name,
        "category": torrent.category,
        "category_name": torrent.category_name,
        "size_bytes": torrent.size_bytes,
        "size_gb": round((torrent.size_bytes or 0) / 1024 ** 3, 2),
        "seeders": torrent.seeders,
        "leechers": torrent.leechers,
        "freeleech": torrent.freeleech,
        "internal": torrent.internal,
        "resolution": torrent.resolution,
        "source": torrent.source,
        "video_codec": torrent.video_codec,
        "audio_codec": torrent.audio_codec,
        "hdr": torrent.hdr,
        "release_group": torrent.release_group,
        "season": torrent.season,
        "episode": torrent.episode,
        "upload_date": torrent.upload_date.isoformat() if torrent.upload_date else None,
        "imdb_id": torrent.imdb_id,
        "origin": torrent.origin or "filelist",
        "origin_label": origin_label(torrent),
        "debrid": bool(torrent.held),
        "download": download_summary(download) if download else None,
    }


def origin_label(torrent: Torrent) -> str:
    if (torrent.origin or "filelist") == "filelist":
        return "Filelist"
    return torrent.category_name or "Addon"


def _wanted_labels(download: Download) -> list[str] | None:
    import os

    from .services.shows import parse_slot

    if not download.wanted_files:
        return None
    try:
        paths = json.loads(download.wanted_files)
    except ValueError:
        return None
    slots = {parse_slot(os.path.basename(str(path))) for path in paths}
    return [f"S{season}:E{number}" for season, number in sorted(s for s in slots if s)]


def _plays_an_episode(download: Download) -> bool:
    from sqlalchemy import select
    from sqlalchemy.orm import object_session

    from .models import Episode

    session = object_session(download)
    if session is None:
        return False
    return session.scalar(
        select(Episode.id)
        .where(Episode.download_id == download.id, Episode.prepared_at.is_not(None))
        .limit(1)
    ) is not None


def download_summary(download: Download | None) -> dict | None:
    if download is None:
        return None
    # A pack fetching another episode is downloading again, but the episodes
    # it already published still play.
    held = bool(download.library_path)
    on_disk = download.state in ("completed", "seeding", "linked") or held
    prepared = download.prepared_at is not None or (held and _plays_an_episode(download))

    # Deferred import: at module scope it would close an import cycle.
    from .services import preparation as prep_service

    prep = prep_service.status(download)
    from .services.downloads import friendly_error as dl_friendly

    return {
        "id": download.id,
        "torrent_id": download.torrent_id,
        "state": download.state,
        "episodes": _wanted_labels(download),
        "on_disk": on_disk,
        "playable": on_disk and prepared,
        "preparing": on_disk and not prepared and download.prepare_error is None,
        "prepare_error": download.prepare_error,
        # None, not 0, when unknown: after a restart in-memory progress is lost.
        "prepare_percent": None if prepared or not prep["percent"] else prep["percent"],
        "prepare_stage": None if prepared else prep["stage"],
        "progress": round(download.progress or 0.0, 4),
        "percent": round((download.progress or 0.0) * 100, 1),
        "dl_speed": download.dl_speed,
        "up_speed": download.up_speed,
        "eta_seconds": download.eta_seconds,
        "downloaded_bytes": download.downloaded_bytes,
        "uploaded_bytes": download.uploaded_bytes,
        "ratio": round(download.ratio or 0.0, 3),
        "seeding_hours": round((download.seeding_seconds or 0) / 3600, 1),
        "library_path": download.library_path,
        "error": download.error,
        "error_message": dl_friendly(download.error),
        "requested_at": download.requested_at.isoformat() if download.requested_at else None,
        "completed_at": download.completed_at.isoformat() if download.completed_at else None,
    }


def media_card(
    media: Media | None,
    torrents: list[Torrent],
    downloads: dict[int, Download] | None = None,
    fallback: Torrent | None = None,
) -> dict:
    from .services.ranking import rank

    from .services.offered import offered

    downloads = downloads or {}
    scored = rank(offered(torrents, downloads))
    ordered = [s.torrent for s in scored]
    if fallback is not None and not offered([fallback], downloads):
        fallback = None
    best = ordered[0] if ordered else fallback

    active = None
    for torrent in ordered:
        candidate = downloads.get(torrent.id)
        if candidate and candidate.state not in ("removed",):
            active = candidate
            break

    title = (media.title if media and media.title else None) or (
        best.parsed_title if best else None
    ) or (best.name if best else "Unknown")
    year = (media.year if media else None) or (best.parsed_year if best else None)
    facts = _facts(media)

    return {
        "media_id": media.id if media else None,
        "tmdb_id": media.tmdb_id if media else None,
        "imdb_id": (media.imdb_id if media else None) or (best.imdb_id if best else None),
        "media_type": (media.media_type if media else None) or "movie",
        "title": title,
        "year": year,
        "overview": media.overview if media else None,
        "tagline": media.tagline if media else None,
        "runtime": media.runtime if media else None,
        "genres": _genres(media),
        "vote_average": round(media.vote_average, 1) if media and media.vote_average else None,
        "poster": poster_url(media.poster_path if media else None),
        "backdrop": backdrop_url(media.backdrop_path if media else None),
        "logo": logo_url(facts.get("logo")),
        "backdrop_small": backdrop_url(media.backdrop_path if media else None, "w780"),
        "certification": facts.get("certification"),
        "tags": (facts.get("keywords") or [])[:3],
        "limited": bool(facts.get("limited")),
        "season_count": facts.get("seasons"),
        "complete": bool(
            media and media.media_type == "tv" and (media.coverage or 0) >= COMPLETE
        ),
        "enrich_status": media.enrich_status if media else "pending",
        "best_resolution": best.resolution if best else None,
        "primary_release_id": best.id if best else None,
        "quality": (
            {
                "resolution": best.resolution,
                "hdr": best.hdr,
                "source": best.source,
                "codec": best.video_codec,
                "audio": best.audio_codec,
                "size_gb": round((best.size_bytes or 0) / 1024 ** 3, 1),
                "reasons": scored[0].reasons if scored else [],
            }
            if best
            else None
        ),
        "release_count": len(ordered),
        "newest_upload": (
            max((t.upload_date for t in ordered if t.upload_date), default=None).isoformat()
            if any(t.upload_date for t in ordered)
            else None
        ),
        "download": download_summary(active),
        "releases": [
            torrent_summary(t, downloads.get(t.id)) for t in ordered
        ],
    }
