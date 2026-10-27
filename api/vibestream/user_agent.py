"""Generic browser User-Agent for every third-party client. Their URLs can
carry keys, so they are logged by host only."""

from __future__ import annotations

import logging
import os

import httpx

_HOUSE = {"qbittorrent", "localhost", "127.0.0.1"}


class _HostOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 2 and isinstance(args[1], httpx.URL):
            url = args[1]
            if url.host not in _HOUSE:
                record.args = (args[0], f"{url.scheme}://{url.host}/...", *args[2:])
        return True


logging.getLogger("httpx").addFilter(_HostOnly())

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

USER_AGENT = os.environ.get("OUTBOUND_USER_AGENT") or DEFAULT_USER_AGENT


def outbound_client(**kwargs) -> httpx.AsyncClient:
    headers = dict(kwargs.pop("headers", None) or {})
    headers["User-Agent"] = USER_AGENT
    return httpx.AsyncClient(headers=headers, **kwargs)
