"""Filelist API client and the incremental catalog sweep (150 API requests an hour)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import Media, Torrent, utcnow
from ..titles import parse_release
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

API_URL = "https://filelist.io/api.php"

# Enumerated against the live API; the numbering is irregular
# (5 is FLAC, 6 is Movies 4K). Id 14 is rejected as invalid.
CATEGORY_NAMES = {
    1: "Movies SD", 2: "Movies DVD", 3: "Movies DVD-RO", 4: "Movies HD",
    5: "FLAC", 6: "Movies 4K", 7: "XXX", 8: "Apps", 9: "Games PC",
    10: "Games Console", 11: "Music", 12: "Videoclips", 13: "Sport",
    15: "Cartoons", 16: "Docs", 17: "Linux", 18: "Various",
    19: "Movies HD-RO", 20: "Movies Blu-Ray", 21: "TV-Series HD", 22: "Mobile",
    23: "TV-Series SD", 24: "Anime", 25: "Movies 3D",
    26: "Movies 4K Blu-Ray", 27: "TV-Series 4K", 28: "RO Dubbed",
    29: "Books", 30: "Courses",
}

MOVIE_CATEGORIES = {1, 2, 3, 4, 6, 19, 20, 25, 26}
TV_CATEGORIES = {21, 23, 27}
VIDEO_CATEGORIES = MOVIE_CATEGORIES | TV_CATEGORIES | {15, 16, 24}


def media_type_for_category(category: int | None) -> str:
    if category in TV_CATEGORIES:
        return "tv"
    return "movie"


class FilelistError(RuntimeError):
    pass


class FilelistAuthError(FilelistError):
    pass


class FilelistRateLimited(FilelistError):
    pass


class TorrentGone(FilelistError):
    """The tracker no longer has this release's .torrent: it was deleted."""


# download.php's answer (an HTML page, status 200, in the account's language)
# for a release the tracker has deleted.
GONE_PAGE = re.compile(rb"Nu pot gasi fisierul \.torrent|can.?t find the \.torrent", re.I)


class RateBudget:
    """Request budget, trusting x-ratelimit-remaining; a reserve keeps sweeps from starving searches."""

    CEILING = 150

    def __init__(self, reserve: int = 25):
        self.reserve = reserve
        self._remaining: int | None = None
        self._observed_at: float = 0.0
        self._local_hits: list[float] = []
        self._lock = asyncio.Lock()

    def observe(self, header_value: str | None) -> None:
        if not header_value:
            return
        try:
            self._remaining = int(header_value)
            self._observed_at = asyncio.get_event_loop().time()
        except (TypeError, ValueError):
            pass

    def _prune(self, now: float) -> None:
        self._local_hits = [t for t in self._local_hits if t > now - 3600]

    def remaining(self) -> int:
        loop = asyncio.get_event_loop()
        now = loop.time()
        self._prune(now)
        if self._remaining is None:
            return self.CEILING - len(self._local_hits)
        spent_since = len([t for t in self._local_hits if t > self._observed_at])
        return max(0, self._remaining - spent_since)

    async def acquire(self, *, reserved: bool = False) -> None:
        async with self._lock:
            floor = 0 if reserved else self.reserve
            if self.remaining() <= floor:
                raise FilelistRateLimited(
                    f"filelist budget nearly spent ({self.remaining()} left of "
                    f"{self.CEILING}/hour, reserve={self.reserve}). "
                    "The window is hourly, so try again later."
                )
            self._local_hits.append(asyncio.get_event_loop().time())


# Shared across all clients in the process, which is what makes the budget real.
budget = RateBudget()


@dataclass
class SweepResult:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _parse_upload_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("unparseable upload_date: %r", raw)
    return None


def _normalise_imdb(raw) -> str | None:
    if raw in (None, "", 0, "0"):
        return None
    s = str(raw).strip()
    if s.startswith("tt"):
        return s
    if s.isdigit():
        return f"tt{s.zfill(7)}"
    return None


def _as_bool(raw) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes")


