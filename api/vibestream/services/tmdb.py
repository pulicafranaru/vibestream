"""TMDB enrichment: exact match by IMDb id via /find, else a scored title and year search."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import EnrichStatus, Media, MediaType, Torrent, utcnow
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"

# Concurrency cap for bulk backfills.
_semaphore = asyncio.Semaphore(8)


class TMDBError(RuntimeError):
    pass


class TMDBAuthError(TMDBError):
    pass


@dataclass
class EnrichResult:
    matched: int = 0
    notfound: int = 0
    failed: int = 0
    skipped: int = 0


def _year_of(date_str: str | None) -> int | None:
    if not date_str or len(date_str) < 4 or not date_str[:4].isdigit():
        return None
    return int(date_str[:4])


def _normalise_for_match(text: str) -> str:
    import re

    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    na, nb = _normalise_for_match(a), _normalise_for_match(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


class TMDBClient:
    def __init__(self, api_key: str | None = None, timeout: float = 20.0):
        self.api_key = api_key if api_key is not None else settings.tmdb_api_key
        # A short connect timeout: a handshake that is not fast is not happening.
        self.timeout = httpx.Timeout(timeout, connect=5.0)
        if not self.api_key:
            raise TMDBAuthError("TMDB_API_KEY is not set")

    async def _get(self, path: str, **params) -> dict:
        query = {"api_key": self.api_key, "language": settings.tmdb_language, **params}
        url = f"{BASE_URL}{path}"

        for attempt in range(4):
            try:
                async with _semaphore:
                    async with outbound_client(timeout=self.timeout) as client:
                        resp = await client.get(url, params=query)
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise TMDBError(f"TMDB unreachable for {path}: {exc}") from exc
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", "2")) + 1
                log.warning("tmdb rate limited, sleeping %ss", wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code == 401:
                raise TMDBAuthError("TMDB rejected the API key")
            if resp.status_code == 404:
                return {}
            if resp.status_code >= 500 and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                raise TMDBError(f"TMDB returned HTTP {resp.status_code} for {path}")
            return resp.json()

        raise TMDBError(f"TMDB gave up after retries for {path}")

    async def find_by_imdb(self, imdb_id: str) -> tuple[dict | None, str | None]:
        data = await self._get(f"/find/{imdb_id}", external_source="imdb_id")
        for key, media_type in (("movie_results", "movie"), ("tv_results", "tv")):
            results = data.get(key) or []
            if results:
                return results[0], media_type
        return None, None

    async def search(
        self, title: str, year: int | None, media_type: str = "movie"
    ) -> dict | None:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year" if media_type == "movie" else "first_air_date_year"] = str(year)

        data = await self._get(f"/search/{media_type}", **params)
        results = data.get("results") or []
        if not results and year:
            params.pop("year", None)
            params.pop("first_air_date_year", None)
            data = await self._get(f"/search/{media_type}", **params)
            results = data.get("results") or []
        if not results:
            return None

        def score(item: dict) -> float:
            name = item.get("title") or item.get("name") or ""
            s = _title_similarity(title, name)
            item_year = _year_of(item.get("release_date") or item.get("first_air_date"))
            if year and item_year:
                if item_year == year:
                    s += 0.25
                elif abs(item_year - year) == 1:
                    s += 0.10
                else:
                    s -= 0.20
            return s

        best = max(results, key=score)
        return best if score(best) >= 0.75 else None

    async def details(self, tmdb_id: int, media_type: str) -> dict:
        """The title and everything a detail page shows. Shows and films name their extras differently."""
        extras = (
            "external_ids,aggregate_credits,keywords,content_ratings,images"
            if media_type == "tv"
            else "external_ids,credits,keywords,release_dates,images"
        )
        # Images only for the title's logo: English, then language-less.
        return await self._get(
            f"/{media_type}/{tmdb_id}",
            append_to_response=extras,
            include_image_language="en,null",
        )

    async def search_any(self, query: str) -> list[dict]:
        data = await self._get("/search/multi", query=query, include_adult="false")
        return [r for r in data.get("results") or [] if r.get("media_type") in ("movie", "tv")]

    async def trending(self, media_type: str, window: str = "week") -> list[dict]:
        data = await self._get(f"/trending/{media_type}/{window}")
        return data.get("results") or []

    async def tv_details(self, tmdb_id: int) -> dict:
        return await self._get(f"/tv/{tmdb_id}")

    async def tv_season(self, tmdb_id: int, season: int) -> dict:
        return await self._get(f"/tv/{tmdb_id}/season/{season}")

    async def person(self, person_id: int) -> dict:
        return await self._get(f"/person/{person_id}", append_to_response="combined_credits")

    async def check_key(self) -> tuple[bool, str]:
        try:
            await self._get("/configuration")
            return True, "ok"
        except TMDBError as exc:
            return False, str(exc)


CAST_LIMIT = 8
CAST_ALL_LIMIT = 60
KEYWORD_LIMIT = 6
# Keywords about the production or the catalog entry rather than the story.
NOISE_KEYWORDS = frozenset({
    "miniseries", "duringcreditsstinger", "aftercreditsstinger", "woman director",
    "based on novel or book", "based on true story", "anime", "live action remake",
    "sequel", "remake", "3d", "short film", "tv movie", "docuseries",
})


def _names(items: list[dict] | None, limit: int | None = None) -> list[str]:
    out = [item.get("name") for item in items or [] if item.get("name")]
    return out[:limit] if limit else out


def _certification(details: dict, media_type: str) -> str | None:
    if media_type == "tv":
        by_region = {
            r.get("iso_3166_1"): r.get("rating")
            for r in (details.get("content_ratings") or {}).get("results") or []
        }
    else:
        by_region = {}
        for region in (details.get("release_dates") or {}).get("results") or []:
            ratings = [d.get("certification") for d in region.get("release_dates") or []]
            ratings = [r for r in ratings if r]
            if ratings:
                by_region[region.get("iso_3166_1")] = ratings[0]
    for region in settings.rating_regions:
        if by_region.get(region):
            return by_region[region]
    return None


def _logo(details: dict) -> str | None:
    """The title's logo: English before language-less, then best voted, PNG before SVG."""
    logos = (details.get("images") or {}).get("logos") or []
    if not logos:
        return None

    def rank(logo: dict) -> tuple:
        return (
            logo.get("iso_639_1") == "en",
            str(logo.get("file_path", "")).endswith(".png"),
            logo.get("vote_average") or 0,
            logo.get("width") or 0,
        )

    best = max(logos, key=rank)
    return best.get("file_path") or None


