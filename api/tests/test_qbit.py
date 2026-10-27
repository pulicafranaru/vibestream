"""qBittorrent response shapes that differ across versions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.qbit import (  # noqa: E402
    QbitError,
    _parse_add_response,
    _status_from,
    contiguous_prefix_bytes,
)

REAL_5X_BODY = (
    '{"added_torrent_ids":["7b15bc4564341616a4957c12d63190213fd1018d"],'
    '"failure_count":0,"pending_count":0,"success_count":1}'
)


def test_add_response_4x_ok():
    assert _parse_add_response("Ok.") is None


def test_add_response_4x_empty_body():
    assert _parse_add_response("") is None
    assert _parse_add_response("   ") is None


def test_add_response_4x_failure():
    with pytest.raises(QbitError):
        _parse_add_response("Fails.")


def test_add_response_5x_success_returns_hash():
    # Captured verbatim from qBittorrent 5.2.3.
    assert _parse_add_response(REAL_5X_BODY) == (
        "7b15bc4564341616a4957c12d63190213fd1018d"
    )


def test_add_response_5x_failure_raises():
    body = '{"added_torrent_ids":[],"failure_count":1,"pending_count":0,"success_count":0}'
    with pytest.raises(QbitError):
        _parse_add_response(body)


def test_add_response_5x_pending_is_not_a_failure():
    body = '{"added_torrent_ids":[],"failure_count":0,"pending_count":1,"success_count":0}'
    assert _parse_add_response(body) is None


def test_add_response_unknown_text_is_a_failure():
    with pytest.raises(QbitError):
        _parse_add_response("<html>gateway timeout</html>")


def test_status_eta_sentinel_becomes_none():
    # qBittorrent uses 8640000 (100 days) to mean "unknown".
    status = _status_from({"hash": "AB", "eta": 8640000, "state": "downloading"})
    assert status.eta is None
    assert status.hash == "ab"


def test_status_real_eta_survives():
    assert _status_from({"eta": 300, "state": "downloading"}).eta == 300


def test_status_normalisation():
    assert _status_from({"state": "downloading", "progress": 0.3}).normalised_state() == (
        "downloading"
    )
    assert _status_from({"state": "stalledUP", "progress": 1.0}).normalised_state() == (
        "seeding"
    )
    assert _status_from({"state": "pausedDL", "progress": 0.5}).normalised_state() == (
        "paused"
    )
    assert _status_from({"state": "missingFiles"}).normalised_state() == "error"


def test_contiguous_prefix_stops_at_first_gap():
    # 2 = downloaded. A gap means playback cannot run past it.
    pieces = [2, 2, 2, 0, 2, 2]
    assert contiguous_prefix_bytes(pieces, 1000, 0, 6000) == 3000


def test_contiguous_prefix_is_capped_by_file_size():
    assert contiguous_prefix_bytes([2, 2, 2], 1000, 0, 2500) == 2500


def test_contiguous_prefix_from_a_later_start_piece():
    assert contiguous_prefix_bytes([0, 0, 2, 2], 1000, 2, 4000) == 2000


def test_contiguous_prefix_empty_when_first_piece_missing():
    assert contiguous_prefix_bytes([0, 2, 2], 1000, 0, 3000) == 0


@pytest.mark.parametrize("failure", ["connect", "timeout"])
def test_qbittorrent_not_answering_is_a_qbit_error(failure):
    """Transport failures are raised as QbitError, which callers handle."""
    import asyncio

    import httpx

    from vibestream.services.qbit import QbitClient

    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError("refused", request=request)
        raise httpx.ReadTimeout("slow", request=request)

    async def run():
        client = QbitClient(base_url="http://qbit.invalid", username="u", password="p")
        client._client = httpx.AsyncClient(base_url="http://qbit.invalid",
                                           transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(QbitError):
                await client.info(["ab" * 20])
            with pytest.raises(QbitError):
                await client.login()
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("status, body, cookie, works", [
    (200, "Ok.", "SID", True),             # 4.x
    (204, "", "SID", True),                # 5.0 and 5.1, which the installer pins
    (204, "", "QBT_SID_8080", True),       # 5.2 and later
    (204, "", None, False),
])
def test_every_qbittorrent_versions_session_cookie_signs_in(status, body, cookie, works):
    import asyncio

    import httpx

    from vibestream.services.qbit import QbitAuthError, QbitClient

    def handler(request):
        headers = {"set-cookie": f"{cookie}=abc123; HttpOnly; path=/"} if cookie else {}
        return httpx.Response(status, text=body, headers=headers)

    async def run():
        client = QbitClient(base_url="http://qbittorrent:8080", username="u", password="p")
        client._client = httpx.AsyncClient(base_url="http://qbittorrent:8080",
                                           transport=httpx.MockTransport(handler))
        try:
            if works:
                await client.login()
            else:
                with pytest.raises(QbitAuthError):
                    await client.login()
        finally:
            await client.close()

    asyncio.run(run())
