"""Which releases this server can fetch, given the sources it is set up for."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import object_session

from ..config import settings
from ..models import Download, Torrent


def origins() -> set[str] | None:
    found = set()
    if settings.filelist_configured:
        found.add("filelist")
    if settings.addons_configured:
        found.add("addon")
    return found or None


def can_fetch(torrent: Torrent) -> bool:
    allowed = origins()
    return allowed is None or (torrent.origin or "filelist") in allowed


def offered(
    torrents: Iterable[Torrent], downloads: dict[int, Download] | None = None
) -> list[Torrent]:
    allowed = origins()
    torrents = list(torrents)
    if allowed is None:
        return torrents
    others = [t for t in torrents if (t.origin or "filelist") not in allowed]
    if downloads is not None:
        held = {t.id for t in others if t.id in downloads}
    else:
        held = _downloaded(others)
    return [t for t in torrents if (t.origin or "filelist") in allowed or t.id in held]


def _downloaded(torrents: list[Torrent]) -> set[int]:
    if not torrents:
        return set()
    session = object_session(torrents[0])
    if session is None:
        return {t.id for t in torrents if t.download is not None}
    ids = [t.id for t in torrents]
    found: set[int] = set()
    for start in range(0, len(ids), 900):
        found.update(session.scalars(
            select(Download.torrent_id).where(Download.torrent_id.in_(ids[start:start + 900]))
        ))
    return found
