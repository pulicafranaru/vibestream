"""Whether a newer release is out, asked of GitHub at most every few hours.

Only GitHub's public releases endpoint is called, with nothing about this
server but the User-Agent every other request sends. Switched off with
update_check, the dashboard simply shows no notice.
"""

from __future__ import annotations

import logging
import re
import time

from .. import BUILD, VERSION
from ..config import settings
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

REPO = "pulicafranaru/vibestream"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL = f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install.sh | sudo bash"
FRESH_SECONDS = 6 * 3600
RETRY_SECONDS = 3600

_cache: dict = {"at": 0.0, "ttl": 0.0, "release": None}


def parse(version: str) -> tuple[int, int, int] | None:
    found = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (version or "").strip())
    return tuple(int(n) for n in found.groups()) if found else None


async def latest() -> dict | None:
    """The newest release, as {version, url, published}, or None when unknown."""
    if time.monotonic() - _cache["at"] < _cache["ttl"]:
        return _cache["release"]
    release, ttl = None, RETRY_SECONDS
    try:
        async with outbound_client(timeout=10) as client:
            resp = await client.get(LATEST, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 200:
            body = resp.json()
            if parse(body.get("tag_name", "")):
                release = {"version": body["tag_name"].lstrip("v"), "url": body.get("html_url"),
                           "published": body.get("published_at")}
                ttl = FRESH_SECONDS
        elif resp.status_code == 404:
            ttl = FRESH_SECONDS
    except Exception as exc:  # noqa: BLE001
        log.info("update check failed: %s", exc)
    _cache.update(at=time.monotonic(), ttl=ttl, release=release)
    return release


async def status() -> dict:
    out = {"version": VERSION, "build": BUILD, "checked": settings.update_check,
           "latest": None, "available": False, "command": INSTALL}
    if not settings.update_check:
        return out
    release = await latest()
    out["latest"] = release
    if release:
        newer, running = parse(release["version"]), parse(VERSION)
        out["available"] = bool(newer and running and newer > running)
    return out
