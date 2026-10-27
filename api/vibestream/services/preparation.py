"""Turning a finished download into something playable. `prepared_at` marks it done."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ..db import session_scope
from ..models import Download, DownloadState, Episode, utcnow
from . import hls, live, mediainfo, stills, trickplay

log = logging.getLogger(__name__)


def _resolve_path(download: Download, episode=None) -> str | None:
    """Imported at call time to avoid an import cycle with services.streaming."""
    from . import streaming

    return streaming.canonical_path(download, episode)


# In memory on purpose: after a restart the work restarts anyway.
_progress: dict[int, dict] = {}
_running: set[int] = set()

# One title at a time: both jobs read very large files off one disk.
_gate = asyncio.Lock()

THUMB_TIMEOUT_SECONDS = 45 * 60

COMPLETE_STATES = (
    DownloadState.completed.value,
    DownloadState.seeding.value,
    DownloadState.linked.value,
)


def _playlist_complete(path: str) -> bool:
    """Whether the rendition was finished. Reads only the tail: #EXT-X-ENDLIST is written last."""
    playlist = hls.playlist_path_for(path)
    try:
        with open(playlist, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 256))
            return b"#EXT-X-ENDLIST" in fh.read()
    except OSError:
        return False


def _thumbs_complete(path: str) -> bool:
    # Ask the module for its manifest path. Never guess the name.
    return os.path.exists(trickplay.manifest_path_for(path))


def artefacts_ready(path: str | None) -> bool:
    if not path:
        return False
    if live.everywhere() and os.path.exists(path) and live.has_index(path):
        return True
    return _playlist_complete(path) and _thumbs_complete(path)


def status(download: Download) -> dict:
    if download.prepared_at is not None:
        return {"ready": True, "percent": 100.0, "stage": "ready", "error": None}

    live = _progress.get(download.id)
    if live:
        return {"ready": False, **live, "error": download.prepare_error}

    return {
        "ready": False,
        "percent": 0.0,
        "stage": "waiting" if download.state in COMPLETE_STATES else "downloading",
        "error": download.prepare_error,
    }


def _set(download_id: int, stage: str, percent: float) -> None:
    _progress[download_id] = {"stage": stage, "percent": round(percent, 1)}


def targets_for(session, download: Download) -> list[tuple[int | None, str]]:
    episodes = list(session.scalars(
        select(Episode).where(Episode.download_id == download.id,
                              Episode.file_path.is_not(None))
        .order_by(Episode.season_number, Episode.number)
    ))
    if episodes:
        return [(e.id, _resolve_path(download, e)) for e in episodes]
    path = _resolve_path(download)
    return [(None, path)] if path else []


async def _prepare_file(download_id: int, episode_id: int | None, path: str,
                        index: int, total: int) -> str | None:
    def report(stage: str, percent: float) -> None:
        span = 100.0 / total
        _set(download_id, stage, index * span + percent * span / 100)

    if artefacts_ready(path):
        return None

    if live.everywhere():
        report("index", 0.0)
        info = await mediainfo.probe(path)
        try:
            await live.build_index(path)
        except live.LiveError as exc:
            return str(exc)
        await trickplay.ensure(info)
        return None

    report("rendition", 0.0)
    info = await mediainfo.probe(path)

    session_hls = await hls.ensure_session(info, None)
    while session_hls.running:
        report("rendition", session_hls.progress()["percent"] * 0.5)
        await asyncio.sleep(2)
    if not session_hls.complete:
        return session_hls.error or "the rendition did not finish"

    # Wait for the manifest, not the process: trickplay.ensure() returns before
    # the subprocess exists.
    report("thumbnails", 50.0)
    job = await trickplay.ensure(info)
    deadline = time.monotonic() + THUMB_TIMEOUT_SECONDS
    while not job.ready and job.error is None:
        if time.monotonic() > deadline:
            return "thumbnail generation timed out"
        report("thumbnails", 50.0 + job.progress()["percent"] * 0.5)
        await asyncio.sleep(2)
    return f"thumbnails failed: {job.error}" if job.error else None


