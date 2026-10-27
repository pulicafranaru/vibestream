"""Serving a file over HTTP Range, including one that is still downloading.

qBittorrent's "append .!qB to incomplete files" must be off, or the path
changes when the download finishes and open streams break.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from ..config import settings
from ..models import Download
from ..torrentmeta import TorrentFile, TorrentMeta
from .downloads import fetch_torrent_bytes, get_meta, remember_meta
from .qbit import PIECE_DOWNLOADED, QbitClient

log = logging.getLogger(__name__)

CHUNK_SIZE = 512 * 1024
# How long a single read waits for a piece before giving up on the range.
POLL_INTERVAL = 0.5

MIME_BY_EXT = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/x-matroska",
    ".webm": "video/webm", ".avi": "video/x-msvideo", ".mov": "video/quicktime",
    ".ts": "video/mp2t", ".m2ts": "video/mp2t",
}

DIRECT_PLAY_VIDEO = {"H.264", "x264", "AV1"}
DIRECT_PLAY_CONTAINER = {".mp4", ".m4v", ".webm"}


@dataclass
class StreamContext:
    """Plain values for the body generator: it runs after the session has closed,
    when touching an ORM row raises DetachedInstanceError.
    """

    download_id: int
    path: str
    file_size: int
    complete: bool
    info_hash: str | None = None
    primary_file: str | None = None
    torrent_id: int | None = None

    @classmethod
    def of(cls, download: Download, path: str, file_size: int) -> "StreamContext":
        return cls(
            download_id=download.id,
            path=path,
            file_size=file_size,
            complete=(download.progress or 0.0) >= 1.0,
            info_hash=download.info_hash,
            primary_file=download.primary_file,
            torrent_id=download.torrent_id,
        )


@dataclass
class Readiness:
    ready: bool
    reason: str
    buffered_bytes: int
    required_bytes: int
    contiguous_pieces: int
    total_pieces: int
    progress: float
    dl_speed: int
    file_size: int
    direct_play: bool
    eta_seconds: int | None = None


def mime_for(path: str) -> str:
    return MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def can_direct_play(download: Download) -> bool:
    """Conservative: matroska is excluded, since HEVC in MKV is common and will not play."""
    path = download.primary_file or ""
    if os.path.splitext(path)[1].lower() not in DIRECT_PLAY_CONTAINER:
        return False
    torrent = download.torrent
    if torrent and torrent.video_codec and torrent.video_codec not in DIRECT_PLAY_VIDEO:
        return False
    return True


def canonical_path(download: Download, episode=None) -> str | None:
    """The one path of a playable file: the library copy when it exists. Renditions are keyed by it."""
    if episode is not None and episode.file_path:
        if os.path.exists(episode.file_path):
            return episode.file_path
        # Its source removed: the path still names everything built from it.
        if episode.source_removed_at is not None:
            return episode.file_path

    if episode is None and download.source_removed_at is not None and download.play_path:
        return download.play_path

    published = _library_file(download)
    if published:
        return published

    return download_path(download)


def _library_file(download: Download) -> str | None:
    """Gives up on several files: a season pack needs an episode to choose."""
    root = download.library_path
    if not root or not os.path.isdir(root):
        return None
    found = []
    for name in sorted(os.listdir(root)):
        if os.path.splitext(name)[1].lower() in MIME_BY_EXT:
            found.append(os.path.join(root, name))
    return found[0] if len(found) == 1 else None


def download_path(download: Download) -> str | None:
    content = download.content_path or download.save_path
    if not content:
        return None

    if os.path.isfile(content):
        return content

    if download.primary_file:
        candidate = os.path.join(content, download.primary_file)
        if os.path.exists(candidate):
            return candidate
        # qBittorrent may still be appending .!qB despite configuration.
        if os.path.exists(candidate + ".!qB"):
            return candidate + ".!qB"

    best, best_size = None, 0
    for dirpath, _dirs, files in os.walk(content):
        for name in files:
            if os.path.splitext(name)[1].lower() not in MIME_BY_EXT:
                continue
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > best_size:
                best, best_size = full, size
    return best


async def ensure_meta(
    info_hash: str | None, torrent_id: int | None
) -> TorrentMeta | None:
    """Torrent metadata for piece math, cached. Takes plain ids: safe after the session closes."""
    if not info_hash:
        return None
    cached = get_meta(info_hash)
    if cached:
        return cached
    if not torrent_id:
        return None
    try:
        meta = _parse(await fetch_torrent_bytes(torrent_id))
        remember_meta(meta)
        return meta
    except Exception as exc:
        log.warning("could not load torrent metadata for %s: %s", info_hash, exc)
        return None


def _parse(content: bytes) -> TorrentMeta:
    from ..torrentmeta import parse_torrent

    return parse_torrent(content)


def _stream_file(meta: TorrentMeta, primary_file: str | None) -> TorrentFile | None:
    if primary_file:
        for f in meta.files:
            if f.path == primary_file:
                return f
    return meta.largest_video_file()


async def readiness(download: Download) -> Readiness:
    direct = can_direct_play(download)
    file_size = download.primary_file_size or 0

    if download.progress >= 1.0:
        return Readiness(
            ready=True, reason="download complete", buffered_bytes=file_size,
            required_bytes=0, contiguous_pieces=0, total_pieces=0,
            progress=1.0, dl_speed=0, file_size=file_size, direct_play=direct,
        )

    meta = await ensure_meta(download.info_hash, download.torrent_id)
    if meta is None or not download.info_hash:
        return Readiness(
            ready=False, reason="torrent metadata unavailable", buffered_bytes=0,
            required_bytes=0, contiguous_pieces=0, total_pieces=0,
            progress=download.progress, dl_speed=download.dl_speed,
            file_size=file_size, direct_play=direct,
        )

    target = _stream_file(meta, download.primary_file)
    if target is None:
        return Readiness(
            ready=False, reason="no video file in this torrent", buffered_bytes=0,
            required_bytes=0, contiguous_pieces=0, total_pieces=0,
            progress=download.progress, dl_speed=download.dl_speed,
            file_size=file_size, direct_play=direct,
        )

    file_size = target.length
    try:
        async with QbitClient() as client:
            pieces = await client.piece_states(download.info_hash)
    except Exception as exc:
        return Readiness(
            ready=False, reason=f"qBittorrent unreachable: {exc}", buffered_bytes=0,
            required_bytes=0, contiguous_pieces=0, total_pieces=0,
            progress=download.progress, dl_speed=download.dl_speed,
            file_size=file_size, direct_play=direct,
        )

    first_piece, _ = meta.piece_range_for(target, 0, 0)
    contiguous = 0
    for idx in range(first_piece, len(pieces)):
        if pieces[idx] != PIECE_DOWNLOADED:
            break
        contiguous += 1

    buffered = max(0, min(contiguous * meta.piece_length, file_size))

    required = max(
        int(file_size * settings.stream_min_buffer_ratio),
        settings.stream_min_buffer_bytes,
    )
    # With 16 MiB pieces a 32 MiB buffer is only two pieces, which is too thin
    # to absorb a stall, so also insist on a handful of whole pieces.
    required = max(required, meta.piece_length * 4)
    required = min(required, file_size)

    if buffered >= required:
        return Readiness(
            ready=True, reason="buffered", buffered_bytes=buffered,
            required_bytes=required, contiguous_pieces=contiguous,
            total_pieces=meta.piece_count, progress=download.progress,
            dl_speed=download.dl_speed, file_size=file_size, direct_play=direct,
        )

    eta = None
    if download.dl_speed > 0:
        eta = int((required - buffered) / download.dl_speed)

    return Readiness(
        ready=False,
        reason=(
            f"buffering {buffered / 1024 ** 2:.0f} of "
            f"{required / 1024 ** 2:.0f} MiB"
        ),
        buffered_bytes=buffered, required_bytes=required,
        contiguous_pieces=contiguous, total_pieces=meta.piece_count,
        progress=download.progress, dl_speed=download.dl_speed,
        file_size=file_size, direct_play=direct, eta_seconds=eta,
    )


async def wait_for_bytes(
    info_hash: str | None,
    meta: TorrentMeta,
    target: TorrentFile,
    offset: int,
    length: int,
) -> bool:
    if not info_hash:
        return False

    deadline = asyncio.get_event_loop().time() + settings.stream_wait_timeout_s
    start_piece, end_piece = meta.piece_range_for(target, offset, offset + length - 1)

    async with QbitClient() as client:
        while True:
            pieces = await client.piece_states(info_hash)
            window = pieces[start_piece : end_piece + 1]
            if window and all(p == PIECE_DOWNLOADED for p in window):
                return True
            if asyncio.get_event_loop().time() > deadline:
                log.warning(
                    "timed out waiting for pieces %s..%s of %s",
                    start_piece, end_piece, info_hash,
                )
                return False
            await asyncio.sleep(POLL_INTERVAL)


async def iter_range(ctx: StreamContext, start: int, end: int):
    """Yield bytes [start, end] inclusive. Takes a StreamContext, never an ORM row."""
    meta = None
    target = None
    if not ctx.complete:
        meta = await ensure_meta(ctx.info_hash, ctx.torrent_id)
        target = _stream_file(meta, ctx.primary_file) if meta else None

    loop = asyncio.get_event_loop()
    have: tuple[int, int] | None = None
    stalled_since: float | None = None
    position = start
    # Unbuffered: read-ahead would keep the zeros of a piece that has since landed.
    with open(ctx.path, "rb", buffering=0) as fh:
        while position <= end:
            chunk_size = min(CHUNK_SIZE, end - position + 1)

            if not ctx.complete and meta and target:
                # qBittorrent preallocates: a piece not fetched yet reads as zeros.
                first, last = meta.piece_range_for(target, position, position + chunk_size - 1)
                if have is None or not (have[0] <= first and last <= have[1]):
                    if not await wait_for_bytes(
                        ctx.info_hash, meta, target, position, chunk_size
                    ):
                        return
                    have = (first, last)

            fh.seek(position)
            data = fh.read(chunk_size)
            if not data:
                if ctx.complete:
                    return
                stalled_since = stalled_since or loop.time()
                if loop.time() - stalled_since > settings.stream_wait_timeout_s:
                    log.warning("gave up waiting for %s to reach byte %s", ctx.path, position)
                    return
                await asyncio.sleep(POLL_INTERVAL)
                continue
            stalled_since = None

            position += len(data)
            yield data


def parse_range_header(
    header: str | None, file_size: int
) -> tuple[str, tuple[int, int] | None]:
    """Parse a single byte range: ("ignore", None), ("ok", (start, end)) or ("unsatisfiable", None).

    RFC 9110: an unparseable Range header is ignored (200), not rejected (416).
    """
    if not header:
        return "ignore", None

    value = header.strip()
    if not value.lower().startswith("bytes="):
        return "ignore", None

    spec = value[6:].split(",")[0].strip()
    if not spec or "-" not in spec:
        return "ignore", None

    raw_start, _, raw_end = spec.partition("-")
    raw_start, raw_end = raw_start.strip(), raw_end.strip()

    if not raw_start:
        if not raw_end.isdigit():
            return "ignore", None
        suffix = int(raw_end)
        if suffix == 0:
            return "unsatisfiable", None
        length = min(suffix, file_size)
        return "ok", (max(0, file_size - length), file_size - 1)

    if not raw_start.isdigit():
        return "ignore", None
    if raw_end and not raw_end.isdigit():
        return "ignore", None

    start = int(raw_start)
    end = int(raw_end) if raw_end else file_size - 1

    if start >= file_size:
        return "unsatisfiable", None

    end = min(end, file_size - 1)
    if start > end:
        return "unsatisfiable", None
    return "ok", (start, end)


def resolve_path(download: Download) -> str | None:
    """Backwards-compatible name for the canonical path."""
    return canonical_path(download)
