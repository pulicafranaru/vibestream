from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

import asyncio
import os
import json
import logging
import time

from ..config import settings
from ..db import get_session
from ..models import Download, Episode, EpisodeProgress, Media, Season, Torrent
from ..schemas import download_summary, media_card, torrent_summary
from ..services.coverage import ranked_popularity, title_weight
from ..services import stills
from ..services.tmdb import poster_url
from .profiles import current_profile_id

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

SORTS = {
    "newest": (Torrent.upload_date.desc().nullslast(), Torrent.id.desc()),
    "oldest": (Torrent.upload_date.asc().nullsfirst(), Torrent.id.asc()),
    "seeders": (Torrent.seeders.desc(), Torrent.id.desc()),
    "size": (Torrent.size_bytes.desc(), Torrent.id.desc()),
    "title": (Torrent.parsed_title.asc(), Torrent.id.desc()),
    "popular": (Torrent.seeders.desc(), Torrent.id.desc()),
}


def _group_key(torrent: Torrent) -> object:
    if torrent.media_id:
        return ("m", torrent.media_id)
    if torrent.parsed_title:
        return ("t", torrent.parsed_title.strip().lower(), torrent.parsed_year)
    return ("r", torrent.id)


THIN_RESULT = 8
MIN_LIVE_QUERY = 3
LIVE_TTL_SECONDS = 15 * 60
LIVE_RETRY_SECONDS = 60

_live_seen: dict[str, float] = {}
# One lock per query, so one slow search does not block the others.
_live_locks: dict[str, asyncio.Lock] = {}
# Bounded: lookups share the tracker's hourly request budget.
_live_slots = asyncio.Semaphore(3)


def _lock_for(key: str) -> asyncio.Lock:
    if len(_live_locks) > 500:
        _live_locks.clear()
    lock = _live_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _live_locks[key] = lock
    return lock


async def _consult_tracker(
    session: Session, q: str | None, offset: int, found: int
) -> bool:
    """Search the tracker for `q` when the catalog is thin. The tracker allows 150 requests an hour."""
    if not q or offset or found >= THIN_RESULT:
        return False
    term = q.strip()
    if len(term) < MIN_LIVE_QUERY:
        return False

    from ..services.filelist import search_live

    key = term.lower()
    async with _lock_for(key), _live_slots:
        now = time.monotonic()
        last = _live_seen.get(key)
        if last is not None and now - last < LIVE_TTL_SECONDS:
            return False
        if len(_live_seen) > 500:
            _live_seen.clear()
        _live_seen[key] = now

        # Hard timeout per source: a stalled dependency must not hang the search.
        result = None
        if settings.filelist_configured or not settings.addons_configured:
            try:
                result = await asyncio.wait_for(search_live(session, term), timeout=25)
            except Exception:
                log.exception("live search failed for %r", term)
                session.rollback()
                _live_seen[key] = now - LIVE_TTL_SECONDS + LIVE_RETRY_SECONDS
        fresh = 0
        if settings.addons_configured:
            from ..services import addons

            try:
                fresh = await asyncio.wait_for(addons.search_live(session, term), timeout=20)
            except Exception as exc:  # noqa: BLE001 - includes the timeout
                session.rollback()
                log.warning("addon search for %r cut short: %s", term, exc)
                if not settings.filelist_configured:
                    _live_seen[key] = now - LIVE_TTL_SECONDS + LIVE_RETRY_SECONDS

        if result is not None and result.error:
            _live_seen[key] = now - LIVE_TTL_SECONDS + LIVE_RETRY_SECONDS
        return fresh > 0 or bool(result and result.added > 0)


def _downloads_for(session: Session, torrent_ids: list[int]) -> dict[int, Download]:
    if not torrent_ids:
        return {}
    rows = session.scalars(
        select(Download).where(Download.torrent_id.in_(torrent_ids))
    )
    return {d.torrent_id: d for d in rows}