async def _build_extras(info) -> None:
    from . import sources

    error = await sources.build_extras(info)
    if error:
        log.warning("could not keep everything of %s: %s", os.path.basename(info.path), error)


async def prepare(download_id: int) -> None:
    if download_id in _running:
        return
    _running.add(download_id)
    try:
        with session_scope() as session:
            download = session.get(Download, download_id)
            if download is None:
                return
            targets = [(eid, path) for eid, path in targets_for(session, download)
                       if path and os.path.exists(path)]
        if not targets:
            return

        _set(download_id, "queued", 0.0)
        async with _gate:
            failure = None
            for index, (episode_id, path) in enumerate(targets):
                if not _still_held(download_id, episode_id, path):
                    continue
                error = await _prepare_file(
                    download_id, episode_id, path, index, len(targets)
                )
                if not _still_held(download_id, episode_id, path):
                    hls.clear_for(path)
                    trickplay.clear_for(path)
                    continue
                _finish_episode(episode_id, error)
                if error:
                    failure = error
                elif episode_id is not None and not _has_tmdb_still(episode_id):
                    await stills.ensure(episode_id, path)
            _finish(download_id, failure)
            # Only decides when the source can go (services/sources.py), so a failure
            # here must not take the title away.
            for _episode_id, path in targets:
                if os.path.exists(path):
                    await _build_extras(await mediainfo.probe(path))
    except Exception as exc:  # noqa: BLE001 - never let this kill the sync loop
        log.exception("preparation failed for download %s", download_id)
        _finish(download_id, str(exc)[:400])
    finally:
        _running.discard(download_id)
        _progress.pop(download_id, None)


def _has_tmdb_still(episode_id: int) -> bool:
    with session_scope() as session:
        episode = session.get(Episode, episode_id)
        return bool(episode and episode.still_path)


def _live_download(session, download_id: int) -> Download | None:
    download = session.get(Download, download_id)
    if download is None or download.reaped_at is not None \
            or download.state == DownloadState.removed.value:
        return None
    return download


def _still_held(download_id: int, episode_id: int | None, path: str) -> bool:
    with session_scope() as session:
        if episode_id is None:
            download = _live_download(session, download_id)
            return download is not None and _resolve_path(download) == path
        episode = session.get(Episode, episode_id)
        if episode is None or not episode.file_path or not episode.download_id:
            return False
        return _resolve_path(session.get(Download, episode.download_id), episode) == path


def _finish_episode(episode_id: int | None, error: str | None) -> None:
    if episode_id is None:
        return
    with session_scope() as session:
        episode = session.get(Episode, episode_id)
        if episode is None:
            return
        episode.prepare_error = error
        episode.prepared_at = None if error else utcnow()


def _finish(download_id: int, error: str | None) -> None:
    with session_scope() as session:
        download = _live_download(session, download_id)
        if download is None:
            return
        download.prepare_error = error
        if error is None:
            download.prepared_at = utcnow()
            log.info("download %s is ready to play", download_id)


# Files that could not be indexed, skipped until a restart.
_unindexable: set[str] = set()


async def index_backlog() -> bool:
    with session_scope() as session:
        paths = []
        for download in session.scalars(
            select(Download).where(Download.state.in_(COMPLETE_STATES),
                                   Download.prepared_at.is_not(None))
        ):
            paths += [path for _eid, path in targets_for(session, download) if path]
    for path in paths:
        if path not in _unindexable and os.path.exists(path) and not live.has_index(path):
            async with _gate:
                try:
                    await live.build_index(path)
                except live.LiveError as exc:
                    _unindexable.add(path)
                    log.warning("could not index %s: %s", os.path.basename(path), exc)
            return True
    return False


def busy(download_id: int) -> bool:
    return download_id in _running


async def _extras(download_id: int) -> None:
    if download_id in _running:
        return
    _running.add(download_id)
    try:
        with session_scope() as session:
            download = session.get(Download, download_id)
            if download is None:
                return
            paths = [path for eid, path in targets_for(session, download)
                     if path and os.path.exists(path)]
        async with _gate:
            for path in paths:
                info = await mediainfo.probe(path)
                await _build_extras(info)
    except Exception:  # noqa: BLE001 - never let this kill the sync loop
        log.exception("keeping the extras of download %s failed", download_id)
    finally:
        _running.discard(download_id)


