"""TorBox: a release is fetched on its servers, then over HTTPS (services/linkfetch.py).

Only addon releases are sent: a filelist .torrent carries the passkey, and private trackers
ban accounts whose torrents appear on debrid services.
"""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import quote

import httpx

from ..config import settings
from ..models import Torrent
from ..user_agent import outbound_client
from .library import SKIP_PATTERNS, VIDEO_EXT

log = logging.getLogger(__name__)

API = "https://api.torbox.app/v1/api"
PREFIX = "torbox:"
# Hashes asked about in one question; the API takes a list in a body.
CACHED_BATCH = 100


class TorboxError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.torbox_api_key)


def allowed(torrent: Torrent | None) -> bool:
    """Whether this release may go to TorBox: one found through an addon,
    never one from filelist."""
    return bool(torrent is not None and torrent.origin == "addon" and torrent.info_hash)


def _client() -> httpx.AsyncClient:
    return outbound_client(
        base_url=API, timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"Authorization": f"Bearer {settings.torbox_api_key}"},
    )


def _data(resp: httpx.Response):
    """The answer's data, or TorboxError with TorBox's own words."""
    try:
        body = resp.json()
    except ValueError:
        raise TorboxError(f"TorBox answered HTTP {resp.status_code}") from None
    if resp.status_code >= 400 or not body.get("success", False):
        detail = body.get("detail") or body.get("error") or f"HTTP {resp.status_code}"
        raise TorboxError(str(detail))
    return body.get("data")


async def account() -> tuple[bool, str]:
    """Whether the key works, and the plan it is on, for the dashboard."""
    try:
        async with _client() as client:
            me = _data(await client.get("/user/me"))
    except (TorboxError, httpx.HTTPError) as exc:
        return False, str(exc) or "TorBox could not be reached"
    plan = {0: "Free", 1: "Essential", 2: "Pro", 3: "Standard"}.get(me.get("plan"), "a plan")
    until = (me.get("premium_expires_at") or "")[:10]
    return True, f"{plan}{f', until {until}' if until else ''}"


async def held(hashes: list[str]) -> set[str]:
    """Which of these TorBox already holds, so they arrive at once."""
    wanted = sorted({h.lower() for h in hashes if h})
    found: set[str] = set()
    async with _client() as client:
        for start in range(0, len(wanted), CACHED_BATCH):
            batch = wanted[start:start + CACHED_BATCH]
            data = _data(await client.post("/torrents/checkcached", params={"format": "list"},
                                           json={"hashes": batch}))
            if isinstance(data, dict):
                found.update(h.lower() for h, item in data.items() if item)
                continue
            for item in data or []:
                if isinstance(item, dict) and item.get("hash"):
                    found.add(item["hash"].lower())
    return found


def magnet(torrent: Torrent) -> str:
    link = f"magnet:?xt=urn:btih:{torrent.info_hash}&dn={quote(torrent.name or '')}"
    try:
        trackers = json.loads(torrent.announce) if torrent.announce else []
    except ValueError:
        trackers = []
    for tracker in trackers[:20]:
        link += f"&tr={quote(tracker, safe='')}"
    return link


async def add(torrent: Torrent) -> int:
    """Hands the release to TorBox. Returns its id there."""
    if not allowed(torrent):
        raise TorboxError("only releases found through the addons go to TorBox")
    async with _client() as client:
        try:
            data = _data(await client.post("/torrents/createtorrent", data={
                "magnet": magnet(torrent), "seed": "3", "allow_zip": "false",
                "name": torrent.name or "",
            }))
        except TorboxError as exc:
            # Already in the account, from an earlier try.
            existing = await _find(client, torrent.info_hash)
            if existing is None:
                raise
            log.info("%s is already on TorBox (%s)", torrent.name, exc)
            return existing
    torrent_id = (data or {}).get("torrent_id")
    if not isinstance(torrent_id, int):
        raise TorboxError("TorBox did not say what it called the torrent")
    return torrent_id


async def _find(client: httpx.AsyncClient, info_hash: str) -> int | None:
    rows = _data(await client.get("/torrents/mylist", params={"bypass_cache": "true"})) or []
    for row in rows:
        if str(row.get("hash", "")).lower() == info_hash.lower():
            return row.get("id")
    return None


async def state(torrent_id: int) -> dict:
    """TorBox's view of one torrent: download_finished, progress (0 to 1),
    download_speed, eta, download_state, files."""
    async with _client() as client:
        data = _data(await client.get("/torrents/mylist",
                                      params={"id": torrent_id, "bypass_cache": "true"}))
    if not isinstance(data, dict):
        raise TorboxError("TorBox no longer has it")
    return data


def pick_file(files: list[dict], wanted: str | None) -> dict | None:
    """The video to fetch: the one the release names, else the largest."""
    def plain(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", os.path.basename(name).lower())

    videos = [f for f in files
              if str(f.get("name", "")).lower().endswith(VIDEO_EXT)
              and not SKIP_PATTERNS.search(os.path.basename(str(f.get("name", ""))))]
    if wanted:
        for f in videos:
            if os.path.basename(str(f.get("name", ""))) == wanted or \
                    plain(str(f.get("name", ""))) == plain(wanted):
                return f
    return max(videos, key=lambda f: f.get("size") or 0, default=None)


async def link(torrent_id: int, file_id: int) -> str:
    """A link to one file of it; asked for each time, as they expire."""
    async with _client() as client:
        data = _data(await client.get("/torrents/requestdl", params={
            "token": settings.torbox_api_key, "torrent_id": torrent_id,
            "file_id": file_id, "zip_link": "false",
        }))
    if not isinstance(data, str) or not data.startswith("https://"):
        raise TorboxError("TorBox gave no link")
    return data


async def delete(torrent_id: int) -> None:
    """Off the account once fetched or no longer wanted. Best effort."""
    try:
        async with _client() as client:
            _data(await client.post("/torrents/controltorrent",
                                    json={"torrent_id": torrent_id, "operation": "delete"}))
    except (TorboxError, httpx.HTTPError) as exc:
        log.warning("could not remove torrent %s from TorBox: %s", torrent_id, exc)


def torrent_id(link: str | None) -> int | None:
    if link and link.startswith(PREFIX):
        rest = link[len(PREFIX):]
        return int(rest) if rest.isdigit() else None
    return None
