"""The User-Agent for every service outside the house, and the only place clients for them are built.

VibeStream/<version> by default, never a person, host, account or contact; "browser" (Sources,
Privacy) sends a plain browser string; OUTBOUND_USER_AGENT replaces either. qBittorrent, on the
LAN, is the only other client. httpx request lines name only the host: addresses can hold keys.
"""

from __future__ import annotations

import logging
import os

import httpx

from . import VERSION
from .config import settings


# On the LAN, logged in full: nothing in them is a secret worth the lost detail.
_HOUSE = {"qbittorrent", "localhost", "127.0.0.1"}


class _HostOnly(logging.Filter):
    """httpx's "HTTP Request: GET <url> ..." line, with a third party's
    address cut down to its host."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 2 and isinstance(args[1], httpx.URL):
            url = args[1]
            if url.host not in _HOUSE:
                record.args = (args[0], f"{url.scheme}://{url.host}/...", *args[2:])
        return True


logging.getLogger("httpx").addFilter(_HostOnly())

BROWSER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
PROJECT_AGENT = f"VibeStream/{VERSION}"


def current() -> str:
    """The string sent now: read on every request, so a change in the
    dashboard applies at once."""
    if custom := os.environ.get("OUTBOUND_USER_AGENT"):
        return custom
    return BROWSER_AGENT if settings.outbound_identity == "browser" else PROJECT_AGENT


def outbound_client(**kwargs) -> httpx.AsyncClient:
    """An HTTP client for a third party, sending this server's agent (current)."""
    headers = dict(kwargs.pop("headers", None) or {})
    headers["User-Agent"] = current()
    return httpx.AsyncClient(headers=headers, **kwargs)
