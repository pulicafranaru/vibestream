from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Download, DownloadJob, DownloadState, Episode, Torrent
from ..schemas import _wanted_labels, download_summary, torrent_summary
from ..services import downloads as dl_service
from ..services import jobs as jobs_service
from ..services import maturity
from ..services import streaming

router = APIRouter(prefix="/api", tags=["downloads"])


@router.get("/downloads")
def list_downloads(
    session: Session = Depends(get_session),
    active_only: bool = Query(False),
):
    stmt = select(Download).order_by(Download.requested_at.desc())
    if active_only:
        stmt = stmt.where(
            Download.state.in_(
                [
                    DownloadState.requested.value,
                    DownloadState.adding.value,
                    DownloadState.downloading.value,
                    DownloadState.paused.value,
                ]
            )
        )
    rows = maturity.downloads(session.scalars(stmt))
    return [
        {
            **download_summary(row),
            "release": torrent_summary(row.torrent) if row.torrent else None,
        }
        for row in rows
    ]


@router.get("/downloads/manager")
async def manager(session: Session = Depends(get_session)):
    from ..services import linkfetch, preparation, reaper, sources
    from ..services.library import free_bytes
    from ..services.qbit import QbitClient, QbitError
    from ..services.tmdb import poster_url

    rows = maturity.downloads(
        session.scalars(
            select(Download)
            .where(Download.state != DownloadState.removed.value)
            .order_by(Download.requested_at.desc())
        )
    )

    live: dict[str, object] = {}
    live_ok = False
    hashes = [d.info_hash.lower() for d in rows if d.info_hash]
    if hashes:
        try:
            async with QbitClient() as client:
                for status in await client.info(hashes):
                    live[status.hash] = status
            live_ok = True
        except QbitError:
            live_ok = False

    items = []
    for row in rows:
        torrent = row.torrent
        media = torrent.media if torrent else None
        status = live.get((row.info_hash or "").lower()) or linkfetch.status(row)

        size = (status.size if status else 0) or (torrent.size_bytes if torrent else 0)
        uploaded = status.uploaded if status else (row.uploaded_bytes or 0)
        downloaded = status.downloaded if status else (row.downloaded_bytes or 0)
        seeding_seconds = status.seeding_time if status else (row.seeding_seconds or 0)

        items.append(
            {
                "download_id": row.id,
                "torrent_id": row.torrent_id,
                "media_id": media.id if media else None,
                "media_type": (media.media_type if media else None) or "movie",
                "title": (media.title if media and media.title else None)
                or (torrent.parsed_title if torrent else None)
                or (torrent.name if torrent else f"Download {row.id}"),
                "year": (media.year if media else None)
                or (torrent.parsed_year if torrent else None),
                "poster": poster_url(media.poster_path if media else None),
                "release": torrent.name if torrent else None,
                "episodes": _wanted_labels(row),
                "episode_list": await _pack_episodes(session, row),
                "resolution": torrent.resolution if torrent else None,
                "hdr": torrent.hdr if torrent else None,
                "state": row.state,
                "percent": round((status.progress if status else row.progress or 0.0) * 100, 1),
                "size_bytes": size,
                "downloaded_bytes": downloaded,
                "uploaded_bytes": uploaded,
                # qBittorrent's own ratio is -1 for a torrent that has downloaded nothing.
                "ratio": round(uploaded / downloaded, 3) if downloaded > 0 else 0.0,
                "dl_speed": status.dlspeed if status else 0,
                "up_speed": status.upspeed if status else 0,
                "eta_seconds": (status.eta if status else row.eta_seconds),
                "seeders": status.connected_seeds if status else None,
                "leechers": status.connected_leechs if status else None,
                "swarm_seeders": status.swarm_seeds if status else (torrent.seeders if torrent else None),
                "swarm_leechers": status.swarm_leechs if status else (torrent.leechers if torrent else None),
                "seeding_hours": round(seeding_seconds / 3600, 1),
                "error": row.error,
                "playable": row.prepared_at is not None,
                "preparation": preparation.status(row),
                "in_library": bool(row.library_path),
                "source_removed": row.source_removed_at is not None,
                "source_removable": await sources.removable(session, row),
                "source_bytes": sources.source_bytes(session, row)
                if row.source_removed_at is None else 0,
                "requested_at": row.requested_at.isoformat() if row.requested_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "seeding": reaper.seeding_obligation(row),
                "live": status is not None,
            }
        )

    try:
        free = free_bytes()
    except OSError:
        free = None

    return {
        "live": live_ok,
        "totals": {
            "count": len(items),
            "size_bytes": sum(i["size_bytes"] or 0 for i in items),
            "uploaded_bytes": sum(i["uploaded_bytes"] or 0 for i in items),
            "downloaded_bytes": sum(i["downloaded_bytes"] or 0 for i in items),
            "dl_speed": sum(i["dl_speed"] or 0 for i in items),
            "up_speed": sum(i["up_speed"] or 0 for i in items),
            "leechers": sum(i["leechers"] or 0 for i in items),
            "downloading": sum(1 for i in items if i["state"] == "downloading"),
            "free_bytes": free,
            **(await asyncio.to_thread(sources.usage)),
        },
        "space": await sources.summary(session),
        "items": items,
    }