def _last_aired(details: dict) -> list[int] | None:
    last = details.get("last_episode_to_air") or {}
    season, episode = last.get("season_number"), last.get("episode_number")
    return [season, episode] if season is not None and episode is not None else None


def extract_facts(details: dict, media_type: str) -> dict:
    if media_type == "tv":
        cast = sorted(
            (details.get("aggregate_credits") or {}).get("cast") or [],
            key=lambda c: c.get("order", 999),
        )
        keywords = (details.get("keywords") or {}).get("results")
        makers = details.get("created_by") or []
        crew_heading, crew = "Creators", _names(makers)
    else:
        credits = details.get("credits") or {}
        cast = credits.get("cast") or []
        keywords = (details.get("keywords") or {}).get("keywords")
        crew_heading = "Director"
        makers = [c for c in credits.get("crew") or []
                  if c.get("job") == "Director" and c.get("name")]
        crew = [c.get("name") for c in makers]

    facts: dict = {
        "cast": _names(cast, CAST_LIMIT),
        # Capped only so a huge guest cast does not bloat every card.
        "cast_all": _names(cast, CAST_ALL_LIMIT),
        "person_ids": {
            person["name"]: person["id"]
            for person in [*cast[:CAST_ALL_LIMIT], *makers]
            if person.get("name") and person.get("id")
        },
        "crew_heading": crew_heading if crew else None,
        "crew": crew[:3],
        "keywords": [k for k in _names(keywords)
                     if k.lower() not in NOISE_KEYWORDS][:KEYWORD_LIMIT],
        "certification": _certification(details, media_type),
        "original_language": details.get("original_language"),
        "countries": details.get("origin_country")
        or [c.get("iso_3166_1") for c in details.get("production_countries") or []],
        # Always present, None when TMDB has none, so the logo is asked about once.
        "logo": _logo(details),
    }
    if media_type == "tv":
        facts.update({
            "limited": details.get("type") == "Miniseries",
            "seasons": details.get("number_of_seasons"),
            "episodes": details.get("number_of_episodes"),
            # Episodes per season and the last one aired, for services/coverage.py. None when not aired.
            "season_episodes": {
                str(s["season_number"]): s.get("episode_count") or 0
                for s in details.get("seasons") or []
                if s.get("season_number") is not None
            },
            "last_aired": _last_aired(details),
            "status": details.get("status"),
            "networks": _names(details.get("networks"), 2),
        })
    else:
        facts["studios"] = _names(details.get("production_companies"), 2)
    return facts


