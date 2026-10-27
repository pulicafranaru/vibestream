"""Download orchestration: requested -> adding -> downloading -> completed -> linked -> prepared."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import Download, DownloadState, Episode, Torrent, utcnow
from ..torrentmeta import TorrentMeta, parse_torrent
from . import library
from .filelist import FilelistClient, FilelistError, TorrentGone
from .qbit import QbitClient, QbitError, QbitNotFound

log = logging.getLogger(__name__)

_meta_cache: dict[str, TorrentMeta] = {}

TORRENT_CACHE_DIR = "/app/data/torrents"


class DownloadError(RuntimeError):
    pass


class ReleaseGone(DownloadError):
    """The tracker deleted this release; another one has to be used."""


_FRIENDLY = [
    ("no copy left", "None of this title's releases are on the tracker any more."),
    ("no longer has this release", "This release was removed from the tracker."),
    ("credentials are not configured", "The tracker login is not set up on the server."),
    ("not in this season pack", "That episode is not in this release."),
    ("not part of this", "That episode is not in this release."),
    ("could not fetch .torrent", "The tracker did not hand over the download. Try again in a minute."),
    ("sent its file list", "Nobody sharing this release answered. Try another one, or again later."),
    ("rate limit", "The tracker is busy. Try again in a few minutes."),
    ("qbittorrent state", "The download stopped. Try again."),
    ("qbittorrent", "The downloader is not answering. Try again in a minute."),
    ("connect", "The downloader is not answering. Try again in a minute."),
]


def friendly_error(error: str | None) -> str | None:
    if not error:
        return None
    lowered = error.lower()
    for needle, message in _FRIENDLY:
        if needle in lowered:
            return message
    return "The download could not start. Try again."


def preparation():
    """Imported on use: a module-level import closes a cycle (streaming, preparation)."""
    from . import preparation as module

    return module


def _torrent_cache_path(torrent_id: int) -> str:
    os.makedirs(TORRENT_CACHE_DIR, exist_ok=True)
    return os.path.join(TORRENT_CACHE_DIR, f"{torrent_id}.torrent")


async def fetch_torrent_bytes(torrent_id: int) -> bytes:
    """Takes a bare id, not a row: called from a StreamingResponse body after the session closed."""
    cached = _torrent_cache_path(torrent_id)
    if os.path.exists(cached) and os.path.getsize(cached) > 100:
        with open(cached, "rb") as fh:
            return fh.read()

    from . import addons

    if torrent_id >= addons.FIRST_ID:
        from ..db import session_scope

        with session_scope() as s:
            row = s.get(Torrent, torrent_id)
            if row is None or row.origin != "addon" or not row.info_hash:
                raise DownloadError(f"unknown release {torrent_id}")
            info_hash, name, announce = row.info_hash, row.name, row.announce
        try:
            content = await addons.metadata_bytes(info_hash, name, announce)
        except (addons.AddonError, QbitError) as exc:
            raise DownloadError(str(exc)) from exc
        with open(cached, "wb") as fh:
            fh.write(content)
        return content

    if not settings.filelist_configured:
        raise DownloadError("filelist credentials are not configured")

    url = (
        f"https://filelist.io/download.php?id={torrent_id}"
        f"&passkey={settings.filelist_passkey}"
    )
    client = FilelistClient()
    try:
        content = await client.fetch_torrent_file(url)
    except TorrentGone as exc:
        raise ReleaseGone(f"the tracker no longer has this release ({torrent_id})") from exc
    except FilelistError as exc:
        raise DownloadError(f"could not fetch .torrent for {torrent_id}: {exc}") from exc

    with open(cached, "wb") as fh:
        fh.write(content)
    return content


def get_meta(info_hash: str) -> TorrentMeta | None:
    return _meta_cache.get(info_hash.lower())


def remember_meta(meta: TorrentMeta) -> None:
    _meta_cache[meta.infohash.lower()] = meta


def cached_meta(torrent_id: int) -> TorrentMeta | None:
    """Cached metadata or None: the tracker API allows only 150 requests an hour."""
    path = _torrent_cache_path(torrent_id)
    try:
        if os.path.getsize(path) <= 100:
            return None
        with open(path, "rb") as fh:
            return parse_torrent(fh.read())
    except (OSError, ValueError):
        return None


def wanted_paths(download: Download) -> list[str] | None:
    if not download.wanted_files:
        return None
    try:
        value = json.loads(download.wanted_files)
    except ValueError:
        return None
    return [str(p) for p in value] if isinstance(value, list) else None


async def episode_file(session: Session, torrent: Torrent, meta: TorrentMeta,
                       episode: Episode) -> str | None:
    from . import shows

    media = torrent.media
    if media is None:
        return None
    slots = await shows.slot_files(session, media, torrent, shows.pack_video_paths(meta.files))
    return slots.get((episode.season_number, episode.number))


def _matches(name: str, wanted: set[str]) -> bool:
    # qBittorrent prefixes a multi-file torrent's files with its folder; the
    # metadata does not. Either way, the tail is the file.
    return any(name == w or name.endswith("/" + w) for w in wanted)


def _sidecar_of(name: str, wanted: set[str]) -> bool:
    stem, ext = os.path.splitext(name)
    if ext.lower() not in library.SIDECAR_EXT:
        return False
    for w in wanted:
        base = os.path.splitext(w)[0]
        for candidate in (stem, stem.rsplit(".", 1)[0]):
            if candidate == base or candidate.endswith("/" + base):
                return True
    return False


def _selected(name: str, wanted: set[str]) -> bool:
    return _matches(name, wanted) or _sidecar_of(name, wanted)


async def _apply_wanted(client: QbitClient, info_hash: str, wanted: list[str] | None) -> None:
    """Indexes come from qBittorrent, not the metadata: the two can disagree (padding files)."""
    files: list[dict] = []
    for _ in range(30):
        # Listed a moment after the add: until then qBittorrent lists no files or
        # answers 404 for the hash.
        try:
            files = await client.files(info_hash)
        except QbitNotFound:
            files = []
        if files:
            break
        await asyncio.sleep(0.5)
    if not files:
        raise DownloadError("qBittorrent did not list the torrent's files")

    def index(position: int, entry: dict) -> int:
        return int(entry.get("index", position))

    if wanted is None:
        off = [index(i, f) for i, f in enumerate(files) if int(f.get("priority", 1)) == 0]
        await client.set_file_priority(info_hash, off, 1)
        return

    want = set(wanted)
    on = [index(i, f) for i, f in enumerate(files) if _selected(f.get("name", ""), want)]
    off = [index(i, f) for i, f in enumerate(files) if not _selected(f.get("name", ""), want)]
    if not any(_matches(f.get("name", ""), want) for f in files):
        raise DownloadError("that episode's file is not in this torrent")
    await client.set_file_priority(info_hash, off, 0)
    await client.set_file_priority(info_hash, on, 1)


async def _wanted_complete(client: QbitClient, download: Download) -> bool:
    """Per file: right after a pack is asked for another episode, qBittorrent can
    briefly report 100% for the torrent.
    """
    wanted = wanted_paths(download)
    files = await client.files(download.info_hash)
    if not files:
        return False
    if wanted is None:
        return all(float(f.get("progress", 0)) >= 1.0 for f in files
                   if int(f.get("priority", 1)) > 0)
    want = set(wanted)
    chosen = [f for f in files if _selected(f.get("name", ""), want)]
    return bool(chosen) and all(float(f.get("progress", 0)) >= 1.0 for f in chosen)


async def request_download(
    session: Session, torrent_id: int, episode_id: int | None = None,
    everything: bool = False,
) -> Download:
    """Idempotent per release. `episode_id` fetches one file of a pack; `everything` the whole torrent."""
    torrent = session.get(Torrent, torrent_id)
    if torrent is None:
        raise DownloadError(f"unknown release {torrent_id}")

    episode: Episode | None = None
    if episode_id is not None and torrent.episode is None:
        from . import shows

        episode = session.get(Episode, episode_id)
        if episode is None or episode.media_id != torrent.media_id or not shows.covers(
            torrent, episode.season_number, episode.number
        ):
            raise DownloadError("that episode is not part of this release")
        if episode.file_path and episode.download_id:
            held = session.get(Download, episode.download_id)
            if held is not None:
                return held

    existing = session.scalar(
        select(Download).where(Download.torrent_id == torrent_id)
    )
    if existing and existing.source_removed_at is not None \
            and existing.state != DownloadState.removed.value:
        return await _fetch_again(session, existing, torrent, episode, everything)
    if existing and existing.state not in (
        DownloadState.error.value,
        DownloadState.removed.value,
    ):
        current = wanted_paths(existing)
        if current is None or (episode is None and not everything):
            # Asking again for something that could not be prepared prepares it again
            # (the "Try again" button).
            preparation().retry(session, existing)
            return existing
        if everything:
            grown: list[str] | None = None
        else:
            meta = parse_torrent(await fetch_torrent_bytes(torrent.id))
            path = await episode_file(session, torrent, meta, episode)
            if path is None:
                raise DownloadError(
                    f"S{episode.season_number}E{episode.number} is not in this season pack"
                )
            if path in current:
                preparation().retry(session, existing)
                return existing
            grown = current + [path]
        try:
            async with QbitClient() as client:
                await _apply_wanted(client, existing.info_hash, grown)
                await client.resume(existing.info_hash)
        except QbitError as exc:
            raise DownloadError(str(exc)) from exc
        existing.wanted_files = json.dumps(grown) if grown is not None else None
        existing.wanted_at = utcnow()
        existing.prepared_at = None
        existing.prepare_error = None
        existing.state = DownloadState.downloading.value
        session.commit()
        record_event(
            session, "downloads",
            f"added {'the rest of' if grown is None else 'an episode of'} {torrent.name}",
            f"wanted={len(grown) if grown is not None else 'all'}",
        )
        return existing

    download = existing or Download(torrent_id=torrent_id)
    old_hash, old_link = download.info_hash, download.link
    download.state = DownloadState.adding.value
    download.error = None
    download.reaped_at = None
    # A source removed last time would keep sync from ever tracking this fetch.
    download.source_removed_at = None
    download.play_path = None
    download.requested_at = utcnow()
    download.link = None
    download.info_hash = None
    if existing is None:
        session.add(download)
    session.commit()

    if _by_torbox(torrent, episode, everything) and await _start_torbox(session, download, torrent):
        if old_hash:
            await _drop_torrent(session, old_hash, download.id, delete_files=True)
        return download
    if _by_link(torrent, episode, everything) and await _start_link(session, download, torrent):
        if old_hash:
            await _drop_torrent(session, old_hash, download.id, delete_files=True)
        return download
    if old_link:
        from . import linkfetch

        linkfetch.remove_files(download.id)

    try:
        content = await fetch_torrent_bytes(torrent.id)
        meta = parse_torrent(content)
        remember_meta(meta)
        if torrent.origin == "addon":
            torrent.size_bytes = meta.total_length
            torrent.file_count = len(meta.files)

        # Two downloads of one torrent would each take the other's progress and
        # delete the other's files, so the second is turned away.
        sharing = session.scalar(
            select(Download).where(
                Download.info_hash == meta.infohash, Download.id != download.id,
                Download.reaped_at.is_(None),
                Download.state != DownloadState.removed.value,
            )
        )
        if sharing is not None:
            other = sharing.torrent.media.title if sharing.torrent and sharing.torrent.media \
                else "another title"
            raise DownloadError(
                f"This release is the same torrent as {other}, which is downloaded or on "
                f"its way. Choose another release for this one."
            )
        if old_hash:
            # qBittorrent would refuse to take the failed torrent again. The files stay.
            await _drop_torrent(session, old_hash, download.id, delete_files=False)

        wanted: list[str] | None = None
        film = _film_in_box_set(torrent, meta)
        if film is not None:
            wanted = [film.path]
        if episode is not None:
            path = await episode_file(session, torrent, meta, episode)
            if path is None:
                raise DownloadError(
                    f"S{episode.season_number}E{episode.number} is not in this season pack"
                )
            wanted = [path]
        primary = meta.largest_video_file()
        if wanted:
            primary = next((f for f in meta.files if f.path == wanted[0]), primary)
        if primary:
            download.primary_file = primary.path
            download.primary_file_size = primary.length
            download.primary_file_index = meta.files.index(primary)
        download.wanted_files = json.dumps(wanted) if wanted is not None else None
        download.wanted_at = utcnow()
        session.commit()

        async with QbitClient() as client:
            # Added stopped, so no other episode is fetched before priorities are set.
            reported = await client.add_torrent_file(
                content,
                filename=f"{torrent.id}.torrent",
                save_path=settings.qbit_download_dir,
                sequential=True,
                first_last_prio=True,
                paused=wanted is not None,
            )
            download.info_hash = meta.infohash
            session.commit()
            if wanted is not None:
                await _apply_wanted(client, reported or meta.infohash, wanted)
                await client.resume(reported or meta.infohash)

        # qBittorrent 5.x returns the infohash it derived. A mismatch with the local one
        # means the bencode parsing, and so the streaming piece math, is wrong.
        if reported and reported != meta.infohash:
            log.warning(
                "infohash mismatch for release %s: computed %s, qBittorrent says %s",
                torrent.id, meta.infohash, reported,
            )
            download.info_hash = reported
            session.commit()

        download.state = DownloadState.downloading.value
        download.added_at = utcnow()
        download.reaped_at = None
        session.commit()
        record_event(
            session, "downloads", f"queued {torrent.name}",
            f"hash={meta.infohash} size={meta.total_length / 1024 ** 3:.2f}GiB",
        )
    except Exception as exc:
        if download.info_hash:
            # Left stopped in qBittorrent, the next sync would turn this error into a
            # "paused" nobody can resume. The files stay.
            await _drop_torrent(session, download.info_hash, download.id, delete_files=False)
            download.info_hash = None
        download.state = DownloadState.error.value
        download.error = str(exc)[:1000]
        session.commit()
        record_event(
            session, "downloads", f"failed to queue {torrent.name}", str(exc), level="error"
        )
        if isinstance(exc, ReleaseGone):
            raise
        raise DownloadError(str(exc)) from exc

    return download


def _one_file(torrent: Torrent, episode: Episode | None, everything: bool) -> bool:
    return episode is None and not everything and (torrent.season is None or torrent.episode is not None)


def _by_torbox(torrent: Torrent, episode: Episode | None, everything: bool) -> bool:
    """Through TorBox: an addon release of one film or one episode. Never
    a filelist one (services/torbox.py, allowed)."""
    from . import torbox

    return settings.torbox_configured and torbox.allowed(torrent) and \
        _one_file(torrent, episode, everything)


async def _start_torbox(session: Session, download: Download, torrent: Torrent) -> bool:
    """Hands it to TorBox; the fetch waits there until TorBox has it. False
    when TorBox will not take it, and it goes the other ways instead."""
    from . import linkfetch, torbox

    try:
        torrent_id = await torbox.add(torrent)
    except Exception as exc:  # noqa: BLE001 - the other ways are still there
        log.warning("TorBox would not take %s: %s", torrent.name, exc)
        record_event(session, "downloads", f"TorBox would not take {torrent.name}", str(exc),
                     level="warning")
        return False
    download.link = f"{torbox.PREFIX}{torrent_id}"
    download.info_hash = None
    download.wanted_files = None
    download.wanted_at = utcnow()
    download.save_path = linkfetch.folder(download.id)
    download.progress = 0.0
    download.downloaded_bytes = 0
    download.state = DownloadState.downloading.value
    download.added_at = utcnow()
    session.commit()
    linkfetch.start(download.id)
    record_event(session, "downloads", f"queued {torrent.name} on TorBox")
    return True


def _by_link(torrent: Torrent, episode: Episode | None, everything: bool) -> bool:
    return (
        settings.addons_configured and torrent.origin == "addon" and bool(torrent.linkable)
        and episode is None and not everything
        and (torrent.season is None or torrent.episode is not None)
    )


async def _drop_torrent(session: Session, info_hash: str, download_id: int,
                        delete_files: bool) -> None:
    shared = session.scalar(
        select(Download.id).where(
            Download.info_hash == info_hash, Download.id != download_id,
            Download.reaped_at.is_(None), Download.state != DownloadState.removed.value,
        ).limit(1)
    )
    if shared is not None:
        return
    try:
        async with QbitClient() as client:
            await client.delete(info_hash, delete_files=delete_files)
    except QbitError as exc:
        log.warning("could not remove %s from qBittorrent: %s", info_hash, exc)


async def _start_link(session: Session, download: Download, torrent: Torrent) -> bool:
    from . import addons, linkfetch

    try:
        link = await addons.link_for(torrent)
    except Exception as exc:  # noqa: BLE001 - the torrent is still there to fetch
        log.warning("no debrid link for %s: %s", torrent.name, exc)
        return False
    if not link:
        return False
    download.link = link
    download.info_hash = None
    download.wanted_files = None
    download.wanted_at = utcnow()
    download.save_path = linkfetch.folder(download.id)
    download.progress = 0.0
    download.downloaded_bytes = 0
    download.state = DownloadState.downloading.value
    download.added_at = utcnow()
    session.commit()
    linkfetch.start(download.id)
    record_event(session, "downloads", f"queued {torrent.name} from a debrid link")
    return True


def _film_in_box_set(torrent: Torrent, meta: TorrentMeta):
    """The film wanted out of a multi-film torrent; None for a single film. Ambiguous ones are refused."""
    if not torrent.file_name or torrent.season is not None:
        return None
    videos = [f for f in meta.files
              if f.path.lower().endswith(library.VIDEO_EXT)
              and not library.SKIP_PATTERNS.search(os.path.basename(f.path))]
    if len(videos) < 2:
        return None

    def plain(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", os.path.basename(name).lower())

    wanted = torrent.file_name
    match = next((f for f in videos if os.path.basename(f.path) == wanted), None) or \
        next((f for f in videos if plain(f.path) == plain(wanted)), None)
    if match is not None:
        return match
    sizes = sorted((f.length for f in videos), reverse=True)
    if sizes[0] >= 2 * sizes[1]:
        return None
    raise DownloadError(
        "This release holds several films and none of its files is named as this one. "
        "Choose another release."
    )


def forget_gone(session: Session, torrent: Torrent) -> None:
    torrent.gone_at = utcnow()
    torrent.media_id = None
    failed = session.scalar(select(Download).where(Download.torrent_id == torrent.id))
    if failed is not None and failed.state == DownloadState.error.value and not failed.library_path:
        session.delete(failed)
    session.commit()
    record_event(session, "downloads", f"the tracker deleted {torrent.name}", f"release={torrent.id}")


def next_release(session: Session, media_id: int, gone: Torrent,
                 episode_id: int | None, everything: bool) -> Torrent | None:
    from . import shows
    from .offered import offered
    from .ranking import rank

    others = offered(session.scalars(
        select(Torrent).where(Torrent.media_id == media_id, Torrent.id != gone.id)
    ))
    failed = set(session.scalars(
        select(Download.torrent_id).where(
            Download.torrent_id.in_([t.id for t in others]),
            Download.state == DownloadState.error.value,
        )
    ))
    others = [t for t in others if t.id not in failed]

    episode = session.get(Episode, episode_id) if episode_id is not None else None
    if episode is not None:
        fits = [t for t in others if shows.covers(t, episode.season_number, episode.number)]
    elif gone.season is None:
        fits = [t for t in others if t.season is None]
    elif gone.episode is not None:
        fits = [t for t in others if shows.covers(t, gone.season, gone.episode)]
    else:
        last = gone.season_end or gone.season
        fits = [t for t in others if t.episode is None and t.season is not None
                and t.season <= gone.season and (t.season_end or t.season) >= last]
    ranked = rank(fits)
    return ranked[0].torrent if ranked else None


async def request_with_fallback(
    session: Session, torrent_id: int, *, episode_id: int | None = None,
    everything: bool = False,
) -> Download:
    for _ in range(4):
        try:
            return await request_download(
                session, torrent_id, episode_id=episode_id, everything=everything
            )
        except ReleaseGone:
            gone = session.get(Torrent, torrent_id)
            media_id = gone.media_id
            forget_gone(session, gone)
            replacement = next_release(session, media_id, gone, episode_id, everything) \
                if media_id is not None else None
            if replacement is None:
                raise DownloadError("no copy left on the tracker") from None
            log.info("release %s was deleted from the tracker; using %s", torrent_id, replacement.id)
            torrent_id = replacement.id
    raise DownloadError("no copy left on the tracker")


async def _fetch_again(session: Session, download: Download, torrent: Torrent,
                       episode: Episode | None, everything: bool) -> Download:
    from . import shows

    if episode is None and not everything:
        return download
    content = await fetch_torrent_bytes(torrent.id)
    meta = parse_torrent(content)
    remember_meta(meta)
    media = torrent.media
    videos = shows.pack_video_paths(meta.files)
    slots = await shows.slot_files(session, media, torrent, videos, sync=False) if media else {}
    held = {
        path for (season, number), path in slots.items()
        if session.scalar(select(Episode.id).where(
            Episode.media_id == torrent.media_id, Episode.season_number == season,
            Episode.number == number, Episode.file_path.is_not(None),
        ))
    }
    if everything:
        wanted = [p for p in videos if p not in held]
    else:
        path = await episode_file(session, torrent, meta, episode)
        if path is None:
            raise DownloadError(
                f"S{episode.season_number}E{episode.number} is not in this season pack"
            )
        wanted = [] if path in held else [path]
    if not wanted:
        return download

    try:
        async with QbitClient() as client:
            reported = await client.add_torrent_file(
                content, filename=f"{torrent.id}.torrent",
                save_path=settings.qbit_download_dir,
                sequential=True, first_last_prio=True, paused=True,
            )
            await _apply_wanted(client, reported or meta.infohash, wanted)
            await client.resume(reported or meta.infohash)
    except QbitError as exc:
        raise DownloadError(str(exc)) from exc

    download.info_hash = reported or meta.infohash
    download.wanted_files = json.dumps(wanted)
    download.wanted_at = utcnow()
    download.source_removed_at = None
    download.prepared_at = None
    download.prepare_error = None
    download.reaped_at = None
    download.state = DownloadState.downloading.value
    session.commit()
    record_event(
        session, "downloads", f"fetching more of {torrent.name}",
        f"{len(wanted)} file(s); {len(held)} kept from before",
    )
    return download


async def publish(session: Session, download: Download, name: str,
                  wanted: list[str] | None = None) -> str:
    try:
        media = download.torrent.media if download.torrent else None
        root = download.content_path or download.save_path or ""
        only = (
            {os.path.normpath(os.path.join(root, p)) for p in wanted}
            if wanted is not None and os.path.isdir(root) else None
        )
        # In a thread: a copy of many GB on the event loop froze every request.
        source, dest_dir, is_tv = library.plan(download, media)
        published = await asyncio.to_thread(
            library.publish_files, source, dest_dir, is_tv, only, download.id
        )
        download.library_path = published.path
        download.linked_at = utcnow()
        download.state = DownloadState.linked.value
        # Kept before anything is awaited, so a concurrent delete knows the library has it.
        session.commit()
        if media and media.media_type == "tv":
            try:
                from . import shows

                await shows.attach_files(session, download)
                await shows.sync_show(session, media)
            except Exception as exc:  # noqa: BLE001
                log.warning("could not map episodes for %s: %s", name, exc)
        preparation().start(download.id)

        if published.degraded:
            record_event(
                session, "library",
                f"published {name} by COPYING, not hardlinking",
                f"{published.copied} file(s) copied, which consumed real "
                f"disk space. The download directory and the library must "
                f"share one mount inside the container.",
                level="warn",
            )
            return "copied"
        record_event(
            session, "library",
            f"published {name}",
            f"{published.path} ({published.linked} hardlinked)",
        )
        return "published"
    except library.LibraryError as exc:
        download.error = f"publish failed: {exc}"
        record_event(
            session, "library", f"publish failed for {name}",
            str(exc), level="error",
        )
        return "error"


async def sync_active(session: Session) -> dict:
    summary = {"tracked": 0, "updated": 0, "completed": 0, "published": 0, "errors": 0}
    if settings.qbit_configured:
        await _sync_torrents(session, summary)

    from . import linkfetch

    summary["published"] += await linkfetch.publish_stragglers(session)

    await _housekeeping(session, summary)
    return summary


async def _sync_torrents(session: Session, summary: dict) -> None:
    tracked = list(
        session.scalars(
            select(Download).where(
                Download.info_hash.is_not(None),
                Download.reaped_at.is_(None),
                Download.state.notin_([DownloadState.removed.value]),
                Download.source_removed_at.is_(None),
            )
        )
    )
    if not tracked:
        return
    summary["tracked"] = len(tracked)

    by_hash = {d.info_hash.lower(): d for d in tracked if d.info_hash}

    try:
        async with QbitClient() as client:
            statuses = await client.info(list(by_hash.keys()))
    except QbitError as exc:
        record_event(session, "downloads", "qBittorrent unreachable", str(exc), level="warn")
        summary["errors"] += 1
        return

    seen: set[str] = set()

    for status in statuses:
        download = by_hash.get(status.hash)
        if download is None:
            continue
        seen.add(status.hash)

        download.progress = status.progress
        download.dl_speed = status.dlspeed
        download.up_speed = status.upspeed
        download.eta_seconds = status.eta
        download.downloaded_bytes = status.downloaded
        download.uploaded_bytes = status.uploaded
        download.ratio = status.ratio
        download.seeding_seconds = status.seeding_time
        download.save_path = status.save_path
        download.content_path = status.content_path or status.save_path

        new_state = status.normalised_state()
        healthy = new_state != "error"

        if not healthy:
            download.state = DownloadState.error.value
            download.error = f"qBittorrent state: {status.state}"
            summary["errors"] += 1
        else:
            download.error = None

            if status.is_complete:
                if download.completed_at is None:
                    download.completed_at = utcnow()
                    summary["completed"] += 1
                if download.library_path:
                    download.state = DownloadState.linked.value
                elif download.state != DownloadState.linked.value:
                    download.state = DownloadState.completed.value
            else:
                download.state = (
                    DownloadState.paused.value
                    if new_state == "paused"
                    else DownloadState.downloading.value
                )

        summary["updated"] += 1

        needs_publish = healthy and status.is_complete and (
            not download.library_path
            or (download.wanted_at is not None and download.linked_at is not None
                and download.wanted_at > download.linked_at)
        )
        wanted = wanted_paths(download)
        if needs_publish and wanted is not None:
            try:
                async with QbitClient() as files_client:
                    if not await _wanted_complete(files_client, download):
                        needs_publish = False
                        download.state = DownloadState.downloading.value
            except QbitError:
                needs_publish = False
        if needs_publish:
            outcome = await publish(session, download, status.name, wanted)
            if outcome == "error":
                summary["errors"] += 1
            else:
                summary["published"] += 1
                if outcome == "copied":
                    summary["copied"] = summary.get("copied", 0) + 1

    # Removed outside VibeStream, unless just added: qBittorrent can take a
    # moment to list it.
    settled = utcnow() - timedelta(seconds=JUST_ADDED_SECONDS)
    for info_hash, download in by_hash.items():
        recent = any(t is not None and t > settled
                     for t in (download.requested_at, download.added_at))
        if info_hash not in seen and not recent \
                and download.state != DownloadState.requested.value:
            download.state = DownloadState.removed.value
            download.reaped_at = download.reaped_at or utcnow()
            record_event(
                session, "downloads",
                f"torrent vanished from qBittorrent: {info_hash}",
                "marked removed", level="warn",
            )

    session.commit()



async def _housekeeping(session: Session, summary: dict) -> None:
    if settings.tmdb_configured:
        from . import shows

        try:
            await shows.backfill(session)
        except Exception as exc:  # noqa: BLE001
            log.warning("episode backfill failed: %s", exc)

    # A restart mid-remux leaves a finished download with no marker, and nothing
    # else would ever start it again.
    preparation().ensure_pending(session)

    global _sources_checked
    if time.monotonic() - _sources_checked > SOURCES_EVERY_SECONDS:
        _sources_checked = time.monotonic()
        from . import sources

        try:
            await sources.ensure_extras(session)
            if settings.sources_auto_remove:
                removed = await sources.remove_finished(session)
                summary["sources_removed"] = removed["removed"]
        except Exception as exc:  # noqa: BLE001
            log.warning("source housekeeping failed: %s", exc)


SOURCES_EVERY_SECONDS = 600
_sources_checked = 0.0
JUST_ADDED_SECONDS = 60


def _forget_artefacts(path: str | None) -> None:
    from . import hls, live, mediainfo, subtitles, trickplay

    if not path:
        return
    subtitles.clear_for(path, mediainfo.cached_info(path))
    hls.clear_for(path)
    mediainfo.clear_probe(path)
    live.clear_init(path)
    trickplay.clear_for(path)


def artefact_paths(session: Session, download: Download) -> list[str]:
    """Taken before anything is unlinked: the paths are found by looking at the disk."""
    from . import streaming

    paths = [path for _eid, path in preparation().targets_for(session, download) if path]
    paths += [streaming.resolve_path(download), download.play_path]
    return list(dict.fromkeys(p for p in paths if p))


def unpublish(session: Session, download: Download) -> None:
    """A season folder is shared, so it is never removed while another download uses it."""
    if not download.library_path:
        return
    files = list(session.scalars(
        select(Episode.file_path).where(Episode.download_id == download.id,
                                        Episode.file_path.is_not(None))
    ))
    files += library.published_files(download)
    if files:
        library.unpublish_files(list(dict.fromkeys(files)), download.library_path)
    else:
        shared = session.scalar(
            select(Download.id).where(
                Download.library_path == download.library_path, Download.id != download.id,
                Download.reaped_at.is_(None), Download.state != DownloadState.removed.value,
            ).limit(1)
        )
        if shared is None:
            library.unpublish(download.library_path)
        else:
            library.unpublish_files([], download.library_path)
    download.library_path = None


def retire(session: Session, download: Download, paths: list[str]) -> None:
    from . import shows

    for path in paths:
        _forget_artefacts(path)
    shows.detach_files(session, download.id)
    download.state = DownloadState.removed.value
    download.reaped_at = utcnow()
    download.library_path = None
    download.prepared_at = None
    download.prepare_error = None
    download.source_removed_at = None
    download.play_path = None


async def cancel_download(session: Session, download_id: int, delete_files: bool = True) -> None:
    download = session.get(Download, download_id)
    if download is None:
        raise DownloadError(f"unknown download {download_id}")

    paths = artefact_paths(session, download)

    unpublish(session, download)

    if download.info_hash:
        await _drop_torrent(session, download.info_hash, download.id, delete_files)
    if download.link:
        from . import linkfetch, torbox

        linkfetch.stop(download.id)
        if delete_files:
            linkfetch.remove_files(download.id)
        if (on_torbox := torbox.torrent_id(download.link)) is not None:
            await torbox.delete(on_torbox)

    retire(session, download, paths)
    session.commit()
    record_event(
        session, "downloads",
        f"cancelled download {download_id}",
        download.torrent.name if download.torrent else None,
        level="warn",
    )
    session.commit()


def _keep_shared_pieces(path: str, file, piece_length: int, total_length: int) -> None:
    """Sparse-empty a pack's file but keep pieces shared with neighbours, which are still seeded."""
    start, end = file.offset, file.offset + file.length
    keep: list[tuple[int, int]] = []
    if piece_length > 0:
        if start % piece_length:
            keep.append((0, min(file.length, piece_length - start % piece_length)))
        if end % piece_length and end < total_length:
            keep.append((max(0, (end // piece_length) * piece_length - start), file.length))

    partial = path + ".partial"
    mode = os.stat(path).st_mode
    with open(path, "rb") as source, open(partial, "wb") as target:
        target.truncate(file.length)
        for begin, finish in keep:
            source.seek(begin)
            target.seek(begin)
            remaining = finish - begin
            while remaining > 0:
                chunk = source.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                target.write(chunk)
                remaining -= len(chunk)
    os.chmod(partial, mode)
    os.replace(partial, path)


def _unlink_from_library(path: str) -> None:
    root = os.path.abspath(settings.shows_dir)
    target = os.path.abspath(path)
    if not target.startswith(root + os.sep):
        raise DownloadError(f"refusing to delete outside the library: {target}")
    folder = os.path.dirname(target)
    stem = os.path.splitext(os.path.basename(target))[0]
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name == os.path.basename(target) or (
            name.startswith(stem + ".") and name.lower().endswith(library.SIDECAR_EXT)
        ):
            try:
                os.remove(os.path.join(folder, name))
            except OSError as exc:
                log.warning("could not remove %s: %s", name, exc)


async def remove_episode(session: Session, download_id: int, episode_id: int) -> Download:
    from . import shows

    download = session.get(Download, download_id)
    if download is None or download.state == DownloadState.removed.value:
        raise DownloadError(f"unknown download {download_id}")
    torrent = download.torrent
    episode = session.get(Episode, episode_id)
    if torrent is None or episode is None or episode.media_id != torrent.media_id:
        raise DownloadError("that episode is not part of this download")

    if torrent.episode is not None:
        if episode.download_id != download.id and (
            torrent.season != episode.season_number or torrent.episode != episode.number
        ):
            raise DownloadError("that episode is not part of this download")
        await cancel_download(session, download.id)
        return download

    if episode.source_removed_at is not None and episode.download_id == download.id:
        _forget_artefacts(episode.file_path)
        episode.download_id = None
        episode.file_path = None
        episode.file_size = None
        episode.prepared_at = None
        episode.prepare_error = None
        episode.source_removed_at = None
        session.commit()
        others = session.scalar(
            select(Episode.id).where(Episode.download_id == download.id).limit(1)
        )
        if others is None:
            await cancel_download(session, download.id)
        record_event(
            session, "downloads",
            f"removed S{episode.season_number}E{episode.number} of {torrent.name}",
            "its source was already gone", level="warn",
        )
        session.commit()
        return download

    meta = cached_meta(torrent.id) or parse_torrent(await fetch_torrent_bytes(torrent.id))
    path = await episode_file(session, torrent, meta, episode)
    if path is None:
        raise DownloadError(
            f"S{episode.season_number}E{episode.number} is not in this season pack"
        )

    videos = shows.pack_video_paths(meta.files)
    current = wanted_paths(download)
    remaining = [p for p in (current if current is not None else videos) if p != path]
    if not any(p in videos for p in remaining):
        await cancel_download(session, download.id)
        return download

    if episode.download_id == download.id and episode.file_path:
        _forget_artefacts(episode.file_path)
        _unlink_from_library(episode.file_path)
    if episode.download_id == download.id:
        episode.download_id = None
        episode.file_path = None
        episode.file_size = None
        episode.prepared_at = None
        episode.prepare_error = None

    download.wanted_files = json.dumps(remaining)
    if download.primary_file == path:
        biggest = max(
            (f for f in meta.files if f.path in remaining), key=lambda f: f.length, default=None
        )
        if biggest is not None:
            download.primary_file = biggest.path
            download.primary_file_size = biggest.length
            download.primary_file_index = meta.files.index(biggest)
    session.commit()

    freed = False
    try:
        async with QbitClient() as client:
            await _apply_wanted(client, download.info_hash, remaining)
            entry = next(
                (f for f in await client.files(download.info_hash)
                 if _matches(f.get("name", ""), {path})),
                None,
            )
            on_disk = None
            if entry is not None and float(entry.get("progress", 0)) > 0 and download.save_path:
                on_disk = os.path.join(download.save_path, entry["name"])
            if on_disk and os.path.isfile(on_disk):
                piece = next(f for f in meta.files if f.path == path)
                await asyncio.to_thread(
                    _keep_shared_pieces, on_disk, piece, meta.piece_length, meta.total_length
                )
                await client.recheck(download.info_hash)
                freed = True
    except (QbitError, OSError) as exc:
        log.warning("could not give back the space of %s: %s", path, exc)

    record_event(
        session, "downloads",
        f"removed S{episode.season_number}E{episode.number} of {torrent.name}",
        f"{len(remaining)} file(s) kept" + ("" if freed else ", space not reclaimed"),
        level="warn",
    )
    session.commit()
    return download
