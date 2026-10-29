"""The notification bell. Derived from existing data; nothing is stored."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_session, kv_get, kv_set
from ..models import Download, DownloadState, Episode, Media, utcnow
from ..services import maturity
from ..services.tmdb import backdrop_url, poster_url

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/news")
def news(since: str | None = None, app: str | None = Query(None, pattern="^(android|ios|web|tv)$")):
    """What is new in the apps since the version an app last told of, newest
    first; releases with nothing for this app are left out."""
    from ..services import news as notes

    from .. import VERSION

    found = [{"version": r["version"], "items": r["apps"]} for r in notes.since(since, app) if r["apps"]]
    return {"version": VERSION, "releases": found}

LIBRARY_DAYS = 30
ARRIVAL_DAYS = 7
ARRIVAL_LIMIT = 6
SPACE_LOW_SINCE = "space_low_since"


def _image(media: Media | None) -> str | None:
    if media is None:
        return None
    return backdrop_url(media.backdrop_path, "w300") or poster_url(media.poster_path, "w342")


def _seasons_line(session: Session, download: Download) -> str | None:
    rows = list(session.execute(
        select(Episode.season_number, Episode.number)
        .where(Episode.download_id == download.id)
        .order_by(Episode.season_number, Episode.number)
    ))
    if not rows:
        return None
    if len(rows) == 1:
        season, number = rows[0]
        return f"S{season}:E{number}"
    seasons = sorted({season for season, _ in rows})
    if len(seasons) == 1:
        return f"Season {seasons[0]}"
    return f"Seasons {seasons[0]}-{seasons[-1]}"


def _title(session: Session, download: Download) -> tuple[Media | None, str]:
    torrent = download.torrent
    media = torrent.media if torrent else None
    name = (media.title if media and media.title else None) \
        or (torrent.parsed_title if torrent else None) \
        or (torrent.name if torrent else f"Download {download.id}")
    if media is not None and media.media_type == "tv":
        seasons = _seasons_line(session, download)
        if seasons:
            name = f"{name}: {seasons}"
    return media, name


@router.get("/notifications")
def notifications(
    limit: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
):
    now = utcnow()
    items: list[dict] = []

    ready = session.scalars(
        select(Download).where(
            Download.prepared_at.is_not(None),
            Download.prepared_at > now - timedelta(days=LIBRARY_DAYS),
            Download.reaped_at.is_(None),
            Download.state != DownloadState.removed.value,
        )
    )
    for download in maturity.downloads(ready):
        media, name = _title(session, download)
        items.append({
            "id": f"ready-{download.id}",
            "kind": "ready",
            "heading": "Ready to Watch",
            "text": name,
            "image": _image(media),
            "media_id": media.id if media else None,
            "at": download.prepared_at.isoformat(),
        })

    failed = session.scalars(
        select(Download).where(
            or_(Download.prepare_error.is_not(None),
                Download.state == DownloadState.error.value),
            Download.reaped_at.is_(None),
            Download.state != DownloadState.removed.value,
        )
    )
    for download in maturity.downloads(failed):
        media, name = _title(session, download)
        preparing = download.prepare_error is not None
        at = download.completed_at or download.added_at or download.requested_at
        if at < now - timedelta(days=LIBRARY_DAYS):
            continue
        items.append({
            "id": f"failed-{download.id}",
            "kind": "failed",
            "heading": "Couldn't Prepare" if preparing else "Download Failed",
            "text": name,
            "image": _image(media),
            "media_id": media.id if media else None,
            "at": at.isoformat(),
        })

    arrivals = session.scalars(
        select(Media).where(
            Media.created_at > now - timedelta(days=ARRIVAL_DAYS),
            Media.backdrop_path.is_not(None),
            Media.title != "",
            maturity.clause(maturity.current()),
        )
        .order_by(Media.popularity.desc().nulls_last())
        .limit(ARRIVAL_LIMIT)
    )
    for media in arrivals:
        items.append({
            "id": f"new-{media.id}",
            "kind": "new",
            "heading": "New Arrival",
            "text": media.title,
            "image": _image(media),
            "media_id": media.id,
            "at": media.created_at.isoformat(),
        })

    from ..services import sources

    free = sources.free_bytes()
    # Dated from when space first ran low, or it would be unread on every poll.
    since = kv_get(session, SPACE_LOW_SINCE)
    if free is not None and free < sources.floor_bytes():
        if not since:
            since = now.isoformat()
            kv_set(session, SPACE_LOW_SINCE, since)
            session.commit()
        items.append({
            "id": "space-low",
            "kind": "space",
            "heading": "Running Out of Space",
            "text": f"{free / 1024 ** 3:.0f} GB left. Remove finished sources in My Downloads.",
            "image": None,
            "media_id": None,
            "at": since,
        })
    elif since and free is not None:
        kv_set(session, SPACE_LOW_SINCE, "")
        session.commit()

    items.sort(key=lambda item: item["at"], reverse=True)
    return {"items": items[:limit]}
