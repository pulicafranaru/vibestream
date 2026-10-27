"""qBittorrent WebUI API v2 client.

/torrents/add returns no id on 4.x, so callers compute the infohash from the
.torrent bytes. The session cookie expires; _request re-authenticates once on a 403.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger(__name__)

PIECE_MISSING = 0
PIECE_REQUESTED = 1
PIECE_DOWNLOADED = 2

COMPLETE_STATES = {
    "uploading", "stalledUP", "queuedUP", "pausedUP", "stoppedUP",
    "forcedUP", "checkingUP",
}
DOWNLOADING_STATES = {
    "downloading", "stalledDL", "metaDL", "queuedDL", "forcedDL",
    "checkingDL", "allocating", "checkingResumeData",
}
PAUSED_STATES = {"pausedDL", "stoppedDL"}
ERROR_STATES = {"error", "missingFiles", "unknown"}


class QbitError(RuntimeError):
    pass


class QbitNotFound(QbitError):
    """A 404: unknown endpoint or torrent. A torrent added a moment ago looks the same."""


class QbitAuthError(QbitError):
    pass


@dataclass
class TorrentStatus:
    hash: str
    name: str
    state: str
    progress: float           # 0..1
    dlspeed: int
    upspeed: int
    eta: int | None
    downloaded: int
    uploaded: int
    ratio: float
    size: int
    save_path: str
    content_path: str
    seeding_time: int         # seconds
    completion_on: int | None # unix ts
    # Connected counts are current peers; swarm counts are the tracker's last report.
    connected_seeds: int = 0
    connected_leechs: int = 0
    swarm_seeds: int = 0
    swarm_leechs: int = 0

    @property
    def is_complete(self) -> bool:
        return self.progress >= 1.0 or self.state in COMPLETE_STATES

    @property
    def is_downloading(self) -> bool:
        return self.state in DOWNLOADING_STATES

    @property
    def is_error(self) -> bool:
        return self.state in ERROR_STATES

    def normalised_state(self) -> str:
        if self.is_error:
            return "error"
        if self.state in PAUSED_STATES:
            return "paused"
        if self.is_complete:
            return "seeding" if self.state != "checkingUP" else "completed"
        return "downloading"


class QbitClient:
    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or settings.qbit_url).rstrip("/")
        self.username = username if username is not None else settings.qbit_username
        self.password = password if password is not None else settings.qbit_password
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "QbitClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={"Referer": self.base_url},
            )
        return self._client

    async def login(self) -> None:
        """Authenticate. 4.x answers 200 "Ok.", 5.x answers 204: the SID cookie is what is checked."""
        client = await self._ensure_client()
        try:
            resp = await client.post(
                "/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
            )
        except httpx.HTTPError as exc:
            raise QbitError(f"qBittorrent is not answering: {exc!r}") from exc

        if resp.status_code == 401:
            raise QbitAuthError("qBittorrent rejected the username or password")
        if resp.status_code == 403:
            raise QbitAuthError(
                "qBittorrent refused the login, the IP may be temporarily banned "
                "after repeated failures"
            )
        if resp.status_code not in (200, 204):
            raise QbitAuthError(
                f"qBittorrent login failed: HTTP {resp.status_code} {resp.text[:120]}"
            )
        if resp.status_code == 200 and resp.text.strip() not in ("", "Ok."):
            raise QbitAuthError(f"qBittorrent login failed: {resp.text[:120]}")

        # "SID" up to 5.1, "QBT_SID_<port>" from 5.2.
        if not any(name == "SID" or name.startswith("QBT_SID") for name in client.cookies.keys()):
            raise QbitAuthError(
                "qBittorrent returned success but set no session cookie"
            )

    async def _request(
        self, method: str, path: str, *, retry_auth: bool = True, **kwargs
    ) -> httpx.Response:
        client = await self._ensure_client()
        # Connection errors become QbitError, which every caller handles.
        try:
            resp = await client.request(method, path, **kwargs)
            if resp.status_code == 403 and retry_auth:
                async with self._lock:
                    await self.login()
                resp = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise QbitError(f"qBittorrent {path} is not answering: {exc!r}") from exc
        if resp.status_code == 404:
            raise QbitNotFound(f"qBittorrent endpoint not found: {path}")
        if resp.status_code >= 400:
            raise QbitError(
                f"qBittorrent {path} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp

    async def version(self) -> str:
        resp = await self._request("GET", "/api/v2/app/version")
        return resp.text.strip()

    async def check(self) -> tuple[bool, str]:
        try:
            await self.login()
            return True, await self.version()
        except Exception as exc:
            return False, str(exc)

    async def default_save_path(self) -> str:
        resp = await self._request("GET", "/api/v2/app/defaultSavePath")
        return resp.text.strip()

    async def add_torrent_file(
        self,
        content: bytes,
        *,
        filename: str = "vibestream.torrent",
        save_path: str | None = None,
        category: str = "vibestream",
        sequential: bool = True,
        first_last_prio: bool = True,
        paused: bool = False,
    ) -> str | None:
        """Add a torrent. Returns the infohash when the server reports one (5.x).

        sequential + first_last_prio fetch the last piece early: containers keep their index there.
        """
        data = {
            "category": category,
            "sequentialDownload": "true" if sequential else "false",
            "firstLastPiecePrio": "true" if first_last_prio else "false",
            "paused": "true" if paused else "false",
            # Newer builds renamed the pause flag; sending both is harmless.
            "stopped": "true" if paused else "false",
            "autoTMM": "false",
        }
        if save_path:
            data["savepath"] = save_path

        resp = await self._request(
            "POST",
            "/api/v2/torrents/add",
            files={"torrents": (filename, content, "application/x-bittorrent")},
            data=data,
        )
        return _parse_add_response(resp.text)

    async def add_magnet(self, magnet: str, *, save_path: str | None = None,
                         category: str = "vibestream") -> None:
        """Add a magnet that stops once it has its metadata (needs qBittorrent 4.5)."""
        data = {
            "urls": magnet,
            "category": category,
            "stopCondition": "MetadataReceived",
            "autoTMM": "false",
        }
        if save_path:
            data["savepath"] = save_path
        resp = await self._request("POST", "/api/v2/torrents/add", data=data)
        _parse_add_response(resp.text)

    async def export(self, info_hash: str) -> bytes:
        """The .torrent of a torrent. qBittorrent answers 409 until it has the metadata."""
        resp = await self._request(
            "GET", "/api/v2/torrents/export", params={"hash": info_hash.lower()}
        )
        return resp.content

    async def info(self, hashes: list[str] | None = None) -> list[TorrentStatus]:
        params = {}
        if hashes:
            params["hashes"] = "|".join(h.lower() for h in hashes)
        else:
            params["category"] = "vibestream"
        resp = await self._request("GET", "/api/v2/torrents/info", params=params)
        return [_status_from(item) for item in resp.json()]

    async def get(self, info_hash: str) -> TorrentStatus | None:
        found = await self.info([info_hash])
        return found[0] if found else None

    async def properties(self, info_hash: str) -> dict:
        resp = await self._request(
            "GET", "/api/v2/torrents/properties", params={"hash": info_hash.lower()}
        )
        return resp.json()

    async def files(self, info_hash: str) -> list[dict]:
        resp = await self._request(
            "GET", "/api/v2/torrents/files", params={"hash": info_hash.lower()}
        )
        return resp.json()

    async def set_file_priority(self, info_hash: str, indexes: list[int], priority: int) -> None:
        """Set files' priority: 0 is "do not download", 1 is normal."""
        if not indexes:
            return
        await self._request(
            "POST",
            "/api/v2/torrents/filePrio",
            data={
                "hash": info_hash.lower(),
                "id": "|".join(str(i) for i in indexes),
                "priority": str(priority),
            },
        )

    async def piece_states(self, info_hash: str) -> list[int]:
        resp = await self._request(
            "GET", "/api/v2/torrents/pieceStates", params={"hash": info_hash.lower()}
        )
        return resp.json()

    async def peers(self, info_hash: str) -> list[dict]:
        resp = await self._request(
            "GET", "/api/v2/sync/torrentPeers", params={"hash": info_hash.lower(), "rid": 0}
        )
        peers = (resp.json() or {}).get("peers") or {}
        return [{"address": address, **peer} for address, peer in peers.items()]

    async def trackers(self, info_hash: str) -> list[dict]:
        """The torrent's trackers. Their URLs carry the passkey: never pass them on as they are."""
        resp = await self._request(
            "GET", "/api/v2/torrents/trackers", params={"hash": info_hash.lower()}
        )
        return resp.json()

    async def pause(self, info_hash: str) -> None:
        await self._post_hashes("/api/v2/torrents/pause", info_hash)

    async def resume(self, info_hash: str) -> None:
        await self._post_hashes("/api/v2/torrents/resume", info_hash)

    async def set_sequential(self, info_hash: str, enabled: bool = True) -> None:
        current = await self.get(info_hash)
        if current is None:
            return
        props = await self.properties(info_hash)
        if bool(props.get("seq_dl")) != enabled:
            await self._post_hashes("/api/v2/torrents/toggleSequentialDownload", info_hash)

    async def set_first_last_prio(self, info_hash: str, enabled: bool = True) -> None:
        props = await self.properties(info_hash)
        if bool(props.get("f_l_piece_prio")) != enabled:
            await self._post_hashes("/api/v2/torrents/toggleFirstLastPiecePrio", info_hash)

    async def recheck(self, info_hash: str) -> None:
        await self._request(
            "POST", "/api/v2/torrents/recheck", data={"hashes": info_hash.lower()}
        )

    async def delete(self, info_hash: str, delete_files: bool = True) -> None:
        await self._request(
            "POST",
            "/api/v2/torrents/delete",
            data={
                "hashes": info_hash.lower(),
                "deleteFiles": "true" if delete_files else "false",
            },
        )

    async def _post_hashes(self, path: str, info_hash: str) -> None:
        # Some builds moved pause/resume to stop/start. Fall back on 404.
        try:
            await self._request("POST", path, data={"hashes": info_hash.lower()})
        except QbitError as exc:
            if "not found" not in str(exc):
                raise
            alt = path.replace("/pause", "/stop").replace("/resume", "/start")
            if alt == path:
                raise
            await self._request("POST", alt, data={"hashes": info_hash.lower()})


