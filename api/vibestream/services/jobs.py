"""Download jobs: what somebody asked for (a film, episode or season), which Downloads lists."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Download, DownloadJob, DownloadState, Episode, Torrent, utcnow
from . import shows

TITLE = "title"
EPISODE = "episode"
SEASON = "season"

QUEUED = ("requested", "adding")

PREPARE_FAILED = "It arrived but could not be made playable. Try again."


def kind_of(session: Session, torrent: Torrent,
            episode_id: int | None) -> tuple[str, int | None]:
    if torrent.season is None:
        return TITLE, None
    if torrent.episode is not None:
        return EPISODE, None if torrent.media_id is None else session.scalar(
            select(Episode.id).where(
                Episode.media_id == torrent.media_id,
                Episode.season_number == torrent.season,
                Episode.number == torrent.episode,
            )
        )
    if episode_id is not None:
        return EPISODE, episode_id
    return SEASON, None


def record(session: Session, download: Download, torrent: Torrent,
           episode_id: int | None = None) -> DownloadJob:
    kind, episode_id = kind_of(session, torrent, episode_id)
    if kind == EPISODE and episode_id is not None:
        same = select(DownloadJob).where(
            DownloadJob.episode_id == episode_id, DownloadJob.removed_at.is_(None)
        )
    else:
        same = select(DownloadJob).where(
            DownloadJob.download_id == download.id, DownloadJob.kind == kind,
            DownloadJob.removed_at.is_(None),
        )
    job = session.scalar(same)
    if job is not None:
        if job.download_id != download.id:
            job.download_id = download.id
            session.commit()
        return job
    job = DownloadJob(download_id=download.id, kind=kind, episode_id=episode_id)
    session.add(job)
    session.commit()
    return job


def forget_download(session: Session, download_id: int) -> None:
    for job in session.scalars(select(DownloadJob).where(
        DownloadJob.download_id == download_id, DownloadJob.removed_at.is_(None)
    )):
        job.removed_at = utcnow()
    session.commit()


def forget_episode(session: Session, episode_id: int) -> None:
    for job in session.scalars(select(DownloadJob).where(
        DownloadJob.episode_id == episode_id, DownloadJob.removed_at.is_(None)
    )):
        job.removed_at = utcnow()
    session.commit()


def backfill(session: Session) -> int:
    """Jobs for downloads that have none yet. Runs at every start."""
    have = set(session.scalars(select(DownloadJob.download_id)))
    made = 0
    for download in session.scalars(select(Download).where(
        Download.state != DownloadState.removed.value
    )):
        if download.id in have or download.torrent is None:
            continue
        torrent = download.torrent
        kind, episode_id = kind_of(session, torrent, None)
        if kind != SEASON or download.wanted_files is None:
            session.add(DownloadJob(download_id=download.id, kind=kind, episode_id=episode_id,
                                    requested_at=download.requested_at))
            made += 1
            continue
        held = set(session.scalars(select(Episode.id).where(Episode.download_id == download.id)))
        wanted = set(_wanted_episodes(session, download))
        for ep_id in sorted(held | wanted):
            when = download.wanted_at if ep_id in wanted and download.wanted_at else \
                download.requested_at
            session.add(DownloadJob(download_id=download.id, kind=EPISODE,
                                    episode_id=ep_id, requested_at=when))
            made += 1
        if not held and not wanted:
            session.add(DownloadJob(download_id=download.id, kind=SEASON,
                                    requested_at=download.requested_at))
            made += 1
    session.commit()
    return made


def _wanted_slots(download: Download) -> set[tuple[int, int]] | None:
    if not download.wanted_files:
        return None
    try:
        paths = json.loads(download.wanted_files)
    except ValueError:
        return None
    return {s for s in (shows.parse_slot(os.path.basename(str(p))) for p in paths) if s}


def _wanted_episodes(session: Session, download: Download) -> list[int]:
    slots = _wanted_slots(download) or set()
    torrent = download.torrent
    if not slots or torrent is None or torrent.media_id is None:
        return []
    return [
        ep.id for ep in session.scalars(select(Episode).where(Episode.media_id == torrent.media_id))
        if (ep.season_number, ep.number) in slots
    ]


def live_jobs(session: Session) -> list[DownloadJob]:
    return list(session.scalars(
        select(DownloadJob)
        .join(Download, Download.id == DownloadJob.download_id)
        .where(DownloadJob.removed_at.is_(None), Download.state != DownloadState.removed.value)
        .order_by(DownloadJob.requested_at.desc(), DownloadJob.id.desc())
    ))


def _is_video(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in shows.VIDEO_EXTENSIONS


def mine(job: DownloadJob, name: str) -> bool:
    if job.kind != EPISODE or job.episode is None or job.download.torrent.episode is not None:
        return True
    return _is_video(name) and shows.parse_slot(os.path.basename(name)) == (
        job.episode.season_number, job.episode.number
    )


def _progress(job: DownloadJob, files: list[dict] | None) -> tuple[int, int] | None:
    if not files:
        return None
    if job.kind == EPISODE and job.download.torrent.episode is None:
        chosen = [f for f in files if mine(job, f.get("name", ""))]
    else:
        chosen = [f for f in files if int(f.get("priority", 1)) > 0]
    if not chosen:
        return None
    size = sum(int(f.get("size", 0)) for f in chosen)
    done = sum(int(f.get("size", 0)) * float(f.get("progress", 0)) for f in chosen)
    return size, int(done)


def describe(session: Session, job: DownloadJob, status=None,
             files: list[dict] | None = None) -> dict | None:
    from ..schemas import download_summary
    from . import preparation, reaper
    from .downloads import friendly_error
    from .tmdb import backdrop_url, poster_url, still_url

    download = job.download
    torrent = download.torrent
    media = torrent.media if torrent else None
    episode = job.episode
    summary = download_summary(download)

    item = {
        "job_id": job.id,
        "kind": job.kind,
        "download_id": download.id,
        "torrent_id": download.torrent_id,
        "media_id": media.id if media else None,
        "media_type": (media.media_type if media else None) or "movie",
        "title": (media.title if media and media.title else None)
        or (torrent.parsed_title if torrent else None)
        or (torrent.name if torrent else f"Download {download.id}"),
        "year": (media.year if media else None) or (torrent.parsed_year if torrent else None),
        "poster": poster_url(media.poster_path if media else None),
        "backdrop": backdrop_url(media.backdrop_path if media else None, size="w780"),
        "episode": None,
        "label": None,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "release": torrent.name if torrent else None,
        "resolution": torrent.resolution if torrent else None,
        "hdr": torrent.hdr if torrent else None,
        "seeding": reaper.seeding_obligation(download),
        "shares_torrent": session.scalar(
            select(DownloadJob.id).where(
                DownloadJob.download_id == download.id, DownloadJob.id != job.id,
                DownloadJob.removed_at.is_(None),
            ).limit(1)
        ) is not None,
    }
    if episode is not None:
        item["episode"] = {
            "id": episode.id, "season": episode.season_number, "number": episode.number,
            "name": episode.name, "still": still_url(episode.still_path),
        }
        item["label"] = f"S{episode.season_number}:E{episode.number}"
    elif job.kind == SEASON and torrent is not None and torrent.season is not None:
        last = torrent.season_end or torrent.season
        item["label"] = f"Season {torrent.season}" if last == torrent.season else \
            f"Seasons {torrent.season} to {last}"

    state, percent, play_id, error = _state(session, job, download, summary, episode)
    if state is None:
        return None
    measured = _progress(job, files) if state in ("downloading", "paused", "queued") else None
    size = (episode.file_size if episode is not None and episode.file_size else None) \
        or (torrent.size_bytes if torrent and job.kind != EPISODE else None)
    done = None
    if measured:
        size, done = measured
        percent = round(done / size * 100, 1) if size else percent
    speed = status.dlspeed if status is not None and state == "downloading" else 0
    eta = None
    if speed and size and done is not None:
        eta = int((size - done) / speed)
    elif state == "downloading":
        eta = status.eta if status is not None else download.eta_seconds
    prep = preparation.status(download) if state == "preparing" else None
    item.update({
        "state": state,
        "percent": percent,
        "size_bytes": size,
        "downloaded_bytes": done,
        "dl_speed": speed,
        "eta_seconds": eta,
        "prepare_percent": (prep or {}).get("percent") or None,
        "play_id": play_id,
        "error_message": error if error == PREPARE_FAILED else friendly_error(error),
    })
    return item


def _state(session: Session, job: DownloadJob, download: Download, summary: dict,
           episode: Episode | None):
    """States: queued, downloading, paused, preparing, ready, failed; None when gone."""
    row_state = download.state
    percent = summary["percent"]
    if job.kind == EPISODE and episode is not None and download.torrent.episode is None:
        here = episode.download_id is not None and episode.file_path
        if here and episode.prepared_at is not None:
            return "ready", 100.0, f"e{episode.id}", None
        if here and episode.prepare_error:
            return "failed", 100.0, None, PREPARE_FAILED
        if here:
            return "preparing", 100.0, None, None
        slots = _wanted_slots(download)
        wanted = slots is None or (episode.season_number, episode.number) in slots
        if not wanted:
            return None, None, None, None
        if row_state == DownloadState.error.value:
            return "failed", percent, None, download.error
        if row_state in QUEUED:
            return "queued", 0.0, None, None
        if row_state == DownloadState.paused.value:
            return "paused", percent, None, None
        if row_state == DownloadState.downloading.value:
            return "downloading", percent, None, None
        return "preparing", 100.0, None, None

    if row_state == DownloadState.error.value:
        return "failed", percent, None, download.error
    if row_state in QUEUED:
        return "queued", 0.0, None, None
    if row_state == DownloadState.paused.value:
        return "paused", percent, None, None
    if row_state == DownloadState.downloading.value:
        return "downloading", percent, None, None
    if summary["playable"]:
        if job.kind == SEASON:
            return "ready", 100.0, None, None
        if episode is not None:
            return "ready", 100.0, f"e{episode.id}" if episode.prepared_at else str(download.id), None
        return "ready", 100.0, str(download.id), None
    if summary["prepare_error"]:
        return "failed", 100.0, None, PREPARE_FAILED
    return "preparing", 100.0, None, None


_SECRET = re.compile(r"[0-9a-fA-F]{24,}")


def tracker_host(url: str) -> str:
    parts = urlsplit(url or "")
    if parts.hostname:
        return parts.hostname
    return (url or "").strip("* ").strip() or "?"


def scrub(text: str | None) -> str | None:
    return _SECRET.sub("...", text) if text else text


TRACKER_STATUS = {0: "disabled", 1: "not contacted", 2: "working", 3: "updating", 4: "not working"}


def piece_map(states: list[int], buckets: int = 240) -> dict:
    """The pieces in at most `buckets` cells: percent here (0 to 100), and
    whether any of it is being fetched right now.
    """
    count = len(states)
    if not count:
        return {"count": 0, "have": [], "busy": []}
    cells = min(buckets, count)
    have, busy = [], []
    for i in range(cells):
        chunk = states[i * count // cells:(i + 1) * count // cells] or [0]
        have.append(round(100 * sum(1 for s in chunk if s == 2) / len(chunk)))
        busy.append(1 if any(s == 1 for s in chunk) else 0)
    return {"count": count, "have": have, "busy": busy}


def _peer(peer: dict) -> dict:
    return {
        "address": peer.get("address"),
        "client": peer.get("client") or None,
        "country": peer.get("country") or None,
        "country_code": peer.get("country_code") or None,
        "connection": peer.get("connection") or None,
        "flags": peer.get("flags") or None,
        "progress": round(float(peer.get("progress") or 0) * 100, 1),
        "dl_speed": int(peer.get("dl_speed") or 0),
        "up_speed": int(peer.get("up_speed") or 0),
        "downloaded": int(peer.get("downloaded") or 0),
        "uploaded": int(peer.get("uploaded") or 0),
    }


def _tracker(entry: dict) -> dict:
    return {
        "host": tracker_host(entry.get("url", "")),
        "status": TRACKER_STATUS.get(int(entry.get("status", 1)), "unknown"),
        "seeds": entry.get("num_seeds"),
        "leechers": entry.get("num_leeches"),
        "peers": entry.get("num_peers"),
        "downloaded": entry.get("num_downloaded"),
        "message": scrub(entry.get("msg")) or None,
    }


def when(stamp) -> str | None:
    from datetime import datetime, timezone

    try:
        value = int(stamp)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


async def inspect(session: Session, job: DownloadJob) -> dict:
    from ..schemas import torrent_summary
    from . import preparation, sources
    from .qbit import QbitClient, QbitError

    download = job.download
    torrent = download.torrent
    status = props = None
    files: list[dict] = []
    peers: list[dict] = []
    trackers: list[dict] = []
    pieces: list[int] = []
    live = False
    if download.info_hash and download.source_removed_at is None:
        try:
            async with QbitClient() as client:
                status = await client.get(download.info_hash)
                if status is not None:
                    props = await client.properties(download.info_hash)
                    files = await client.files(download.info_hash)
                    peers = await client.peers(download.info_hash)
                    trackers = await client.trackers(download.info_hash)
                    pieces = await client.piece_states(download.info_hash)
                    live = True
        except QbitError:
            live = False
    elif download.link:
        from . import linkfetch

        status = linkfetch.status(download)
        live = status is not None

    props = props or {}
    item = describe(session, job, status, files)
    return {
        "job": item,
        "live": live,
        "release": torrent_summary(torrent) if torrent else None,
        "torrent": {
            "name": status.name if status else (torrent.name if torrent else None),
            "info_hash": download.info_hash,
            "state": status.state if status else download.state,
            "save_path": status.save_path if status else download.save_path,
            "content_path": status.content_path if status else download.content_path,
            "size_bytes": status.size if status else (torrent.size_bytes if torrent else None),
            "total_size_bytes": props.get("total_size"),
            "progress": round((status.progress if status else download.progress or 0) * 100, 1),
            "downloaded_bytes": status.downloaded if status else download.downloaded_bytes,
            "uploaded_bytes": status.uploaded if status else download.uploaded_bytes,
            "wasted_bytes": props.get("total_wasted"),
            "ratio": round(status.ratio, 3) if status else round(download.ratio or 0, 3),
            "dl_speed": status.dlspeed if status else 0,
            "up_speed": status.upspeed if status else 0,
            "dl_speed_avg": props.get("dl_speed_avg"),
            "up_speed_avg": props.get("up_speed_avg"),
            "eta_seconds": status.eta if status else None,
            "seeding_seconds": status.seeding_time if status else download.seeding_seconds,
            "elapsed_seconds": props.get("time_elapsed"),
            "connections": props.get("nb_connections"),
            "connections_limit": props.get("nb_connections_limit"),
            "seeds": status.connected_seeds if status else None,
            "seeds_total": status.swarm_seeds if status else None,
            "leechers": status.connected_leechs if status else None,
            "leechers_total": status.swarm_leechs if status else None,
            "piece_size": props.get("piece_size"),
            "pieces_have": props.get("pieces_have"),
            "pieces_count": props.get("pieces_num"),
            "reannounce_seconds": props.get("reannounce"),
            "created_by": props.get("created_by") or None,
            "created_at": when(props.get("creation_date")),
            "added_at": when(props.get("addition_date"))
            or (download.added_at.isoformat() if download.added_at else None),
            "completed_at": when(props.get("completion_date"))
            or (download.completed_at.isoformat() if download.completed_at else None),
            "last_seen_complete": when(props.get("last_seen")),
        },
        "pieces": piece_map(pieces),
        "files": [
            {
                "name": f.get("name"),
                "size_bytes": int(f.get("size", 0)),
                "progress": round(float(f.get("progress", 0)) * 100, 1),
                "priority": int(f.get("priority", 1)),
                "availability": f.get("availability"),
                "mine": mine(job, f.get("name", "")),
            }
            for f in files
        ],
        "peers": sorted((_peer(p) for p in peers),
                        key=lambda p: (p["dl_speed"] + p["up_speed"], p["progress"]),
                        reverse=True)[:100],
        "trackers": [_tracker(t) for t in trackers],
        "library": {
            "requested_at": download.requested_at.isoformat() if download.requested_at else None,
            "library_path": download.library_path,
            "play_path": download.play_path,
            "wanted": _wanted_labels(download),
            "preparation": preparation.status(download),
            "seeding": item["seeding"] if item else None,
            "source_removed": download.source_removed_at is not None,
            "source_removable": await sources.removable(session, download),
            "source_bytes": sources.source_bytes(session, download)
            if download.source_removed_at is None else 0,
        },
    }


def _wanted_labels(download: Download) -> list[str] | None:
    slots = _wanted_slots(download)
    if slots is None:
        return None
    return [f"S{s}:E{n}" for s, n in sorted(slots)]
