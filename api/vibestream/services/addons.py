"""Stremio addons: releases looked up by IMDb id, stored as Torrent rows with origin "addon"."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote, unquote, urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import Episode, Media, Season, Torrent, utcnow
from ..titles import parse_release
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

FIRST_ID = 1_000_000_000
MOST_ADDONS = 8

FRESH_SECONDS = 6 * 3600
RETRY_SECONDS = 120
# Trending-row questions wait in a line of their own, so a page being opened
# never queues behind them.
CONCURRENCY = 4
BACKGROUND_CONCURRENCY = 2
ANSWER_SECONDS = 6.0
MOST_EPISODES = 30
MOST_SEASONS = 12

METADATA_SECONDS = 60

# Added to every magnet: without them, a magnet from an addon that names no
# trackers relies on DHT alone.
TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
)

HASH = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{40})(?![0-9a-fA-F])")
SEEDERS = re.compile("\U0001F464\\s*(\\d+)")
SIZE = re.compile("\U0001F4BE\\s*([\\d.,]+)\\s*([KMGT]i?B)", re.I)
PROVIDER = re.compile("(?:\u2699\ufe0f?|\U0001F517|\U0001F50E|\U0001F50D)\\s*([^\\n]+?)\\s*$", re.M)
FIGURES = re.compile("[\U0001F464\U0001F4BE\u2699\U0001F517\U0001F50E\U0001F50D\U0001F30E]")
LEADING = re.compile(r"^[^\w\[(]+")
UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
# Read for the not-yet first, since "uncached" contains "cached".
NOT_HELD = re.compile("download\\]|\u2b07|\u23f3|uncached|not cached", re.I)
HELD = re.compile("\\+\\]|\u26a1|instant|cached", re.I)

class AddonError(RuntimeError):
    pass


def base_url(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("stremio://"):
        value = "https://" + value[len("stremio://"):]
    value = value.rstrip("/")
    if value.endswith("/manifest.json"):
        value = value[: -len("/manifest.json")]
    return value


def addresses() -> list[str]:
    return [base_url(u) for u in settings.addon_urls if u and u.strip()]


def label(address: str) -> str:
    """Host only: the rest of the address can hold a debrid key."""
    return urlsplit(address).hostname or "an addon"


@dataclass
class Found:
    info_hash: str
    name: str
    inner: str | None = None
    file_name: str | None = None
    seeders: int = 0
    size_bytes: int = 0
    provider: str | None = None
    trackers: list[str] = field(default_factory=list)
    link: str | None = None
    held: bool = False


def _size(number: str, unit: str) -> int:
    if "," in number and "." in number:
        number = number.replace(",", "")
    else:
        number = number.replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        return 0
    return int(value * UNITS.get(unit.upper().replace("I", ""), 1))


def _hash_of(item: dict, link: str | None) -> str | None:
    value = str(item.get("infoHash") or "")
    if re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return value.lower()
    hints = item.get("behaviorHints") or {}
    for text in (link, hints.get("bingeGroup") if isinstance(hints, dict) else None):
        if text and (match := HASH.search(unquote(str(text)))):
            return match.group(1).lower()
    return None


def parse_stream(item: dict) -> Found | None:
    link = item.get("url")
    link = link if isinstance(link, str) and link.startswith(("https://", "http://")) else None
    info_hash = _hash_of(item, link)
    if info_hash is None:
        return None
    text = str(item.get("description") or item.get("title") or "")
    lines = [line.strip() for line in text.split("\n")]
    at = next((i for i, line in enumerate(lines) if FIGURES.search(line)), len(lines))
    names = [LEADING.sub("", line).strip() for line in lines[:at]]
    names = [n for n in names if n]
    hints = item.get("behaviorHints") or {}
    if not isinstance(hints, dict):
        hints = {}
    file_name = hints.get("filename") if isinstance(hints.get("filename"), str) else None
    if not names and file_name:
        names = [file_name]
    if not names:
        return None
    found = Found(info_hash=info_hash, name=names[0][:512], link=link)
    if len(names) > 1:
        found.inner = names[1]
    found.file_name = file_name or (found.inner.rsplit("/", 1)[-1] if found.inner else None)
    if match := SEEDERS.search(text):
        found.seeders = int(match.group(1))
    if match := SIZE.search(text):
        found.size_bytes = _size(match.group(1), match.group(2))
    if not found.size_bytes and isinstance(hints.get("videoSize"), int):
        found.size_bytes = hints["videoSize"]
    if match := PROVIDER.search(text):
        found.provider = match.group(1)[:64]
    found.trackers = [
        source[len("tracker:"):] for source in item.get("sources") or []
        if isinstance(source, str) and source.startswith("tracker:")
    ]
    if link:
        title = str(item.get("name") or "")
        found.held = not NOT_HELD.search(title) and bool(HELD.search(title))
    return found


def _question(kind: str, imdb_id: str, season: int | None, episode: int | None) -> str:
    if kind == "movie":
        return f"movie/{imdb_id}"
    return f"series/{imdb_id}:{season}:{episode}"


async def ask_one(address: str, kind: str, imdb_id: str, season: int | None = None,
                  episode: int | None = None) -> list[dict]:
    url = f"{address}/stream/{_question(kind, imdb_id, season, episode)}.json"
    try:
        async with outbound_client(timeout=httpx.Timeout(ANSWER_SECONDS, connect=3.0)) as client:
            resp = await client.get(url)
    except httpx.InvalidURL as exc:
        raise AddonError(f"{label(address)} is not an address that can be asked") from exc
    if resp.status_code != 200:
        raise AddonError(f"{label(address)} answered HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise AddonError(f"{label(address)} did not answer with JSON") from exc
    items = payload.get("streams") if isinstance(payload, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


async def streams(kind: str, imdb_id: str, season: int | None = None,
                  episode: int | None = None) -> list[dict]:
    found = addresses()
    if not found:
        return []
    tasks = [asyncio.ensure_future(ask_one(a, kind, imdb_id, season, episode)) for a in found]
    try:
        await asyncio.wait(tasks, timeout=ANSWER_SECONDS + 1)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    items: list[dict] = []
    failed: list[BaseException] = []
    for address, task in zip(found, tasks):
        answer = task.exception() if not task.cancelled() else AddonError(
            f"{label(address)} took too long to answer")
        if answer is not None:
            if not isinstance(answer, (AddonError, httpx.HTTPError)):
                raise answer
            log.warning("%s could not answer for %s: %s", label(address), imdb_id,
                        str(answer) or answer.__class__.__name__)
            failed.append(answer)
        else:
            items += task.result()
    if failed and len(failed) == len(found):
        raise failed[0] if isinstance(failed[0], AddonError) else AddonError(str(failed[0]))
    return items


async def check() -> tuple[bool, str]:
    found = addresses()
    if not found:
        return False, "No addon address is set."
    problems = []
    for address in found:
        try:
            items = await ask_one(address, "movie", "tt0111161")
        except AddonError as exc:
            problems.append(str(exc) + ".")
            continue
        except httpx.HTTPError as exc:
            problems.append(f"{label(address)}: {str(exc) or exc.__class__.__name__}.")
            continue
        if not any(parse_stream(item) for item in items):
            problems.append(f"{label(address)} answered, but with no releases. Check the address.")
    if problems:
        return False, " ".join(problems)
    return True, "ok" if len(found) == 1 else f"{len(found)} addons answer"


async def link_for(torrent: Torrent, season: int | None = None,
                   episode: int | None = None) -> str | None:
    """Asked for again now rather than kept from the answer: some links expire."""
    media = torrent.media
    if media is None or not media.imdb_id or not torrent.info_hash:
        return None
    if media.media_type == "tv":
        season = season if season is not None else torrent.season
        episode = episode if episode is not None else torrent.episode
        if season is None or episode is None:
            return None
    for item in await streams(media.media_type, media.imdb_id, season, episode):
        found = parse_stream(item)
        if found and found.link and found.info_hash == torrent.info_hash:
            return found.link
    return None


def _category(media_type: str, resolution: str | None) -> int:
    if media_type == "tv":
        return 27 if resolution == "2160p" else 21
    return 6 if resolution == "2160p" else 4


def _next_id(session: Session) -> int:
    top = session.scalar(select(func.max(Torrent.id)).where(Torrent.id >= FIRST_ID))
    return (top or FIRST_ID - 1) + 1


def store(session: Session, media: Media, found: Found, season: int | None = None,
          episode: int | None = None) -> tuple[Torrent, bool]:
    row = session.scalar(
        select(Torrent).where(
            Torrent.origin == "addon",
            Torrent.info_hash == found.info_hash,
            Torrent.media_id == media.id,
        )
    )
    created = row is None
    if created:
        parsed = parse_release(found.name)
        row = Torrent(
            id=_next_id(session), origin="addon", info_hash=found.info_hash,
            media_id=media.id, name=found.name, size_bytes=found.size_bytes,
            file_count=2 if found.inner else 1,
            parsed_title=parsed.title or None, parsed_year=parsed.year,
            resolution=parsed.resolution, source=parsed.source,
            video_codec=parsed.video_codec, audio_codec=parsed.audio_codec,
            hdr=parsed.hdr, release_group=parsed.release_group,
            first_seen=utcnow(),
        )
        if media.media_type == "tv":
            row.season, row.episode, row.season_end = parsed.season, parsed.episode, parsed.season_end
        session.add(row)

    row.imdb_id = media.imdb_id
    row.category = _category(media.media_type, row.resolution)
    row.category_name = found.provider
    row.seeders = found.seeders
    row.last_seen = utcnow()
    if found.trackers:
        row.announce = json.dumps(found.trackers)
    row.linkable = bool(found.link)
    row.held = found.held
    if media.media_type == "movie" and found.file_name:
        row.file_name = found.file_name

    if media.media_type == "tv" and season is not None:
        if row.season is None:
            row.season = season
            row.episode = None if found.inner else episode
        elif row.episode is None:
            last = row.season_end or row.season
            if season < row.season:
                row.season_end, row.season = last, season
            elif season > last:
                row.season_end = season
    session.flush()
    return row, created


_asked: dict[str, float] = {}
_slots = asyncio.Semaphore(CONCURRENCY)
_background = asyncio.Semaphore(BACKGROUND_CONCURRENCY)


def forget() -> None:
    _asked.clear()


def _merged(items: list[dict]) -> list[Found]:
    by_hash: dict[str, Found] = {}
    for item in items:
        try:
            found = parse_stream(item)
        except Exception as exc:  # noqa: BLE001 - free text: one odd stream, not the answer
            log.warning("could not read a stream: %s", exc)
            continue
        if found is None:
            continue
        kept = by_hash.get(found.info_hash)
        if kept is None:
            by_hash[found.info_hash] = found
            continue
        kept.seeders = max(kept.seeders, found.seeders)
        kept.size_bytes = kept.size_bytes or found.size_bytes
        kept.link = kept.link or found.link
        kept.held = kept.held or found.held
        kept.provider = kept.provider or found.provider
        kept.inner = kept.inner or found.inner
        kept.file_name = kept.file_name or found.file_name
        kept.trackers = kept.trackers or found.trackers
    return list(by_hash.values())


async def _mark_torbox(found: list[Found]) -> None:
    """Releases TorBox already holds count as held, as a debrid addon's
    would: they arrive at once."""
    from . import torbox

    if not settings.torbox_configured or not found:
        return
    try:
        on_torbox = await torbox.held([f.info_hash for f in found])
    except (torbox.TorboxError, httpx.HTTPError) as exc:
        log.warning("could not ask TorBox what it holds: %s", exc)
        return
    for f in found:
        if f.info_hash.lower() in on_torbox:
            f.held = True


def _fresh(key: str) -> bool:
    at = _asked.get(key)
    return at is not None and time.monotonic() - at < FRESH_SECONDS


async def _ask(session: Session, media: Media, season: int | None = None,
               episode: int | None = None, background: bool = False) -> int:
    if not media.imdb_id:
        return 0
    key = f"{media.imdb_id}:{season}:{episode}"
    if _fresh(key):
        return 0
    # Claimed before asking, so two pages opened at once ask once; given back
    # if the question is not answered and stored.
    _asked[key] = time.monotonic()
    if len(_asked) > 20_000:
        _asked.clear()
        _asked[key] = time.monotonic()
    stored = False
    try:
        try:
            async with (_background if background else _slots):
                items = await streams(media.media_type, media.imdb_id, season, episode)
        except (AddonError, httpx.HTTPError) as exc:
            _asked[key] = time.monotonic() - FRESH_SECONDS + RETRY_SECONDS
            stored = True
            log.warning("no addon could answer for %s: %s", key, exc)
            return 0

        merged = _merged(items)
        await _mark_torbox(merged)
        # No await from here to the commit, so two stores cannot take the same next id.
        added = 0
        for found in merged:
            _, created = store(session, media, found, season, episode)
            added += created
        session.commit()
        stored = True
        session.expire(media, ["torrents"])
        return added
    finally:
        if not stored:
            _asked.pop(key, None)


def _aired(air_date: str | None) -> bool:
    """Undated counts as aired: TMDB leaves the date off some old seasons."""
    if not air_date:
        return True
    try:
        return date.fromisoformat(air_date) <= date.today()
    except ValueError:
        return True


async def refresh_title(session: Session, media: Media, background: bool = False) -> int:
    if not settings.addons_configured or not media.imdb_id:
        return 0
    if media.media_type != "tv":
        return await _ask(session, media, background=background)

    seasons = list(session.scalars(
        select(Season).where(Season.media_id == media.id, Season.number > 0)
        .order_by(Season.number)
    ))
    if not seasons and settings.tmdb_configured:
        from .shows import sync_seasons

        try:
            await sync_seasons(session, media)
        except Exception as exc:  # noqa: BLE001 - without seasons, nothing to ask
            session.rollback()
            log.warning("could not fetch the seasons of %s: %s", media.title, exc)
            return 0
        seasons = list(session.scalars(
            select(Season).where(Season.media_id == media.id, Season.number > 0)
            .order_by(Season.number)
        ))
    numbers = [s.number for s in seasons if s.episode_count and _aired(s.air_date)]
    newest = list(reversed(numbers[-MOST_SEASONS:]))
    added = await asyncio.gather(*(_ask(session, media, n, 1, background) for n in newest))
    return sum(added)


async def refresh_season(session: Session, media: Media, number: int) -> int:
    if not settings.addons_configured or not media.imdb_id or media.media_type != "tv":
        return 0
    from .offered import offered
    from .shows import covers

    added = await _ask(session, media, number, 1)
    releases = offered(media.torrents)
    missing = [
        e.number for e in session.scalars(
            select(Episode).where(Episode.media_id == media.id, Episode.season_number == number)
            .order_by(Episode.number)
        )
        if e.number > 1 and _aired(e.air_date)
        and not any(covers(t, number, e.number) for t in releases)
    ]
    more = await asyncio.gather(*(_ask(session, media, number, n) for n in missing[:MOST_EPISODES]))
    return added + sum(more)


async def _titles_for(session: Session, results: list[dict]) -> list[Media]:
    from .tmdb import TMDBClient, media_for

    client = TMDBClient()
    found = []
    for item in results:
        kind = item.get("media_type")
        if kind not in ("movie", "tv") or not item.get("id"):
            continue
        try:
            media = await media_for(session, client, int(item["id"]), kind)
        except Exception as exc:  # noqa: BLE001 - one title must not lose the rest
            log.warning("could not look up %s %s: %s", kind, item.get("id"), exc)
            continue
        if media is not None:
            found.append(media)
    return found


async def search_live(session: Session, query: str, limit: int = 4) -> int:
    if not (settings.addons_configured and settings.tmdb_configured):
        return 0
    from .tmdb import TMDBClient

    results = await TMDBClient().search_any(query)
    added = 0
    for media in await _titles_for(session, results[:limit]):
        added += await _refresh_quietly(session, media)
    record_event(session, "addons", f"search '{query}': {added} new")
    session.commit()
    return added


async def _refresh_quietly(session: Session, media: Media, background: bool = False) -> int:
    try:
        return await refresh_title(session, media, background)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.warning("could not ask about %s: %s", media.title, exc)
        return 0


DISCOVERED = "addons_discovered_at"
DISCOVER_EVERY = 12 * 3600


async def discover(session: Session, force: bool = False) -> int:
    if not (settings.addons_configured and settings.tmdb_configured):
        return 0
    from ..db import kv_get, kv_set
    from .tmdb import TMDBClient

    last = kv_get(session, DISCOVERED)
    if not force and last and time.time() - float(last) < DISCOVER_EVERY:
        return 0
    client = TMDBClient()
    results = []
    for kind in ("movie", "tv"):
        for item in await client.trending(kind):
            results.append({**item, "media_type": kind})
    added = 0
    for media in await _titles_for(session, results):
        added += await _refresh_quietly(session, media, background=True)
    kv_set(session, DISCOVERED, str(time.time()))
    record_event(session, "addons", f"trending titles: {added} new releases",
                 f"titles={len(results)}")
    session.commit()
    return added


def magnet(info_hash: str, name: str | None, announce: str | None) -> str:
    trackers = []
    try:
        trackers = [str(t) for t in json.loads(announce or "[]")]
    except ValueError:
        pass
    for tracker in TRACKERS:
        if tracker not in trackers:
            trackers.append(tracker)
    parts = [f"xt=urn:btih:{info_hash}"]
    if name:
        parts.append("dn=" + quote(name))
    parts += ["tr=" + quote(t, safe="") for t in trackers]
    return "magnet:?" + "&".join(parts)


async def metadata_bytes(info_hash: str, name: str | None, announce: str | None) -> bytes:
    """The .torrent of a magnet: added stopped at metadata, exported, then removed."""
    from .qbit import QbitClient, QbitError, QbitNotFound

    info_hash = info_hash.lower()
    async with QbitClient() as client:
        already = await client.get(info_hash)
        if already is None:
            await client.add_magnet(magnet(info_hash, name, announce),
                                    save_path=settings.qbit_download_dir)
        deadline = time.monotonic() + METADATA_SECONDS
        content = b""
        while time.monotonic() < deadline:
            try:
                content = await client.export(info_hash)
            except (QbitNotFound, QbitError):
                content = b""
            if content[:1] == b"d":
                break
            await asyncio.sleep(1.0)
        if already is None:
            try:
                await client.delete(info_hash, delete_files=True)
                for _ in range(20):
                    if await client.get(info_hash) is None:
                        break
                    await asyncio.sleep(0.25)
            except QbitError as exc:
                log.warning("could not remove the magnet %s: %s", info_hash, exc)
    if content[:1] != b"d":
        raise AddonError(
            f"nobody sharing this release sent its file list in {METADATA_SECONDS} seconds"
        )
    return content