@router.get("/downloads/jobs")
async def list_jobs(session: Session = Depends(get_session)):
    from ..services import linkfetch, sources
    from ..services.library import free_bytes
    from ..services.qbit import QbitClient, QbitError

    limit = maturity.current()
    wanted = [job for job in jobs_service.live_jobs(session)
              if maturity.allowed(maturity.media_of(job.download), limit)]
    rows = {job.download_id: job.download for job in wanted}
    statuses: dict[str, object] = {}
    files: dict[int, list[dict]] = {}
    live_ok = False
    hashes = [d.info_hash.lower() for d in rows.values() if d.info_hash]
    if hashes:
        try:
            async with QbitClient() as client:
                for status in await client.info(hashes):
                    statuses[status.hash] = status
                for row in rows.values():
                    if row.info_hash and row.state in (
                        DownloadState.downloading.value, DownloadState.paused.value
                    ):
                        files[row.id] = await client.files(row.info_hash)
            live_ok = True
        except QbitError:
            live_ok = False

    items = []
    for job in wanted:
        status = statuses.get((job.download.info_hash or "").lower()) \
            or linkfetch.status(job.download)
        item = jobs_service.describe(session, job, status, files.get(job.download_id))
        if item is not None:
            items.append(item)

    def total(field: str) -> int:
        return sum(getattr(statuses.get((d.info_hash or "").lower()), field, 0) or 0
                   for d in rows.values())

    try:
        free = free_bytes()
    except OSError:
        free = None
    return {
        "live": live_ok,
        "totals": {
            "count": len(items),
            "size_bytes": sum(
                (getattr(statuses.get((d.info_hash or "").lower()), "size", 0) or
                 (d.torrent.size_bytes if d.torrent else 0) or 0)
                for d in rows.values()
            ),
            "uploaded_bytes": total("uploaded"),
            "downloaded_bytes": total("downloaded"),
            "dl_speed": total("dlspeed"),
            "up_speed": total("upspeed"),
            "leechers": total("connected_leechs"),
            "downloading": sum(1 for i in items if i["state"] == "downloading"),
            "free_bytes": free,
            **(await asyncio.to_thread(sources.usage)),
        },
        "space": await sources.summary(session),
        "items": items,
    }


def _job(session: Session, job_id: int) -> DownloadJob:
    job = session.get(DownloadJob, job_id)
    if job is None or job.removed_at is not None:
        raise HTTPException(404, "unknown download")
    maturity.require(maturity.media_of(job.download))
    return job


@router.get("/downloads/jobs/{job_id}/inspect")
async def inspect_job(job_id: int, session: Session = Depends(get_session)):
    return await jobs_service.inspect(session, _job(session, job_id))


@router.delete("/downloads/jobs/{job_id}")
async def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = _job(session, job_id)
    download = job.download
    try:
        if job.kind == jobs_service.EPISODE and job.episode_id is not None \
                and download.state != DownloadState.removed.value:
            await dl_service.remove_episode(session, download.id, job.episode_id)
        elif download.state != DownloadState.removed.value:
            await dl_service.cancel_download(session, download.id)
    except dl_service.DownloadError:
        pass
    if job.episode_id is not None:
        jobs_service.forget_episode(session, job.episode_id)
    session.refresh(download)
    if download.state == DownloadState.removed.value or job.kind != jobs_service.EPISODE:
        jobs_service.forget_download(session, download.id)
    job.removed_at = job.removed_at or jobs_service.utcnow()
    session.commit()
    return {"ok": True}