def _browse_query(
    q: str | None,
    category: int | None,
    resolution: str | None,
    media_type: str | None,
    genre: str | None,
    year: int | None,
    downloaded: bool | None,
):
    stmt = select(Torrent).options(selectinload(Torrent.media))

    stmt = stmt.outerjoin(Media, Torrent.media_id == Media.id)

    if q:
        term = q.strip()
        pattern = f"%{term}%"
        # Release names are dotted ("The.Tudors.S04"), so match the dotted phrase too.
        dotted = f"%{term.replace(' ', '.')}%"
        stmt = stmt.where(
            or_(
                Torrent.parsed_title.ilike(pattern),
                Torrent.name.ilike(pattern),
                Torrent.name.ilike(dotted),
                Torrent.imdb_id.ilike(pattern),
                Media.title.ilike(pattern),
            )
        )
    if category is not None:
        stmt = stmt.where(Torrent.category == category)
    if resolution:
        stmt = stmt.where(Torrent.resolution == resolution)
    if year is not None:
        stmt = stmt.where(Torrent.parsed_year == year)
    if media_type:
        stmt = stmt.where(Media.media_type == media_type)
    if genre:
        stmt = stmt.where(Media.genres.ilike(f'%"{genre}"%'))
    if downloaded:
        stmt = stmt.join(Download, Download.torrent_id == Torrent.id).where(
            Download.state != "removed"
        )
    return stmt


def _relevance(q: str):
    term = q.strip()
    title = func.coalesce(Media.title, Torrent.parsed_title, "")
    return case(
        (title.ilike(term), 0),
        (title.ilike(f"{term}%"), 1),
        (title.ilike(f"% {term}%"), 2),
        (title.ilike(f"%{term}%"), 3),
        else_=4,
    )


def _page(session: Session, stmt, sort: str, limit: int, offset: int, q: str | None = None):
    order = SORTS[sort]
    if q and q.strip() and sort == "newest":
        order = (_relevance(q), *order)
    if sort == "popular":
        # Titles first, then their releases, so one long show cannot fill the page.
        matching = stmt.with_only_columns(Torrent.media_id).where(Torrent.media_id.is_not(None))
        ids = list(session.scalars(
            select(Media.id).where(Media.id.in_(matching))
            .order_by(ranked_popularity().desc(), Media.id).offset(offset).limit(limit)
        ))
        grouped: dict[object, list[Torrent]] = {media_id: [] for media_id in ids}
        for torrent in session.scalars(
            stmt.where(Torrent.media_id.in_(ids)).order_by(Torrent.seeders.desc(), Torrent.id.desc())
        ):
            grouped[torrent.media_id].append(torrent)
        keys = [key for key in ids if grouped[key]]
    else:
        grouped = {}
        read, size = 0, limit * 4 + offset * 2
        while True:
            slab = session.scalars(stmt.order_by(*order).offset(read).limit(size)).all()
            for torrent in slab:
                grouped.setdefault(_group_key(torrent), []).append(torrent)
            read += len(slab)
            if len(slab) < size or len(grouped) > offset + limit:
                break
            size *= 2

        keys = list(grouped.keys())[offset : offset + limit]
    all_ids = [t.id for key in keys for t in grouped[key]]
    downloads = _downloads_for(session, all_ids)

    cards = [
        media_card(grouped[key][0].media, grouped[key], downloads,
                   fallback=grouped[key][0])
        for key in keys
    ]
    total = session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    return cards, total