def start_extras(download_id: int) -> None:
    if download_id in _running:
        return
    asyncio.create_task(_extras(download_id))


def start(download_id: int) -> None:
    if download_id in _running:
        return
    asyncio.create_task(prepare(download_id))


def retry(session: DBSession, download: Download) -> bool:
    """Retry a failed preparation, clearing the error and any half-written rendition."""
    from . import hls, trickplay

    if download.state not in COMPLETE_STATES or download.prepared_at is not None:
        return False
    if download.prepare_error is None or download.id in _running:
        return False

    for episode_id, path in targets_for(session, download):
        if episode_id is not None:
            episode = session.get(Episode, episode_id)
            if episode is not None and episode.prepared_at is None:
                episode.prepare_error = None
        # Only the unfinished half: a completed rendition is still good.
        if path and not _playlist_complete(path):
            hls.clear_for(path)
        if path and not _thumbs_complete(path):
            trickplay.clear_for(path)
    download.prepare_error = None
    session.commit()
    log.info("retrying preparation of download %s on request", download.id)
    start(download.id)
    return True


def ensure_pending(session: DBSession) -> int:
    started = 0
    rows = session.scalars(
        select(Download).where(
            Download.state.in_(COMPLETE_STATES),
            Download.prepared_at.is_(None),
            Download.reaped_at.is_(None),
        )
    )
    for download in rows:
        if download.id in _running:
            continue
        # Errors are not retried on a timer: a broken file would loop forever. See retry().
        if download.prepare_error:
            continue
        start(download.id)
        started += 1
    return started


def adopt_legacy_caches(session: DBSession) -> int:
    from . import hls, trickplay

    moved = 0
    for download in session.scalars(
        select(Download).where(Download.state.in_(COMPLETE_STATES))
    ):
        legacy_paths = {_download_path(download)}
        for episode_id, canonical in targets_for(session, download):
            if not canonical:
                continue
            for legacy in legacy_paths:
                if not legacy or legacy == canonical:
                    continue
                moved += _rename(
                    os.path.dirname(hls.playlist_path_for(legacy)),
                    os.path.dirname(hls.playlist_path_for(canonical)),
                )
                moved += _rename(
                    os.path.dirname(trickplay.manifest_path_for(legacy)),
                    os.path.dirname(trickplay.manifest_path_for(canonical)),
                )
    if moved:
        log.info("adopted %s cache directory(ies) built under the old path", moved)
    return moved


def _download_path(download: Download) -> str | None:
    from . import streaming

    return streaming.download_path(download)


def _rename(source: str, destination: str) -> int:
    if source == destination or not os.path.isdir(source) or os.path.isdir(destination):
        return 0
    try:
        os.rename(source, destination)
        return 1
    except OSError as exc:
        log.warning("could not adopt %s: %s", source, exc)
        return 0


def backfill(session: DBSession) -> tuple[int, int]:
    """Reconcile the markers with what is actually on disk, at startup, both ways."""
    marked = cleared = 0
    rows = list(session.scalars(
        select(Download).where(Download.state.in_(COMPLETE_STATES))
    ))
    for download in rows:
        targets = targets_for(session, download)
        states = {eid: artefacts_ready(path) for eid, path in targets if path}
        for episode_id, ok in states.items():
            if episode_id is None:
                continue
            episode = session.get(Episode, episode_id)
            if episode is None:
                continue
            if ok and episode.prepared_at is None:
                episode.prepared_at = utcnow()
                episode.prepare_error = None
            elif not ok and episode.prepared_at is not None:
                episode.prepared_at = None
                episode.prepare_error = None
        ready = bool(states) and all(states.values())
        if ready and download.prepared_at is None:
            download.prepared_at = utcnow()
            download.prepare_error = None
            marked += 1
        elif not ready and download.prepared_at is not None:
            download.prepared_at = None
            download.prepare_error = None
            cleared += 1
    if marked or cleared:
        session.commit()
        log.info(
            "preparation markers reconciled: %s marked ready, %s cleared",
            marked, cleared,
        )
    return marked, cleared