# Before /downloads/{torrent_id}: FastAPI matches in declaration order.
@router.post("/downloads/sync")
async def force_sync(session: Session = Depends(get_session)):
    return await dl_service.sync_active(session)


@router.get("/downloads/space")
async def space(session: Session = Depends(get_session)):
    from ..services import sources

    return await sources.summary(session)


@router.post("/downloads/sources/remove")
async def remove_sources(
    include_seeding: bool = Query(False, description="also those still seeding: a hit and run"),
    session: Session = Depends(get_session),
):
    from ..services import sources

    result = await sources.remove_finished(session)
    if include_seeding:
        for download in session.scalars(
            select(Download).where(Download.source_removed_at.is_(None),
                                   Download.prepared_at.is_not(None))
        ):
            if await sources.removable(session, download):
                try:
                    result["freed_bytes"] += await sources.remove_source(
                        session, download, force=True
                    )
                    result["removed"] += 1
                except dl_service.DownloadError:
                    continue
    return {**result, "space": await sources.summary(session)}


@router.post("/downloads/{download_id}/remove-source")
async def remove_source(
    download_id: int,
    force: bool = Query(False, description="before seeding is done: a hit and run"),
    session: Session = Depends(get_session),
):
    from ..services import sources

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(404, "unknown download")
    try:
        freed = await sources.remove_source(session, download, force=force)
    except dl_service.DownloadError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"freed_bytes": freed, "space": await sources.summary(session)}