def _apply_details(media: Media, details: dict, media_type: str) -> None:
    media.media_type = media_type
    media.tmdb_id = details.get("id") or media.tmdb_id
    media.title = details.get("title") or details.get("name") or media.title
    media.original_title = (
        details.get("original_title") or details.get("original_name")
    )
    date_str = details.get("release_date") or details.get("first_air_date")
    media.release_date = date_str or None
    media.year = _year_of(date_str) or media.year
    media.overview = details.get("overview") or None
    media.tagline = details.get("tagline") or None
    media.poster_path = details.get("poster_path") or None
    media.backdrop_path = details.get("backdrop_path") or None
    media.vote_average = details.get("vote_average")
    media.vote_count = details.get("vote_count")
    media.popularity = details.get("popularity")

    runtime = details.get("runtime")
    if runtime is None:
        episode_runtimes = details.get("episode_run_time") or []
        runtime = episode_runtimes[0] if episode_runtimes else None
    media.runtime = runtime

    genres = [g.get("name") for g in details.get("genres") or [] if g.get("name")]
    media.genres = json.dumps(genres) if genres else None
    media.facts = json.dumps(extract_facts(details, media_type))

    external = details.get("external_ids") or {}
    if external.get("imdb_id"):
        media.imdb_id = external["imdb_id"]
    elif details.get("imdb_id"):
        media.imdb_id = details["imdb_id"]

    media.enrich_status = EnrichStatus.ok.value
    media.enrich_error = None
    media.enriched_at = utcnow()


def _find_or_create_media(
    session: Session, tmdb_id: int, media_type: str
) -> Media:
    existing = session.scalar(
        select(Media).where(Media.tmdb_id == tmdb_id, Media.media_type == media_type)
    )
    if existing:
        return existing
    created = Media(tmdb_id=tmdb_id, media_type=media_type)
    session.add(created)
    session.flush()
    return created


async def media_for(
    session: Session, client: TMDBClient, tmdb_id: int, media_type: str
) -> Media | None:
    existing = session.scalar(
        select(Media).where(Media.tmdb_id == tmdb_id, Media.media_type == media_type)
    )
    if existing is not None and existing.enrich_status == EnrichStatus.ok.value:
        return existing
    details = await client.details(tmdb_id, media_type)
    if not details:
        return existing
    media = _find_or_create_media(session, tmdb_id, media_type)
    _apply_details(media, details, media_type)
    session.commit()
    return media


