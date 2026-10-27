"""Building the home screen from TMDB genres, ratings and dates, not tracker categories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Download, Episode, EpisodeProgress, Media, Torrent, WatchProgress, utcnow,
)
from .coverage import ranked_popularity, watchable

FEATURED_GENRES = [
    "Action", "Comedy", "Drama", "Thriller", "Science Fiction", "Horror",
    "Animation", "Documentary", "Adventure", "Crime", "Family", "Fantasy",
    "Mystery", "Romance", "War", "Western", "History", "Music",
]

MIN_ROW_ITEMS = 6
DEFAULT_ROW_SIZE = 24


@dataclass
class Row:
    id: str
    title: str
    kind: str                     # continue | recent | genre | toprated | collection
    items: list = field(default_factory=list)


def _media_with_releases(session: Session, stmt) -> list[tuple[Media, list[Torrent]]]:
    media_rows = list(session.scalars(stmt))
    if not media_rows:
        return []
    ids = [m.id for m in media_rows]
    torrents = session.scalars(
        select(Torrent).where(Torrent.media_id.in_(ids))
    ).all()
    by_media: dict[int, list[Torrent]] = {}
    for t in torrents:
        by_media.setdefault(t.media_id, []).append(t)
    return [(m, by_media.get(m.id, [])) for m in media_rows if by_media.get(m.id)]


def _base_query(media_type: str | None = None):
    stmt = (
        select(Media)
        .where(Media.enrich_status == "ok", Media.poster_path.is_not(None))
    )
    if media_type:
        stmt = stmt.where(Media.media_type == media_type)
    return stmt


RESUME_MIN_SECONDS = 30


def _resume_percent(seconds: float, runtime: float | None) -> float:
    return round(min(100.0, (seconds / runtime) * 100), 1) if runtime else 0.0


def continue_watching(session: Session, media_type: str | None = None,
                      limit: int = DEFAULT_ROW_SIZE, profile_id: int | None = None):
    """Titles this profile started but has not finished. Films resume per download, shows per episode."""
    if not profile_id:
        return []

    candidates: list[tuple] = []

    films = (
        select(WatchProgress)
        .where(
            WatchProgress.profile_id == profile_id,
            WatchProgress.resume_seconds > RESUME_MIN_SECONDS,
            WatchProgress.finished_at.is_(None),
        )
        .order_by(WatchProgress.updated_at.desc())
        .limit(limit * 2)
        .options(selectinload(WatchProgress.download)
                 .selectinload(Download.torrent).selectinload(Torrent.media))
    )
    film_rows = list(session.scalars(films))
    packs = set(session.scalars(
        select(Episode.download_id).where(
            Episode.download_id.in_([p.download_id for p in film_rows])
        ).distinct()
    )) if film_rows else set()
    for progress in film_rows:
        download = progress.download
        if not download or download.reaped_at:
            continue
        if download.prepared_at is None:
            continue
        torrent = download.torrent
        if not torrent or not torrent.media:
            continue
        # A download that holds episodes is resumed by episode, never as a whole.
        if download.id in packs:
            continue
        candidates.append((
            progress.updated_at,
            torrent.media,
            torrent,
            {
                "resume_seconds": round(progress.resume_seconds),
                "resume_percent": _resume_percent(
                    progress.resume_seconds, progress.runtime_seconds
                ),
                "resume_download_id": download.id,
                "resume_play_id": str(download.id),
            },
        ))

    from .nextup import after

    episodes = (
        select(EpisodeProgress)
        .where(EpisodeProgress.profile_id == profile_id)
        .order_by(EpisodeProgress.updated_at.desc())
        .limit(limit * 10)
        .options(selectinload(EpisodeProgress.episode).selectinload(Episode.media))
    )
    shows_seen: set[int] = set()
    for progress in session.scalars(episodes):
        episode = progress.episode
        if episode is None or not episode.media or episode.media_id in shows_seen:
            continue
        shows_seen.add(episode.media_id)
        offer = after(session, profile_id, episode, progress)
        if offer is None:
            continue
        # Barely started counts only when it follows a finished episode.
        if offer["kind"] == "start":
            watched_any = session.scalar(
                select(EpisodeProgress.id)
                .join(Episode, Episode.id == EpisodeProgress.episode_id)
                .where(EpisodeProgress.profile_id == profile_id,
                       Episode.media_id == episode.media_id,
                       EpisodeProgress.finished_at.is_not(None))
                .limit(1)
            )
            if not watched_any:
                continue
            offer = {**offer, "kind": "next"}
        target = session.get(Episode, int(offer["play_id"][1:]))
        download = session.get(Download, target.download_id) if target.download_id else None
        if not download or download.reaped_at or not download.torrent:
            continue
        candidates.append((
            progress.updated_at,
            episode.media,
            download.torrent,
            {
                "resume_seconds": offer["resume_seconds"],
                "resume_percent": offer["resume_percent"],
                "resume_download_id": download.id,
                "resume_play_id": offer["play_id"],
                "resume_label": offer["label"],
                "resume_episode_name": offer["name"],
                "resume_kind": offer["kind"],
            },
        ))

    candidates.sort(key=lambda row: row[0] or datetime.min, reverse=True)

    # Tiles taken off the row stay off until the title is watched again.
    from ..models import ContinueHidden

    hidden = {
        row.media_id: row.hidden_at
        for row in session.scalars(
            select(ContinueHidden).where(ContinueHidden.profile_id == profile_id)
        )
    }

    out = []
    seen_media: set[int] = set()
    for when, media, torrent, extra in candidates:
        if media.id in seen_media:
            continue
        if media.id in hidden and (when is None or when <= hidden[media.id]):
            seen_media.add(media.id)
            continue
        if media_type and media.media_type != media_type:
            continue
        seen_media.add(media.id)
        out.append((media, [torrent], extra))
        if len(out) >= limit:
            break
    return out


def my_list(session: Session, profile_id: int, media_type: str | None = None,
            limit: int | None = DEFAULT_ROW_SIZE):
    from ..models import MyListItem

    stmt = (
        _base_query(media_type)
        .join(MyListItem, MyListItem.media_id == Media.id)
        .where(MyListItem.profile_id == profile_id)
        .order_by(MyListItem.added_at.desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return _media_with_releases(session, stmt)


def liked(session: Session, profile_id: int, limit: int = DEFAULT_ROW_SIZE):
    from ..models import Rating

    stmt = (
        _base_query()
        .join(Rating, Rating.media_id == Media.id)
        .where(Rating.profile_id == profile_id, Rating.value > 0)
        .order_by(Rating.updated_at.desc())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def watch_again(session: Session, profile_id: int, limit: int = DEFAULT_ROW_SIZE):
    finished: dict[int, datetime] = {}
    films = (
        select(Torrent.media_id, func.max(WatchProgress.finished_at))
        .join(Download, Download.id == WatchProgress.download_id)
        .join(Torrent, Torrent.id == Download.torrent_id)
        .where(WatchProgress.profile_id == profile_id, WatchProgress.finished_at.is_not(None))
        .group_by(Torrent.media_id)
    )
    shows = (
        select(Episode.media_id, func.max(EpisodeProgress.finished_at))
        .join(Episode, Episode.id == EpisodeProgress.episode_id)
        .where(EpisodeProgress.profile_id == profile_id,
               EpisodeProgress.finished_at.is_not(None))
        .group_by(Episode.media_id)
    )
    for stmt in (films, shows):
        for media_id, when in session.execute(stmt):
            if media_id is None or when is None:
                continue
            if media_id not in finished or when > finished[media_id]:
                finished[media_id] = when
    if not finished:
        return []
    order = sorted(finished, key=lambda mid: finished[mid], reverse=True)[:limit]
    found = {
        media.id: (media, torrents)
        for media, torrents in _media_with_releases(
            session, _base_query().where(Media.id.in_(order))
        )
    }
    return [found[mid] for mid in order if mid in found]


def mine_rows(session: Session, profile_id: int) -> list[Row]:
    rows: list[Row] = []
    resume = continue_watching(session, None, profile_id=profile_id)
    if resume:
        rows.append(Row("continue", "Resume Watching", "continue", resume))
    saved = my_list(session, profile_id)
    if saved:
        rows.append(Row("mylist", "Watchlist", "mylist", saved))
    again = watch_again(session, profile_id)
    if again:
        rows.append(Row("watchagain", "Watch It Again", "watchagain", again))
    loved = liked(session, profile_id)
    if loved:
        rows.append(Row("liked", "TV Shows & Movies You've Liked", "liked", loved))
    library = in_library(session)
    if library:
        rows.append(Row("library", "Ready to Play", "library", library))
    return rows


def recently_added(session: Session, media_type: str | None = None,
                   limit: int = DEFAULT_ROW_SIZE):
    stmt = (
        _base_query(media_type)
        .join(Torrent, Torrent.media_id == Media.id)
        .where(watchable())
        .group_by(Media.id)
        .order_by(func.max(Torrent.upload_date).desc().nullslast())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def in_library(session: Session, media_type: str | None = None,
               limit: int = DEFAULT_ROW_SIZE):
    stmt = (
        _base_query(media_type)
        .join(Torrent, Torrent.media_id == Media.id)
        .join(Download, Download.torrent_id == Torrent.id)
        .where(Download.state.in_(["linked", "completed", "seeding", "downloading"]))
        .group_by(Media.id)
        .order_by(func.max(Download.requested_at).desc())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def by_genre(session: Session, genre: str, media_type: str | None = None,
             limit: int = DEFAULT_ROW_SIZE):
    stmt = (
        _base_query(media_type)
        .where(Media.genres.ilike(f'%"{genre}"%'))
        .order_by(ranked_popularity().desc(), Media.vote_count.desc().nullslast())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def top_rated(session: Session, media_type: str | None = None,
              limit: int = DEFAULT_ROW_SIZE):
    stmt = (
        _base_query(media_type)
        .where(Media.vote_average.is_not(None), Media.vote_count > 200,
               watchable())
        .order_by(Media.vote_average.desc())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def recent_releases(session: Session, years: int = 2, limit: int = DEFAULT_ROW_SIZE):
    cutoff = (utcnow() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    stmt = (
        _base_query()
        .where(Media.release_date.is_not(None), Media.release_date >= cutoff, watchable())
        .order_by(Media.release_date.desc())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def four_k_row(session: Session, limit: int = DEFAULT_ROW_SIZE):
    stmt = (
        _base_query()
        .join(Torrent, Torrent.media_id == Media.id)
        .where(Torrent.resolution == "2160p", Torrent.hdr.is_not(None))
        .group_by(Media.id)
        .order_by(ranked_popularity().desc())
        .limit(limit)
    )
    return _media_with_releases(session, stmt)


def available_genres(session: Session, minimum: int = MIN_ROW_ITEMS) -> list[str]:
    counts: dict[str, int] = {}
    for (raw,) in session.execute(
        select(Media.genres).where(
            Media.genres.is_not(None), Media.enrich_status == "ok"
        )
    ):
        try:
            for name in json.loads(raw):
                counts[name] = counts.get(name, 0) + 1
        except (ValueError, TypeError):
            continue
    return [g for g in FEATURED_GENRES if counts.get(g, 0) >= minimum]


def home_rows(session: Session, media_type: str | None = None,
              profile_id: int | None = None) -> list[Row]:
    rows: list[Row] = []

    resume = continue_watching(session, media_type, profile_id=profile_id)
    if resume:
        rows.append(Row("continue", "Resume Watching", "continue", resume))

    saved = my_list(session, profile_id, media_type) if profile_id else []
    if saved:
        rows.append(Row("mylist", "Watchlist", "mylist", saved))

    library = in_library(session, media_type)
    if library:
        rows.append(Row("library", "Ready to Play", "library", library))

    recent = recently_added(session, media_type)
    if recent:
        label = {
            "movie": "Recently Added Movies", "tv": "Recently Added Shows"
        }.get(media_type, "Recently Added")
        rows.append(Row("recent", label, "recent", recent))

    if not media_type:
        fresh = recent_releases(session)
        if len(fresh) >= MIN_ROW_ITEMS:
            rows.append(Row("new", "New Releases", "recent", fresh))

        uhd = four_k_row(session)
        if len(uhd) >= MIN_ROW_ITEMS:
            rows.append(Row("uhd", "4K HDR", "genre", uhd))

    best = top_rated(session, media_type)
    if len(best) >= MIN_ROW_ITEMS:
        rows.append(Row("toprated", "Critically Acclaimed", "toprated", best))

    for genre in available_genres(session):
        items = by_genre(session, genre, media_type)
        if len(items) >= MIN_ROW_ITEMS:
            rows.append(
                Row(f"genre-{genre.lower().replace(' ', '-')}", genre, "genre", items)
            )

    return rows