def _needed_bytes(session: Session, torrent_id: int, episode_id: int | None,
                  everything: bool) -> int:
    from ..services import shows, sources

    torrent = session.get(Torrent, torrent_id)
    if torrent is None:
        return 0
    existing = session.scalar(select(Download).where(Download.torrent_id == torrent_id))
    live = existing is not None and existing.state != DownloadState.removed.value
    if episode_id is not None and torrent.episode is None:
        episode = session.get(Episode, episode_id)
        if episode is not None and episode.file_path:
            return 0
        meta = dl_service.cached_meta(torrent.id)
        files = len(shows.pack_video_paths(meta.files)) if meta else 0
        return sources.cost_of(torrent, (torrent.size_bytes or 0) // max(1, files or 10))
    if live:
        if not everything or dl_service.wanted_paths(existing) is None:
            return 0
        held = existing.downloaded_bytes or 0
        return sources.cost_of(torrent, max(0, (torrent.size_bytes or 0) - held))
    return sources.cost_of(torrent)


@router.post("/downloads/{torrent_id}")
async def start_download(
    torrent_id: int,
    episode: int | None = Query(None, description="one episode out of a season pack"),
    scope: str | None = Query(None, pattern="^all$", description="all of a partly fetched pack"),
    ignore_space: bool = Query(False, description="download even though space is low"),
    session: Session = Depends(get_session),
):
    from ..services import sources

    torrent = session.get(Torrent, torrent_id)
    if torrent is not None:
        maturity.require(torrent.media)
    # Low on space: say so, with what removing finished sources would give
    # back, rather than quietly filling the disk. 507 is Insufficient Storage.
    needed = _needed_bytes(session, torrent_id, episode, scope == "all")
    if needed:
        shortfall = await sources.space_check(session, needed)
        if shortfall and (not ignore_space or not shortfall["fits"]):
            return JSONResponse(status_code=507, content={
                "detail": shortfall["message"], "space": shortfall,
            })
    try:
        download = await dl_service.request_with_fallback(
            session, torrent_id, episode_id=episode, everything=scope == "all"
        )
    except dl_service.DownloadError as exc:
        raise HTTPException(400, dl_service.friendly_error(str(exc))) from exc
    jobs_service.record(session, download, download.torrent,
                        episode_id=None if scope == "all" else episode)
    summary = download_summary(download)
    if download.torrent_id != torrent_id:
        summary["replaces"] = torrent_id
    return summary


@router.delete("/downloads/{download_id}")
async def cancel(
    download_id: int,
    delete_files: bool = Query(True),
    session: Session = Depends(get_session),
):
    try:
        await dl_service.cancel_download(session, download_id, delete_files)
    except dl_service.DownloadError as exc:
        raise HTTPException(404, str(exc)) from exc
    jobs_service.forget_download(session, download_id)
    return {"ok": True}


@router.delete("/downloads/{download_id}/episodes/{episode_id}")
async def remove_episode(
    download_id: int,
    episode_id: int,
    session: Session = Depends(get_session),
):
    try:
        download = await dl_service.remove_episode(session, download_id, episode_id)
    except dl_service.DownloadError as exc:
        raise HTTPException(404, str(exc)) from exc
    jobs_service.forget_episode(session, episode_id)
    if download.state == DownloadState.removed.value:
        jobs_service.forget_download(session, download.id)
    return {"ok": True, "removed": download.state == DownloadState.removed.value}


async def _pack_episodes(session: Session, row: Download) -> list[dict] | None:
    from ..models import Episode
    from ..services import shows

    torrent = row.torrent
    media = torrent.media if torrent else None
    if not torrent or torrent.episode is not None or not media or media.media_type != "tv":
        return None
    meta = dl_service.cached_meta(torrent.id)
    if meta is None:
        return None
    slots = await shows.slot_files(
        session, media, torrent, shows.pack_video_paths(meta.files), sync=False
    )
    wanted = dl_service.wanted_paths(row)
    if wanted is not None:
        slots = {slot: path for slot, path in slots.items() if path in set(wanted)}
    out = []
    for (season, number), _path in sorted(slots.items()):
        episode = session.scalar(
            select(Episode).where(
                Episode.media_id == media.id,
                Episode.season_number == season,
                Episode.number == number,
            )
        )
        if episode is None:
            continue
        out.append({
            "episode_id": episode.id,
            "label": f"S{season}:E{number}",
            "name": episode.name,
            "here": episode.download_id == row.id,
            "ready": episode.download_id == row.id and episode.prepared_at is not None,
        })
    return out


def _load(session: Session, download_id: int) -> Download:
    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(404, "unknown download")
    return download


@router.get("/stream/{download_id}/status")
async def stream_status(download_id: int, session: Session = Depends(get_session)):
    download = _load(session, download_id)
    state = await streaming.readiness(download)
    return {
        "download_id": download_id,
        "ready": state.ready,
        "reason": state.reason,
        "direct_play": state.direct_play,
        "buffered_bytes": state.buffered_bytes,
        "required_bytes": state.required_bytes,
        "buffer_percent": (
            round(min(1.0, state.buffered_bytes / state.required_bytes) * 100, 1)
            if state.required_bytes
            else 100.0
        ),
        "contiguous_pieces": state.contiguous_pieces,
        "total_pieces": state.total_pieces,
        "progress": round(state.progress, 4),
        "dl_speed": state.dl_speed,
        "file_size": state.file_size,
        "eta_seconds": state.eta_seconds,
    }


@router.get("/stream/{download_id}")
async def stream(
    download_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    download = _load(session, download_id)

    path = streaming.resolve_path(download)
    if not path or not os.path.exists(path):
        raise HTTPException(409, "no playable file on disk yet")

    # The final size, not what is on disk: players need it to seek.
    file_size = download.primary_file_size or os.path.getsize(path)
    if file_size <= 0:
        raise HTTPException(409, "file size unknown")

    mime = streaming.mime_for(path)
    verdict, span = streaming.parse_range_header(
        request.headers.get("range"), file_size
    )

    if verdict == "unsatisfiable":
        return JSONResponse(
            {"detail": "unsatisfiable range"},
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    if verdict == "ok":
        start, end = span
        status_code = 206
    else:
        start, end = 0, file_size - 1
        status_code = 200

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-store",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    # Snapshot now: the body generator runs after the session is closed.
    ctx = streaming.StreamContext.of(download, path, file_size)

    return StreamingResponse(
        streaming.iter_range(ctx, start, end),
        status_code=status_code,
        media_type=mime,
        headers=headers,
    )
