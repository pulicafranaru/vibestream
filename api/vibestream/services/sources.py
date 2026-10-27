"""The torrent's own copy of a title, removed once seeded and everything playback needs is kept."""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import Download, DownloadState, Episode, Torrent, utcnow
from . import hls, live, mediainfo, subtitles, trickplay

log = logging.getLogger(__name__)

HELD_STATES = (
    DownloadState.completed.value,
    DownloadState.seeding.value,
    DownloadState.linked.value,
)


def _rendition_complete(path: str, audio_index: int | None) -> bool:
    try:
        with open(hls.playlist_path_for(path, audio_index), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 256))
            return b"#EXT-X-ENDLIST" in fh.read()
    except OSError:
        return False


async def extras_ready(path: str) -> bool:
    """Whether everything beyond the main rendition has been kept. Never runs ffprobe."""
    info = mediainfo.cached_info(path)
    if info is None:
        return False
    if live.everywhere():
        return subtitles.all_extracted(info)
    return (
        all(_rendition_complete(path, index) for index in hls.extra_audio(info))
        and subtitles.all_extracted(info)
    )


async def build_extras(info: mediainfo.MediaInfo, report=None) -> str | None:
    import asyncio

    # Played live, audio tracks come from the source; no rendition is built.
    extras = [] if live.everywhere() else hls.extra_audio(info)
    for done, index in enumerate(extras):
        if report:
            report(done / max(1, len(extras) + 1) * 100)
        session = await hls.ensure_session(info, index)
        while session.running:
            await asyncio.sleep(2)
        if not session.complete:
            return session.error or f"the rendition of audio track {index} did not finish"
    if report:
        report(len(extras) / max(1, len(extras) + 1) * 100)
    return await subtitles.extract_all(info)


def _files(session: Session, download: Download) -> list[tuple[Episode | None, str]]:
    from .preparation import targets_for

    rows = []
    for episode_id, path in targets_for(session, download):
        episode = session.get(Episode, episode_id) if episode_id else None
        if episode is not None and episode.source_removed_at is not None:
            continue
        if path:
            rows.append((episode, path))
    return rows


def obligation(download: Download) -> dict:
    from .reaper import seeding_obligation

    return seeding_obligation(download)


async def removable(session: Session, download: Download) -> bool:
    if download.source_removed_at is not None or download.prepared_at is None:
        return False
    if live.everywhere():
        # Played live, the source is the title, and renditions can be rebuilt from it.
        return False
    if download.state not in HELD_STATES:
        return False
    files = _files(session, download)
    if not files:
        return False
    for episode, path in files:
        if episode is not None and episode.prepared_at is None:
            return False
        if not (_rendition_complete(path, None)
                and os.path.exists(trickplay.manifest_path_for(path))
                and await extras_ready(path)):
            return False
    return True


def source_bytes(session: Session, download: Download) -> int:
    files = _files(session, download)
    total = 0
    for _episode, path in files:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


async def remove_source(session: Session, download: Download, force: bool = False) -> int:
    """Delete the torrent and its files, keeping the title playable. Returns the bytes freed."""
    from .downloads import DownloadError
    from .qbit import QbitClient, QbitError

    if not await removable(session, download):
        raise DownloadError("this title still needs its source to play everything it has")
    seeding = obligation(download)
    if not seeding["met"] and not force:
        raise DownloadError(f"still seeding: {seeding['detail']}")

    files = _files(session, download)
    freed = source_bytes(session, download)

    # Recorded first: canonical_path looks at the disk, which is about to be emptied.
    from . import streaming

    if all(episode is None for episode, _ in files):
        download.play_path = streaming.canonical_path(download)
    # Saved before the torrent goes, or a sync would mark the whole title removed.
    now = utcnow()
    for episode, _path in files:
        if episode is not None:
            episode.source_removed_at = now
    download.source_removed_at = now
    session.commit()

    if download.info_hash:
        try:
            async with QbitClient() as client:
                await client.delete(download.info_hash, delete_files=True)
        except QbitError as exc:
            log.warning("could not remove %s from qBittorrent: %s", download.info_hash, exc)
    if download.link:
        from . import linkfetch

        linkfetch.remove_files(download.id)

    # The library's hardlinks: the space comes back only once both are gone.
    for _episode, path in files:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            log.warning("could not remove %s: %s", path, exc)

    download.up_speed = 0
    download.dl_speed = 0
    session.commit()
    record_event(
        session, "downloads",
        f"removed the source of {download.torrent.name if download.torrent else download.id}",
        f"{freed / 1024 ** 3:.1f} GiB freed"
        + ("" if obligation(download)["met"] else ", before seeding was done"),
        level="info" if not force else "warn",
    )
    session.commit()
    return freed