async def enrich_torrent(
    session: Session, client: TMDBClient, torrent: Torrent
) -> str:
    from .filelist import media_type_for_category

    expected_type = media_type_for_category(torrent.category)
    if torrent.season is not None:
        expected_type = "tv"

    try:
        result, media_type = (None, None)

        if torrent.imdb_id:
            result, media_type = await client.find_by_imdb(torrent.imdb_id)

        if not result and torrent.parsed_title:
            media_type = expected_type
            result = await client.search(
                torrent.parsed_title, torrent.parsed_year, media_type
            )
            if not result:
                other = "tv" if media_type == "movie" else "movie"
                result = await client.search(
                    torrent.parsed_title, torrent.parsed_year, other
                )
                if result:
                    media_type = other

        if not result:
            placeholder = session.scalar(
                select(Media).where(
                    Media.tmdb_id.is_(None),
                    Media.title == (torrent.parsed_title or torrent.name),
                    Media.year.is_(torrent.parsed_year),
                )
            )
            if not placeholder:
                placeholder = Media(
                    tmdb_id=None,
                    media_type=expected_type,
                    title=torrent.parsed_title or torrent.name,
                    year=torrent.parsed_year,
                    imdb_id=torrent.imdb_id,
                    enrich_status=EnrichStatus.notfound.value,
                    enriched_at=utcnow(),
                )
                session.add(placeholder)
                session.flush()
            torrent.media_id = placeholder.id
            return "notfound"

        # Fetch before writing: creating the row opens SQLite's write transaction,
        # which must not be held across a network round trip.
        existing = session.scalar(
            select(Media).where(Media.tmdb_id == result["id"],
                                Media.media_type == media_type)
        )
        details = None
        if existing is None or existing.enrich_status != EnrichStatus.ok.value:
            details = await client.details(result["id"], media_type)

        media = _find_or_create_media(session, result["id"], media_type)
        if media.enrich_status != EnrichStatus.ok.value:
            _apply_details(media, details or result, media_type)
        torrent.media_id = media.id
        return "matched"

    except TMDBAuthError:
        raise
    except Exception:
        # Left unattached on purpose: a transient failure is not an answer, and the
        # next pass retries it.
        log.exception("enrichment failed for torrent %s", torrent.id)
        return "failed"


async def enrich_pending(session: Session, limit: int = 200) -> EnrichResult:
    result = EnrichResult()

    try:
        client = TMDBClient()
    except TMDBAuthError as exc:
        record_event(session, "tmdb", "enrichment skipped", str(exc), level="warn")
        return result

    stmt = (
        select(Torrent)
        .where(Torrent.media_id.is_(None), Torrent.gone_at.is_(None))
        .order_by(Torrent.upload_date.desc().nullslast(), Torrent.id.desc())
        .limit(limit)
    )
    pending = list(session.scalars(stmt))
    if not pending:
        return result

    for torrent in pending:
        try:
            outcome = await enrich_torrent(session, client, torrent)
        except TMDBAuthError as exc:
            record_event(session, "tmdb", "enrichment aborted", str(exc), level="error")
            break
        if outcome == "matched":
            result.matched += 1
        elif outcome == "notfound":
            result.notfound += 1
        else:
            result.failed += 1

        # Commit every row: a write transaction held across TMDB calls makes every
        # other writer hit the busy timeout.
        session.commit()

    session.commit()
    record_event(
        session,
        "tmdb",
        f"enriched {result.matched} matched, {result.notfound} unmatched",
        f"failed={result.failed} batch={len(pending)}",
    )
    return result


def _title_group(torrent: Torrent) -> tuple:
    if torrent.imdb_id:
        return ("i", torrent.imdb_id)
    return ("t", (torrent.parsed_title or torrent.name or "").strip().lower(),
            torrent.parsed_year)


async def enrich_torrents(
    session: Session, torrents: list[Torrent], budget_seconds: float = 8.0
) -> EnrichResult:
    """Match these releases now: one lookup per title, giving up after `budget_seconds`."""
    result = EnrichResult()
    if not torrents:
        return result

    try:
        client = TMDBClient()
    except TMDBAuthError as exc:
        record_event(session, "tmdb", "enrichment skipped", str(exc), level="warn")
        return result

    groups: dict[tuple, list[Torrent]] = {}
    for torrent in torrents:
        if torrent.media_id:
            continue
        groups.setdefault(_title_group(torrent), []).append(torrent)

    deadline = time.monotonic() + budget_seconds
    for members in groups.values():
        if time.monotonic() > deadline:
            break
        first, rest = members[0], members[1:]
        try:
            outcome = await enrich_torrent(session, client, first)
        except TMDBAuthError as exc:
            record_event(session, "tmdb", "enrichment aborted", str(exc), level="error")
            break
        if outcome == "matched":
            result.matched += 1
        elif outcome == "notfound":
            result.notfound += 1
        else:
            result.failed += 1

        if first.media_id:
            for other in rest:
                other.media_id = first.media_id
        # Commit per group: never hold the write transaction across a network call.
        session.commit()

    return result


async def refresh_facts(session: Session, media: Media) -> bool:
    if media.tmdb_id is None:
        return False
    details = await TMDBClient().details(media.tmdb_id, media.media_type)
    if not details:
        return False
    _apply_details(media, details, media.media_type)
    session.commit()
    return True