def _parse_add_response(body: str) -> str | None:
    """Parse the /torrents/add reply (4.x "Ok."/"Fails.", 5.x JSON). Infohash or None; raises on failure."""
    text = (body or "").strip()
    if not text or text == "Ok.":
        return None
    if text.lower().startswith("fails"):
        raise QbitError("qBittorrent rejected the torrent")

    try:
        payload = json.loads(text)
    except ValueError:
        raise QbitError(f"qBittorrent rejected the torrent: {text[:200]}") from None

    if not isinstance(payload, dict):
        return None

    if int(payload.get("failure_count") or 0) > 0 or (
        "success_count" in payload and int(payload.get("success_count") or 0) == 0
        and int(payload.get("pending_count") or 0) == 0
    ):
        raise QbitError(f"qBittorrent rejected the torrent: {text[:200]}")

    added = payload.get("added_torrent_ids") or []
    return str(added[0]).lower() if added else None


def _status_from(item: dict) -> TorrentStatus:
    eta = item.get("eta")
    # qBittorrent uses 8640000 (100 days) as its "unknown" sentinel.
    if eta in (None, 8640000) or (isinstance(eta, int) and eta >= 8640000):
        eta = None
    completion = item.get("completion_on")
    if completion in (None, 0) or (isinstance(completion, int) and completion < 0):
        completion = None
    return TorrentStatus(
        hash=(item.get("hash") or "").lower(),
        name=item.get("name") or "",
        state=item.get("state") or "unknown",
        progress=float(item.get("progress") or 0.0),
        dlspeed=int(item.get("dlspeed") or 0),
        upspeed=int(item.get("upspeed") or 0),
        eta=eta,
        downloaded=int(item.get("downloaded") or 0),
        uploaded=int(item.get("uploaded") or 0),
        ratio=float(item.get("ratio") or 0.0),
        size=int(item.get("size") or 0),
        save_path=item.get("save_path") or "",
        content_path=item.get("content_path") or "",
        seeding_time=int(item.get("seeding_time") or 0),
        completion_on=completion,
        connected_seeds=int(item.get("num_seeds") or 0),
        connected_leechs=int(item.get("num_leechs") or 0),
        swarm_seeds=int(item.get("num_complete") or 0),
        swarm_leechs=int(item.get("num_incomplete") or 0),
    )


def contiguous_prefix_bytes(
    pieces: list[int], piece_length: int, start_piece: int, total_bytes: int
) -> int:
    """Bytes contiguously available from start_piece onward: this, not progress, decides playback."""
    if piece_length <= 0 or start_piece >= len(pieces):
        return 0
    count = 0
    for idx in range(start_piece, len(pieces)):
        if pieces[idx] != PIECE_DOWNLOADED:
            break
        count += 1
    return min(count * piece_length, total_bytes)
