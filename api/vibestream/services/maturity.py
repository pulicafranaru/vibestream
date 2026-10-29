"""Age ratings as an age, and what a kids profile may see; an unrated title has no age."""

from __future__ import annotations

import re
from contextvars import ContextVar

from sqlalchemy import true

# What the dashboard offers as a kids profile's ceiling.
LEVELS = [(0, "All ages"), (7, "7+"), (10, "10+"), (13, "13+"), (16, "16+"), (18, "18+")]
CEILINGS = tuple(age for age, _ in LEVELS)
DEFAULT_KIDS_CEILING = 7

_NAMED = {
    "G": 0, "PG": 10, "PG-13": 13, "R": 17, "NC-17": 18, "NR": None, "UNRATED": None,
    "TV-Y": 0, "TV-G": 0, "TV-Y7": 7, "TV-Y7-FV": 7, "TV-PG": 10, "TV-14": 14, "TV-MA": 18,
    "U": 0, "UC": 0, "12A": 12, "R18": 18,
    "AG": 0, "AP": 12, "A.P.": 12,
    # Everyone, everywhere: "all", "tous publics", "alle".
    "ALL": 0, "AL": 0, "TP": 0, "T": 0, "A": 0, "0+": 0,
}


def age(certification: str | None) -> int | None:
    """The youngest age a certification suits, or None when unknown."""
    if not certification:
        return None
    text = certification.strip().upper()
    if text in _NAMED:
        return _NAMED[text]
    found = re.search(r"\d{1,2}", text)
    return min(int(found.group()), 18) if found else None


def label(ceiling: int | None) -> str:
    return dict(LEVELS).get(ceiling, f"{ceiling}+") if ceiling is not None else "No limit"


# The asking profile's ceiling, for this request (set by Screen, main.py).
_LIMIT: ContextVar[int | None] = ContextVar("maturity_limit", default=None)


def current() -> int | None:
    return _LIMIT.get()


def ceiling(profile) -> int | None:
    """The oldest age this profile may see, or None for no limit."""
    from ..config import settings

    if not settings.parental_controls or profile is None or not profile.is_kids:
        return None
    return profile.max_maturity if profile.max_maturity is not None else DEFAULT_KIDS_CEILING


def allowed(media, limit: int | None) -> bool:
    if limit is None:
        return True
    return media is not None and media.maturity is not None and media.maturity <= limit


def clause(limit: int | None):
    """A WHERE for Media under this ceiling: true for no limit."""
    from ..models import Media

    if limit is None:
        return true()
    return Media.maturity.is_not(None) & (Media.maturity <= limit)


def media_of(download):
    torrent = getattr(download, "torrent", None)
    return torrent.media if torrent is not None else None


def downloads(rows):
    """Only the downloads of titles this request may see."""
    limit = current()
    return [d for d in rows if allowed(media_of(d), limit)] if limit is not None else list(rows)


def require(media) -> None:
    """404 for a title above this request's ceiling: to a kids profile it is not there."""
    from fastapi import HTTPException

    if not allowed(media, current()):
        raise HTTPException(404, "unknown media")


def limit_for(profile_header: str | None) -> int | None:
    from ..config import settings
    from ..db import session_scope
    from ..models import Profile

    if not settings.parental_controls or not profile_header:
        return None
    try:
        profile_id = int(profile_header)
    except ValueError:
        return None
    with session_scope() as session:
        return ceiling(session.get(Profile, profile_id))


class Screen:
    """ASGI middleware: the ceiling of the profile in X-VibeStream-Profile, for this request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        header = dict(scope.get("headers") or []).get(b"x-vibestream-profile")
        token = _LIMIT.set(limit_for(header.decode() if header else None))
        try:
            await self.app(scope, receive, send)
        finally:
            _LIMIT.reset(token)