@router.get("")
async def browse(
    session: Session = Depends(get_session),
    q: str | None = Query(None, description="free text search over title and release name"),
    category: int | None = None,
    resolution: str | None = None,
    media_type: str | None = Query(None, pattern="^(movie|tv)$"),
    genre: str | None = None,
    year: int | None = None,
    downloaded: bool | None = Query(None, description="only titles with a download"),
    sort: str = Query("newest", pattern="^(newest|oldest|seeders|size|title|popular)$"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    args = (q, category, resolution, media_type, genre, year, downloaded)
    cards, total = _page(session, _browse_query(*args), sort, limit, offset, q)

    if await _consult_tracker(session, q, offset, len(cards)):
        cards, total = _page(session, _browse_query(*args), sort, limit, offset, q)

    return {
        "items": cards,
        "limit": limit,
        "offset": offset,
        "total_releases": total,
        "returned": len(cards),
    }


@router.get("/home")
def home(
    session: Session = Depends(get_session),
    media_type: str | None = Query(None, pattern="^(movie|tv)$"),
    profile_id: int | None = Depends(current_profile_id),
):
    from ..services import rows as rows_service

    from .profiles import resolve_profile

    profile = resolve_profile(session, profile_id)
    built = rows_service.home_rows(session, media_type, profile_id=profile.id)
    if not built:
        return {"hero": None, "rows": []}

    payload_rows = _rows_payload(session, built)
    return {"hero": _pick_hero(payload_rows), "rows": payload_rows}


def _rows_payload(session: Session, built) -> list[dict]:
    torrent_ids = [
        t.id for row in built for entry in row.items for t in entry[1]
    ]
    downloads = _downloads_for(session, torrent_ids)

    payload_rows = []
    for row in built:
        cards = []
        for entry in row.items:
            media, torrents = entry[0], entry[1]
            extra = entry[2] if len(entry) > 2 else None
            card = media_card(media, torrents, downloads)
            if extra:
                card.update(extra)
            cards.append(card)
        if cards:
            payload_rows.append(
                {"id": row.id, "title": row.title, "kind": row.kind, "items": cards}
            )
    return payload_rows


@router.get("/episodes/{episode_id}/still.jpg")
def episode_still_image(episode_id: int):
    from fastapi.responses import FileResponse

    from ..services import stills

    path = stills.still_path(episode_id)
    if not os.path.exists(path):
        raise HTTPException(404, "no still")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/episodes/{episode_id}/about")
async def episode_about(episode_id: int, session: Session = Depends(get_session)):
    from .player import episode_about as about

    episode = session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(404, "no such episode")
    return await about(session, episode)


@router.get("/mine")
def mine(
    session: Session = Depends(get_session),
    profile_id: int | None = Depends(current_profile_id),
):
    from ..services import rows as rows_service

    from .profiles import resolve_profile

    profile = resolve_profile(session, profile_id)
    return {"rows": _rows_payload(session, rows_service.mine_rows(session, profile.id))}


@router.get("/my-list")
def my_list(
    session: Session = Depends(get_session),
    profile_id: int | None = Depends(current_profile_id),
):
    from ..models import MyListItem, WatchProgress
    from ..services import rows as rows_service
    from .profiles import resolve_profile

    profile = resolve_profile(session, profile_id)
    entries = rows_service.my_list(session, profile.id, limit=None)
    if not entries:
        return {"items": []}

    media_ids = [media.id for media, _ in entries]
    added = dict(session.execute(
        select(MyListItem.media_id, MyListItem.added_at).where(
            MyListItem.profile_id == profile.id, MyListItem.media_id.in_(media_ids)
        )
    ).all())
    started: set[int] = set(session.scalars(
        select(Episode.media_id)
        .join(EpisodeProgress, EpisodeProgress.episode_id == Episode.id)
        .where(EpisodeProgress.profile_id == profile.id, Episode.media_id.in_(media_ids))
    ).all())
    started |= set(session.scalars(
        select(Torrent.media_id)
        .join(Download, Download.torrent_id == Torrent.id)
        .join(WatchProgress, WatchProgress.download_id == Download.id)
        .where(WatchProgress.profile_id == profile.id, Torrent.media_id.in_(media_ids))
    ).all())

    downloads = _downloads_for(session, [t.id for _, torrents in entries for t in torrents])
    items = []
    for media, torrents in entries:
        card = media_card(media, torrents, downloads)
        card["started"] = media.id in started
        card["added_at"] = added[media.id].isoformat() if added.get(media.id) else None
        items.append(card)
    return {"items": items}


_WEAK_HERO_ROWS = {"library", "continue", "mylist"}


def _pick_hero(payload_rows: list[dict]) -> dict | None:
    best = None
    best_score = float("-inf")
    seen: set = set()

    for row in payload_rows:
        weight = 0.6 if row["id"] in _WEAK_HERO_ROWS else 1.0
        for position, card in enumerate(row["items"][:10]):
            if not card.get("backdrop") or not card.get("overview"):
                continue
            key = card.get("media_id") or card.get("primary_release_id")
            if key in seen:
                continue
            seen.add(key)

            rating = card.get("vote_average") or 0
            score = rating * weight
            score -= position * 0.12
            quality = card.get("quality") or {}
            if quality.get("resolution") == "2160p":
                score += 0.8
            if quality.get("hdr"):
                score += 0.4
            download = card.get("download")
            if download and download.get("playable"):
                score += 1.2

            if score > best_score:
                best, best_score = card, score

    return best


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    total = session.scalar(select(func.count()).select_from(Torrent)) or 0
    enriched = session.scalar(
        select(func.count()).select_from(Media).where(Media.enrich_status == "ok")
    ) or 0
    pending = session.scalar(
        select(func.count()).select_from(Torrent).where(Torrent.media_id.is_(None))
    ) or 0
    by_resolution = dict(
        session.execute(
            select(Torrent.resolution, func.count())
            .group_by(Torrent.resolution)
            .order_by(func.count().desc())
        ).all()
    )
    by_state = dict(
        session.execute(
            select(Download.state, func.count()).group_by(Download.state)
        ).all()
    )
    newest = session.scalar(select(func.max(Torrent.upload_date)))

    from ..services.library import free_bytes

    try:
        free_gb = round(free_bytes() / 1024 ** 3, 1)
    except OSError:
        free_gb = None

    return {
        "releases": total,
        "media_enriched": enriched,
        "awaiting_enrichment": pending,
        "by_resolution": by_resolution,
        "downloads_by_state": by_state,
        "newest_release": newest.isoformat() if newest else None,
        "free_disk_gb": free_gb,
    }


@router.get("/media/{media_id}")
async def media_detail(
    media_id: int,
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(404, "unknown media")
    stale = media.facts is None or '"person_ids"' not in media.facts
    if stale and media.tmdb_id and settings.tmdb_configured:
        from ..services.tmdb import refresh_facts

        try:
            await refresh_facts(session, media)
        except Exception as exc:  # noqa: BLE001
            # A failed flush refuses everything until rolled back (PendingRollbackError).
            session.rollback()
            logging.getLogger(__name__).warning(
                "could not fetch details for %s: %s", media.title, exc
            )

    if settings.addons_configured:
        from ..services import addons

        try:
            await asyncio.wait_for(addons.refresh_title(session, media), timeout=8)
        except Exception as exc:  # noqa: BLE001 - includes the timeout
            session.rollback()
            logging.getLogger(__name__).warning(
                "addon refresh of %s cut short: %s", media.title, exc
            )

    torrents = list(session.scalars(select(Torrent).where(Torrent.media_id == media_id)))
    downloads = _downloads_for(session, [t.id for t in torrents])
    card = media_card(media, torrents, downloads)
    try:
        card["facts"] = json.loads(media.facts) if media.facts else {}
    except ValueError:
        card["facts"] = {}

    if media.media_type == "tv":
        from ..services import shows

        seasons = list(session.scalars(
            select(Season).where(Season.media_id == media.id).order_by(Season.number)
        ))
        if not seasons and settings.tmdb_configured:
            try:
                await shows.sync_seasons(session, media)
                seasons = list(session.scalars(
                    select(Season).where(Season.media_id == media.id)
                    .order_by(Season.number)
                ))
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logging.getLogger(__name__).warning(
                    "could not fetch seasons for %s: %s", media.title, exc
                )

        held = {
            row.season_number
            for row in session.scalars(
                select(Episode).where(Episode.media_id == media.id,
                                      Episode.file_path.is_not(None))
            )
        }
        from ..services.nextup import next_up
        from .profiles import resolve_profile

        card["next_up"] = next_up(
            session, media.id, profile_id and resolve_profile(session, profile_id).id
        )
        from ..services.plan import show_plan

        try:
            card["plan"] = await show_plan(
                session, media, profile_id and resolve_profile(session, profile_id).id,
                downloads,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logging.getLogger(__name__).warning("could not plan %s: %s", media.title, exc)
            card["plan"] = None
        card["seasons"] = [
            {
                "number": s.number,
                "name": s.name or f"Season {s.number}",
                "overview": s.overview,
                "air_date": s.air_date,
                "poster": poster_url(s.poster_path),
                "episode_count": s.episode_count,
                "downloaded": s.number in held,
            }
            # Season 0 is specials: listed last.
            for s in sorted(seasons, key=lambda x: (x.number == 0, x.number))
            if s.episode_count or s.number in held
        ]

    return card


@router.get("/media/{media_id}/similar")
def similar(
    media_id: int,
    limit: int = Query(24, ge=1, le=60),
    session: Session = Depends(get_session),
):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(404, "unknown media")

    def names(raw: str | None) -> set[str]:
        try:
            return set(json.loads(raw)) if raw else set()
        except (ValueError, TypeError):
            return set()

    def keywords(raw: str | None) -> set[str]:
        try:
            return set((json.loads(raw) or {}).get("keywords") or []) if raw else set()
        except (ValueError, TypeError, AttributeError):
            return set()

    genres, words = names(media.genres), keywords(media.facts)
    if not genres:
        return {"items": []}
    scored = []
    for other in session.scalars(
        select(Media).where(
            Media.id != media.id,
            Media.media_type == media.media_type,
            Media.genres.is_not(None),
            Media.title != "",
            or_(Media.poster_path.is_not(None), Media.backdrop_path.is_not(None)),
            Media.torrents.any(),
        )
    ):
        shared = genres & names(other.genres)
        if not shared:
            continue
        score = (
            len(shared) * 3
            + len(words & keywords(other.facts)) * 2
            + min(other.popularity or 0, 500) / 500
            + (other.vote_average or 0) / 10
        )
        score *= 0.25 + 0.75 * title_weight(other)
        scored.append((score, other))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [other for _score, other in scored[:limit]]

    return {"items": _cards(session, top)}


def _cards(session: Session, medias: list[Media]) -> list[dict]:
    torrents: dict[int, list[Torrent]] = {}
    for torrent in session.scalars(
        select(Torrent).where(Torrent.media_id.in_([m.id for m in medias]))
    ):
        torrents.setdefault(torrent.media_id, []).append(torrent)
    downloads = _downloads_for(session, [t.id for group in torrents.values() for t in group])
    return [media_card(m, torrents.get(m.id, []), downloads) for m in medias]


_people: dict[int, tuple[float, dict]] = {}
PERSON_TTL = 3600
PEOPLE_MAX = 500


def _remember_person(person_id: int, details: dict) -> None:
    now = time.monotonic()
    for key in [k for k, (at, _d) in _people.items() if now - at >= PERSON_TTL]:
        _people.pop(key, None)
    while len(_people) >= PEOPLE_MAX:
        _people.pop(min(_people, key=lambda k: _people[k][0]))
    _people[person_id] = (now, details)


_missing_seasons: dict[tuple[int, int], float] = {}
MISSING_SEASON_TTL = 600


@router.get("/person/{person_id}")
async def person(person_id: int, session: Session = Depends(get_session)):
    import time

    from ..services.tmdb import TMDBClient, TMDBError, poster_url

    cached = _people.get(person_id)
    if cached and time.monotonic() - cached[0] < PERSON_TTL:
        details = cached[1]
    else:
        if not settings.tmdb_configured:
            raise HTTPException(503, "TMDB is not configured")
        try:
            details = await TMDBClient().person(person_id)
        except TMDBError as exc:
            raise HTTPException(404, f"unknown person: {exc}") from exc
        if not details.get("name"):
            raise HTTPException(404, "unknown person")
        _remember_person(person_id, details)

    credits = details.get("combined_credits") or {}
    wanted = {
        (item.get("id"), item.get("media_type"))
        for item in [*(credits.get("cast") or []), *(credits.get("crew") or [])]
        if item.get("id") and item.get("media_type") in ("movie", "tv")
    }
    medias = []
    for kind in ("movie", "tv"):
        ids = [tmdb_id for tmdb_id, media_type in wanted if media_type == kind]
        if ids:
            medias += list(session.scalars(
                select(Media).where(Media.media_type == kind, Media.tmdb_id.in_(ids),
                                    Media.torrents.any())
            ))
    medias.sort(key=lambda m: (m.popularity or 0) * title_weight(m), reverse=True)
    return {
        "id": person_id,
        "name": details.get("name"),
        "profile": poster_url(details.get("profile_path"), "w185"),
        "known_for": details.get("known_for_department"),
        "items": _cards(session, medias),
    }


@router.get("/media/{media_id}/seasons/{number}")
async def season_detail(
    media_id: int,
    number: int,
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    from ..services import shows
    from .profiles import resolve_profile

    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(404, "unknown media")

    season = None
    missing_since = _missing_seasons.get((media_id, number))
    recently_missing = missing_since is not None \
        and time.monotonic() - missing_since < MISSING_SEASON_TTL
    if settings.tmdb_configured and not recently_missing:
        try:
            season = await shows.sync_episodes(session, media, number)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logging.getLogger(__name__).warning("season sync failed: %s", exc)
    if season is None:
        season = session.scalar(
            select(Season).where(Season.media_id == media_id, Season.number == number)
        )
    if season is None:
        if not recently_missing:
            if len(_missing_seasons) > 2000:
                _missing_seasons.clear()
            _missing_seasons[(media_id, number)] = time.monotonic()
        raise HTTPException(404, "unknown season")

    if settings.addons_configured:
        from ..services import addons

        try:
            await asyncio.wait_for(addons.refresh_season(session, media, number), timeout=10)
        except Exception as exc:  # noqa: BLE001 - includes the timeout
            session.rollback()
            logging.getLogger(__name__).warning(
                "addon refresh of %s season %s cut short: %s", media.title, number, exc
            )

    profile = resolve_profile(session, profile_id)
    progress = {
        row.episode_id: row
        for row in session.scalars(
            select(EpisodeProgress).where(EpisodeProgress.profile_id == profile.id)
        )
    }

    episodes = sorted(season.episodes, key=lambda e: e.number)

    downloads_by_torrent = _downloads_for(
        session, [t.id for t in media.torrents]
    )
    coverage = {
        e.id: shows.releases_for(session, media, number, e.number) for e in episodes
    }

    from ..services import downloads as dl_service

    packs: dict[int, dict | None] = {}
    for torrent in {t for releases in coverage.values() for t in releases if t.episode is None}:
        meta = dl_service.cached_meta(torrent.id)
        if meta is None:
            packs[torrent.id] = None
            continue
        slots = await shows.slot_files(
            session, media, torrent, shows.pack_video_paths(meta.files), sync=False
        )
        packs[torrent.id] = {"slots": slots, "sizes": {f.path: f.length for f in meta.files}}
    episode_count = max(1, season.episode_count or len(episodes))

    from ..services.ranking import rank

    from ..services.offered import offered

    whole = [
        scored.torrent for scored in rank([
            t for t in offered(media.torrents, downloads_by_torrent)
            if t.episode is None and shows.covers(t, number, 1)
        ])
    ]
    season_pack = None
    if whole:
        best = whole[0]
        pack_download = downloads_by_torrent.get(best.id)
        season_pack = {
            **torrent_summary(best, pack_download),
            "complete_request": bool(
                pack_download and pack_download.state not in ("removed", "error")
                and dl_service.wanted_paths(pack_download) is None
            ),
        }

    payloads = [
        _episode_payload(
            e, progress.get(e.id), coverage.get(e.id, []), downloads_by_torrent,
            packs, episode_count,
        )
        for e in episodes
    ]
    await _own_progress(episodes, payloads, downloads_by_torrent)

    return {
        "media_id": media_id,
        "season": {
            "number": season.number,
            "name": season.name or f"Season {season.number}",
            "overview": season.overview,
            "air_date": season.air_date,
            "poster": poster_url(season.poster_path),
            "episode_count": season.episode_count,
            "downloaded": any(e.file_path for e in season.episodes),
        },
        "season_pack": season_pack,
        "episodes": payloads,
    }


async def _own_progress(episodes: list[Episode], payloads: list[dict],
                        downloads_by_torrent: dict[int, Download]) -> None:
    """An episode of a season pack, with progress measured from its own file in qBittorrent."""
    from ..services.qbit import QbitClient, QbitError

    coming = {
        payload["id"]: payload["download"]
        for payload in payloads
        if payload.get("download") and not payload["available"]
        and payload["download"]["state"] in ("downloading", "paused")
    }
    if not coming:
        return
    packs = {
        d.id: d for d in downloads_by_torrent.values()
        if d.info_hash and d.torrent is not None and d.torrent.episode is None
        and any(summary["id"] == d.id for summary in coming.values())
    }
    if not packs:
        return
    files: dict[int, list[dict]] = {}
    try:
        async with QbitClient() as client:
            for download in packs.values():
                files[download.id] = await client.files(download.info_hash)
    except QbitError:
        return
    for episode in episodes:
        summary = coming.get(episode.id)
        if summary is None or summary["id"] not in files:
            continue
        percent = episode_file_percent(episode, files[summary["id"]])
        if percent is not None:
            summary["percent"] = percent
            summary["progress"] = round(percent / 100, 4)


def episode_file_percent(episode: Episode, files: list[dict]) -> float | None:
    from ..services import shows
    from ..services.jobs import _is_video

    mine = [
        f for f in files
        if _is_video(f.get("name", ""))
        and shows.parse_slot(os.path.basename(f.get("name", "")))
        == (episode.season_number, episode.number)
    ]
    size = sum(int(f.get("size", 0)) for f in mine)
    if not size:
        return None
    done = sum(int(f.get("size", 0)) * float(f.get("progress", 0)) for f in mine)
    return round(done / size * 100, 1)


def _episode_payload(
    episode: Episode,
    progress: EpisodeProgress | None,
    releases: list[Torrent] | None = None,
    downloads: dict[int, Download] | None = None,
    packs: dict[int, dict | None] | None = None,
    episode_count: int = 1,
) -> dict:
    available = bool(episode.file_path)
    watched = progress.finished_at is not None if progress else False
    resume = progress.resume_seconds if progress else 0.0
    runtime = (progress.runtime_seconds if progress else 0.0) or (
        (episode.runtime or 0) * 60
    )
    return {
        "id": episode.id,
        "season": episode.season_number,
        "episode": episode.number,
        "name": episode.name or f"Episode {episode.number}",
        "overview": episode.overview,
        "air_date": episode.air_date,
        "runtime": episode.runtime,
        "still": stills.episode_still(episode),
        "vote_average": round(episode.vote_average, 1) if episode.vote_average else None,
        "available": available,
        "playable": episode.prepared_at is not None,
        "preparing": available and episode.prepared_at is None
        and episode.prepare_error is None,
        "prepare_error": episode.prepare_error,
        "play_id": f"e{episode.id}" if episode.prepared_at else None,
        "download_id": episode.download_id,
        "size_bytes": episode.file_size,
        "watched": watched,
        "resume_seconds": round(resume),
        "resume_percent": round(min(100.0, resume / runtime * 100), 1) if runtime else 0.0,
        "releases": [
            {
                **torrent_summary(t, (downloads or {}).get(t.id)),
                "season_pack": t.episode is None,
                **_episode_share(t, episode, (packs or {}).get(t.id), episode_count),
            }
            for t in (releases or [])
        ],
        "download": download_summary(
            _covering_download(releases, downloads, episode, packs)
        ),
    }


def _episode_share(torrent: Torrent, episode: Episode, pack: dict | None,
                   episode_count: int) -> dict:
    if torrent.episode is not None:
        return {"episode_size_gb": round((torrent.size_bytes or 0) / 1024 ** 3, 1),
                "episode_size_exact": True}
    if pack:
        path = pack["slots"].get((episode.season_number, episode.number))
        if path is not None:
            return {"episode_size_gb": round(pack["sizes"].get(path, 0) / 1024 ** 3, 1),
                    "episode_size_exact": True}
    share = (torrent.size_bytes or 0) / max(1, episode_count) / 1024 ** 3
    return {"episode_size_gb": round(share, 1), "episode_size_exact": False}


def _covering_download(
    releases: list[Torrent] | None, downloads: dict[int, Download] | None,
    episode: Episode | None = None, packs: dict[int, dict | None] | None = None,
) -> Download | None:
    from ..services.downloads import wanted_paths

    for torrent in releases or []:
        candidate = (downloads or {}).get(torrent.id)
        if not candidate or candidate.state in ("removed", "error"):
            continue
        wanted = wanted_paths(candidate)
        if wanted is not None and episode is not None:
            pack = (packs or {}).get(torrent.id)
            path = pack["slots"].get((episode.season_number, episode.number)) if pack else None
            if path not in wanted:
                continue
        return candidate
    return None


@router.get("/release/{torrent_id}")
def release_detail(torrent_id: int, session: Session = Depends(get_session)):
    torrent = session.get(Torrent, torrent_id)
    if torrent is None:
        raise HTTPException(404, "unknown release")
    downloads = _downloads_for(session, [torrent_id])
    return torrent_summary(torrent, downloads.get(torrent_id))


class Heard(BaseModel):
    heard: list[str] = []


@router.post("/spoken")
def spoken_search(body: Heard, session: Session = Depends(get_session)):
    from ..services import spoken

    return spoken.meant(session, [h[:200] for h in body.heard])


@router.get("/genres")
def genres(
    session: Session = Depends(get_session),
    media_type: str | None = Query(None, pattern="^(movie|tv)$"),
    order: str = Query("popular", pattern="^(popular|name)$"),
):
    import json
    from collections import Counter

    stmt = select(Media.genres).where(Media.genres.is_not(None), Media.torrents.any())
    if media_type:
        stmt = stmt.where(Media.media_type == media_type)
    counter: Counter[str] = Counter()
    for (raw,) in session.execute(stmt):
        try:
            for name in json.loads(raw):
                counter[name] += 1
        except (ValueError, TypeError):
            continue
    found = counter.most_common()
    if order == "name":
        found.sort(key=lambda pair: pair[0].casefold())
    return [{"name": name, "count": count} for name, count in found]