async def remove_finished(session: Session) -> dict:
    removed, freed = 0, 0
    for download in session.scalars(
        select(Download).where(
            Download.source_removed_at.is_(None),
            Download.prepared_at.is_not(None),
            Download.state.in_(HELD_STATES),
        )
    ):
        if not obligation(download)["met"] or not await removable(session, download):
            continue
        try:
            freed += await remove_source(session, download)
            removed += 1
        except Exception as exc:  # noqa: BLE001 - one title must not stop the rest
            log.warning("could not remove the source of download %s: %s", download.id, exc)
    return {"removed": removed, "freed_bytes": freed}


async def ensure_extras(session: Session) -> int:
    from . import preparation

    started = 0
    for download in session.scalars(
        select(Download).where(
            Download.source_removed_at.is_(None),
            Download.prepared_at.is_not(None),
            Download.state.in_(HELD_STATES),
        )
    ):
        if preparation.busy(download.id):
            continue
        missing = False
        for _episode, path in _files(session, download):
            if os.path.exists(path) and not await extras_ready(path):
                missing = True
                break
        if missing:
            preparation.start_extras(download.id)
            started += 1
            if started >= 3:
                break
    return started


def free_bytes() -> int | None:
    from .library import free_bytes as statvfs_free

    try:
        return statvfs_free()
    except OSError:
        return None


def floor_bytes() -> int:
    return settings.reaper_min_free_gb * 1024 ** 3


async def summary(session: Session) -> dict:
    seeded = {"count": 0, "bytes": 0}
    seeding = {"count": 0, "bytes": 0}
    for download in session.scalars(
        select(Download).where(
            Download.source_removed_at.is_(None),
            Download.prepared_at.is_not(None),
            Download.state.in_(HELD_STATES),
        )
    ):
        if not await removable(session, download):
            continue
        bucket = seeded if obligation(download)["met"] else seeding
        bucket["count"] += 1
        bucket["bytes"] += source_bytes(session, download)
    free = free_bytes()
    return {
        "free_bytes": free,
        "floor_bytes": floor_bytes(),
        "low": free is not None and free < floor_bytes(),
        "removable_seeded": seeded,
        "removable_seeding": seeding,
    }


def cost_of(torrent: Torrent, episode_bytes: int | None = None) -> int:
    size = episode_bytes if episode_bytes is not None else (torrent.size_bytes or 0)
    return size if live.everywhere() else size * 2


async def space_check(session: Session, needed: int) -> dict | None:
    free = free_bytes()
    if free is None or free - needed >= floor_bytes():
        return None
    report = await summary(session)
    return {
        "code": "low_space",
        "message": (
            f"Only {free / 1024 ** 3:.0f} GB free, and this needs about "
            f"{needed / 1024 ** 3:.0f} GB."
        ),
        "needed_bytes": needed,
        "fits": needed < free,
        **report,
    }


_usage: tuple[float, dict] | None = None
USAGE_TTL = 60


def _allocated(root: str, seen: set[tuple[int, int]]) -> int:
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                info = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += info.st_blocks * 512
    return total


def usage() -> dict:
    global _usage
    now = time.monotonic()
    if _usage and now - _usage[0] < USAGE_TTL:
        return _usage[1]
    from . import clips

    seen: set[tuple[int, int]] = set()
    result = {
        "torrent_bytes": _allocated(settings.qbit_download_dir, seen),
        "playback_bytes": sum(
            _allocated(root, seen)
            for root in (hls.CACHE_ROOT, trickplay.CACHE_ROOT, subtitles.CACHE_DIR, clips.CLIPS_DIR)
        ),
    }
    _usage = (now, result)
    return result