def _as_int(raw, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class FilelistClient:
    def __init__(
        self,
        username: str | None = None,
        passkey: str | None = None,
        timeout: float = 30.0,
    ):
        self.username = username if username is not None else settings.filelist_username
        self.passkey = passkey if passkey is not None else settings.filelist_passkey
        self.timeout = timeout
        if not (self.username and self.passkey):
            raise FilelistAuthError("FILELIST_USERNAME and FILELIST_PASSKEY are not set")

    async def _request(self, action: str, *, reserved: bool = False, **params) -> list[dict]:
        query = {
            "username": self.username,
            "passkey": self.passkey,
            "action": action,
            **{k: v for k, v in params.items() if v not in (None, "")},
        }
        await budget.acquire(reserved=reserved)
        async with outbound_client(timeout=self.timeout) as client:
            resp = await client.get(API_URL, params=query)

        budget.observe(resp.headers.get("x-ratelimit-remaining"))

        if resp.status_code == 429:
            raise FilelistRateLimited("filelist rate limit reached (150 requests/hour)")
        if resp.status_code in (401, 403):
            raise FilelistAuthError(
                f"filelist rejected the credentials (HTTP {resp.status_code}). "
                "Check FILELIST_USERNAME and FILELIST_PASSKEY."
            )
        if resp.status_code != 200:
            raise FilelistError(f"filelist returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise FilelistError(f"filelist returned non-JSON: {resp.text[:200]}") from exc

        if isinstance(payload, dict):
            message = payload.get("error") or payload.get("message") or str(payload)
            lowered = str(message).lower()
            if "rate" in lowered or "limit" in lowered:
                raise FilelistRateLimited(message)
            if "passkey" in lowered or "user" in lowered or "auth" in lowered:
                raise FilelistAuthError(message)
            raise FilelistError(message)

        if not isinstance(payload, list):
            raise FilelistError(f"unexpected payload type {type(payload).__name__}")
        return payload

    async def latest(self, category: int, limit: int = 100) -> list[dict]:
        return await self._request(
            "latest-torrents", category=str(category), limit=str(min(limit, 100))
        )

    async def search(
        self,
        query: str,
        *,
        category: int | None = None,
        search_type: str = "name",
        limit: int = 100,
    ) -> list[dict]:
        # User initiated, so it may dip into the reserve the sweep cannot touch.
        return await self._request(
            "search-torrents",
            reserved=True,
            type=search_type,
            query=query,
            category=str(category) if category else None,
            limit=str(min(limit, 100)),
        )

    async def search_imdb(self, imdb_id: str, category: int | None = None) -> list[dict]:
        return await self.search(imdb_id, category=category, search_type="imdb")

    async def check_credentials(self) -> tuple[bool, str]:
        try:
            await self.latest(category=settings.filelist_categories[0], limit=1)
            return True, "ok"
        except FilelistError as exc:
            return False, str(exc)

    async def fetch_torrent_file(self, download_link: str) -> bytes:
        async with outbound_client(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(download_link)
        if resp.status_code != 200:
            raise FilelistError(f"torrent download failed: HTTP {resp.status_code}")
        body = resp.content
        if body[:1] != b"d":
            # Bencoded data always starts with 'd'. Anything else is an error page.
            if GONE_PAGE.search(body):
                raise TorrentGone("the tracker no longer has this release")
            raise FilelistError(f"torrent download returned non-bencoded data: {body[:120]!r}")
        return body


def category_id(raw: dict) -> int | None:
    """Sweeps return the numeric category, searches the label ("TV-Series HD")."""
    value = raw.get("category")
    if value is None or value == "":
        return None
    if isinstance(value, int) or str(value).isdigit():
        return int(value)
    for num, label in CATEGORY_NAMES.items():
        if label.lower() == str(value).lower():
            return num
    return None


def upsert_torrent(session: Session, raw: dict) -> tuple[Torrent, bool]:
    fl_id = _as_int(raw.get("id"))
    if not fl_id:
        raise ValueError(f"release has no id: {raw!r}")

    existing = session.get(Torrent, fl_id)
    created = existing is None
    row = existing or Torrent(id=fl_id)

    name = (raw.get("name") or "").strip()
    row.name = name

    category_raw = raw.get("category")
    row.category = category_id(raw)
    if isinstance(category_raw, int) or str(category_raw).isdigit():
        row.category_name = CATEGORY_NAMES.get(row.category)
    else:
        row.category_name = str(category_raw) if category_raw else None

    row.imdb_id = _normalise_imdb(raw.get("imdb"))
    row.size_bytes = _as_int(raw.get("size"))
    row.seeders = _as_int(raw.get("seeders"))
    row.leechers = _as_int(raw.get("leechers"))
    row.times_completed = _as_int(raw.get("times_completed"))
    row.file_count = _as_int(raw.get("files"), 1)
    row.freeleech = _as_bool(raw.get("freeleech"))
    row.doubleup = _as_bool(raw.get("doubleup"))
    row.internal = _as_bool(raw.get("internal"))
    row.moderated = _as_bool(raw.get("moderated"))
    row.small_description = raw.get("small_description") or None

    upload_date = _parse_upload_date(raw.get("upload_date"))
    if upload_date:
        row.upload_date = upload_date

    if created or not row.parsed_title:
        parsed = parse_release(name)
        row.parsed_title = parsed.title or None
        row.parsed_year = parsed.year
        row.resolution = parsed.resolution
        row.source = parsed.source
        row.video_codec = parsed.video_codec
        row.audio_codec = parsed.audio_codec
        row.hdr = parsed.hdr
        row.release_group = parsed.release_group
        row.season = parsed.season
        row.episode = parsed.episode
        row.season_end = parsed.season_end

    tv = raw.get("tv")
    if isinstance(tv, dict):
        season, episode = _as_int(tv.get("season"), 0), _as_int(tv.get("episode"), 0)
        if season:
            row.season = season
        if episode:
            row.episode = episode

    row.last_seen = utcnow()
    if created:
        row.first_seen = utcnow()
        session.add(row)

    if row.media_id is None and row.imdb_id and row.gone_at is None:
        known = session.scalar(
            select(Media.id).where(Media.imdb_id == row.imdb_id, Media.tmdb_id.is_not(None))
            .order_by(Media.id).limit(1)
        )
        if known is not None:
            row.media_id = known

    return row, created


async def sweep_categories(
    session: Session, categories: list[int] | None = None, limit: int = 100
) -> SweepResult:
    """The whole window is upserted every time, to refresh seeder counts."""
    result = SweepResult()
    cats = categories or settings.filelist_categories
    if not cats:
        result.errors.append("no categories configured")
        return result

    try:
        client = FilelistClient()
    except FilelistAuthError as exc:
        result.errors.append(str(exc))
        record_event(session, "filelist", "sweep skipped", str(exc), level="warn")
        session.commit()
        return result

    for category in cats:
        try:
            items = await client.latest(category=category, limit=limit)
        except FilelistRateLimited as exc:
            result.errors.append(f"category {category}: {exc}")
            record_event(session, "filelist", "rate limited", str(exc), level="warn")
            session.commit()
            break
        except FilelistError as exc:
            result.errors.append(f"category {category}: {exc}")
            record_event(
                session, "filelist", f"sweep failed for category {category}",
                str(exc), level="error",
            )
            # Committed now, or the next query holds the write lock across the next
            # request to the tracker.
            session.commit()
            continue

        result.fetched += len(items)
        for raw in items:
            try:
                if _as_int(raw.get("seeders")) < settings.filelist_min_seeders:
                    result.skipped += 1
                    continue
                _, created = upsert_torrent(session, raw)
                if created:
                    result.inserted += 1
                else:
                    result.updated += 1
            except Exception as exc:  # one bad row must not lose the batch
                result.errors.append(f"{raw.get('id')}: {exc}")
                log.exception("failed to upsert release %s", raw.get("id"))

        session.commit()
        await asyncio.sleep(1.0)

    record_event(
        session,
        "filelist",
        f"sweep complete: {result.inserted} new, {result.updated} refreshed",
        f"fetched={result.fetched} skipped={result.skipped} errors={len(result.errors)}",
    )
    session.commit()
    return result


ENRICH_BUDGET = 6.0


@dataclass
class LiveSearch:
    found: int = 0
    kept: int = 0
    added: int = 0
    error: str | None = None


async def search_live(session: Session, query: str, *, limit: int = 100) -> LiveSearch:
    """Ask the tracker about something the sweep has never seen. Non-video results are dropped."""
    result = LiveSearch()
    try:
        client = FilelistClient()
    except FilelistAuthError as exc:
        result.error = str(exc)
        return result

    try:
        raw = await client.search(query, limit=limit)
    except FilelistError as exc:
        result.error = str(exc)
        record_event(
            session, "filelist", "live search failed", f"{query}: {exc}", level="warn"
        )
        # Committed now, or the first query holds SQLite's write lock through every
        # addon request that follows.
        session.commit()
        return result

    result.found = len(raw)
    fresh: list[Torrent] = []
    for item in raw:
        if category_id(item) not in VIDEO_CATEGORIES:
            continue
        result.kept += 1
        try:
            row, created = upsert_torrent(session, item)
        except Exception as exc:  # one bad row must not lose the batch
            log.warning("live search could not store release %s: %s", item.get("id"), exc)
            continue
        if created:
            fresh.append(row)
    session.commit()
    result.added = len(fresh)

    if fresh:
        # Matched now, time-boxed: an unmatched release has no poster or title.
        # Whatever is not matched in time is picked up by the scheduled pass.
        from .tmdb import enrich_torrents

        try:
            await asyncio.wait_for(
                enrich_torrents(session, fresh, budget_seconds=ENRICH_BUDGET),
                timeout=ENRICH_BUDGET + 4,
            )
        except Exception as exc:  # noqa: BLE001 - includes the timeout
            log.warning("live search enrichment cut short for %r: %s", query, exc)
            session.rollback()

    record_event(
        session,
        "filelist",
        f"live search '{query}': {result.added} new",
        f"found={result.found} video={result.kept}",
    )
    session.commit()
    return result


def torrents_needing_media(session: Session, limit: int = 200) -> list[Torrent]:
    stmt = (
        select(Torrent)
        .where(Torrent.media_id.is_(None), Torrent.gone_at.is_(None))
        .order_by(Torrent.upload_date.desc().nullslast(), Torrent.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
