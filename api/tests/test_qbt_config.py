from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.qbit import QbitClient  # noqa: E402
from vibestream.tools import qbt_config  # noqa: E402


def test_the_webui_protections_are_on():
    conf = qbt_config.build("a password")
    assert "WebUI\\CSRFProtection=true" in conf
    assert "WebUI\\ClickjackingProtection=true" in conf


def test_the_client_passes_csrf_protection():
    """qBittorrent refuses a request whose Referer or Origin names another
    host than the one it was sent to."""
    seen = []

    def handler(request):
        seen.append((request.headers.get("host"), request.headers.get("referer")))
        return httpx.Response(200, text="v5.0.0")

    async def run():
        client = QbitClient(base_url="http://qbittorrent:8081", username="u", password="p")
        await client._ensure_client()
        client._client._transport = httpx.MockTransport(handler)
        try:
            await client.version()
        finally:
            await client.close()

    asyncio.run(run())
    [(host, referer)] = seen
    assert httpx.URL(referer).netloc.decode() == host == "qbittorrent:8081"