async def backfill_facts(session: Session, limit: int = 300) -> int:
    try:
        client = TMDBClient()
    except TMDBAuthError:
        return 0
    rows = list(session.scalars(
        select(Media)
        .where(Media.tmdb_id.is_not(None),
               or_(Media.facts.is_(None), ~Media.facts.contains('"logo"'),
                   ~Media.facts.contains('"person_ids"'),
                   and_(Media.media_type == "tv",
                        ~Media.facts.contains('"last_aired"'))),
               Media.enrich_status == EnrichStatus.ok.value)
        .order_by(Media.popularity.desc().nulls_last())
        .limit(limit)
    ))

    async def fetch(media: Media) -> tuple[Media, dict | None]:
        try:
            return media, await client.details(media.tmdb_id, media.media_type)
        except TMDBAuthError:
            raise
        except Exception:  # noqa: BLE001 - one title is not worth the batch
            return media, None

    done = 0
    for start in range(0, len(rows), 50):
        chunk = rows[start:start + 50]
        for media, details in await asyncio.gather(*(fetch(m) for m in chunk)):
            if details:
                _apply_details(media, details, media.media_type)
                done += 1
            else:
                # Answered, so it is not asked again every pass; what was known is kept.
                try:
                    known = json.loads(media.facts) if media.facts else {}
                except ValueError:
                    known = {}
                known.setdefault("logo", None)
                known.setdefault("cast_all", known.get("cast") or [])
                known.setdefault("person_ids", {})
                media.facts = json.dumps(known)
        session.commit()
    if done:
        log.info("collected details for %s title(s)", done)
    return done


async def enrich_media_details(session: Session, limit: int = 500) -> EnrichResult:
    result = EnrichResult()

    try:
        client = TMDBClient()
    except TMDBAuthError as exc:
        record_event(session, "tmdb", "detail fetch skipped", str(exc), level="warn")
        return result

    stmt = (
        select(Media)
        .where(
            Media.tmdb_id.is_not(None),
            Media.enrich_status == EnrichStatus.pending.value,
        )
        .limit(limit)
    )
    pending = list(session.scalars(stmt))
    if not pending:
        return result

    async def fetch(media: Media) -> tuple[Media, dict | None, str | None]:
        try:
            return media, await client.details(media.tmdb_id, media.media_type), None
        except TMDBAuthError:
            raise
        except Exception as exc:
            return media, None, str(exc)

    for chunk_start in range(0, len(pending), 50):
        chunk = pending[chunk_start : chunk_start + 50]
        try:
            outcomes = await asyncio.gather(*(fetch(m) for m in chunk))
        except TMDBAuthError as exc:
            record_event(session, "tmdb", "detail fetch aborted", str(exc), level="error")
            break

        for media, details, error in outcomes:
            if error:
                media.enrich_status = EnrichStatus.error.value
                media.enrich_error = error[:500]
                media.enriched_at = utcnow()
                result.failed += 1
            elif details:
                _apply_details(media, details, media.media_type)
                result.matched += 1
            else:
                media.enrich_status = EnrichStatus.notfound.value
                media.enriched_at = utcnow()
                result.notfound += 1
        session.commit()
        log.info("enriched %s/%s media rows", chunk_start + len(chunk), len(pending))

    record_event(
        session,
        "tmdb",
        f"filled details for {result.matched} title(s)",
        f"notfound={result.notfound} failed={result.failed}",
    )
    return result


def still_url(path: str | None, size: str = "w300") -> str | None:
    if not path:
        return None
    return f"{settings.tmdb_image_base}/{size}{path}"


def poster_url(path: str | None, size: str = "w500") -> str | None:
    if not path:
        return None
    return f"{settings.tmdb_image_base}/{size}{path}"


def logo_url(path: str | None, size: str = "w500") -> str | None:
    if not path:
        return None
    return f"{settings.tmdb_image_base}/{size}{path}"


def backdrop_url(path: str | None, size: str = "w1280") -> str | None:
    if not path:
        return None
    return f"{settings.tmdb_image_base}/{size}{path}"
