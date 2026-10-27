"""Downloads fetched over HTTPS from a debrid service's link, resumable, the key redacted once done."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event, session_scope
from ..models import Download, DownloadState, utcnow
from ..user_agent import outbound_client

log = logging.getLogger(__name__)

FOLDER = "links"
PARTIAL = "download.part"
PLACEHOLDER_BYTES = 64 * 1024 * 1024
WAIT_SECONDS = 60
MOST_WAIT_SECONDS = 3600
MOST_FAILURES = 5
SAVE_EVERY_SECONDS = 2.0
CHUNK = 1024 * 1024
TORBOX_POLL_SECONDS = 15
# A release TorBox is fetching is given up on after this long without progress.
TORBOX_STALL_SECONDS = 3 * 3600
REPUBLISH_SECONDS = 600

VIDEO_TYPES = {"video/mp4": ".mp4", "video/x-matroska": ".mkv", "video/webm": ".webm",
               "video/x-msvideo": ".avi", "video/quicktime": ".mov"}
VIDEO_EXTS = (".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".wmv")

_running: dict[int, asyncio.Task] = {}
_live: dict[int, dict] = {}
_republished: dict[int, float] = {}


class LinkError(RuntimeError):
    pass


class Placeholder(LinkError):
    """The service has not got it yet, and sent a stand-in."""


class LinkGone(LinkError):
    """The link stopped working; a new one may."""


def folder(download_id: int) -> str:
    return os.path.join(settings.qbit_download_dir, FOLDER, str(download_id))


def redact(link: str) -> str:
    if link.startswith("torbox:"):
        return "torbox:"
    parts = urlsplit(link)
    return f"{parts.scheme}://{parts.netloc}/" if parts.netloc else "redacted"


def running(download_id: int) -> bool:
    return download_id in _running


def start(download_id: int) -> None:
    if download_id in _running:
        return
    task = asyncio.get_running_loop().create_task(_run(download_id))
    _running[download_id] = task

    def done(finished: asyncio.Task) -> None:
        # Only its own entry: a fetch restarted at once has a new task under the same id.
        if _running.get(download_id) is finished:
            _running.pop(download_id, None)
            _live.pop(download_id, None)

    task.add_done_callback(done)


def stop(download_id: int) -> None:
    task = _running.pop(download_id, None)
    _live.pop(download_id, None)
    if task is not None:
        task.cancel()


def remove_files(download_id: int) -> None:
    stop(download_id)
    shutil.rmtree(folder(download_id), ignore_errors=True)


_redacted_old = False


def _redact_finished(session: Session) -> None:
    global _redacted_old
    if _redacted_old:
        return
    _redacted_old = True
    for download in session.scalars(
        select(Download).where(
            Download.link.is_not(None),
            Download.state.notin_([DownloadState.adding.value, DownloadState.downloading.value]),
        )
    ):
        if download.link != redact(download.link):
            download.link = redact(download.link)
    session.commit()


def ensure_running(session: Session) -> int:
    _redact_finished(session)
    started = 0
    for download in session.scalars(
        select(Download).where(
            Download.link.is_not(None),
            Download.reaped_at.is_(None),
            Download.state.in_([DownloadState.adding.value, DownloadState.downloading.value]),
        )
    ):
        if download.id not in _running:
            start(download.id)
            started += 1
    return started


async def publish_stragglers(session: Session) -> int:
    from .downloads import publish

    published = 0
    for download in list(session.scalars(
        select(Download).where(
            Download.link.is_not(None),
            Download.reaped_at.is_(None),
            Download.library_path.is_(None),
            Download.state == DownloadState.completed.value,
        )
    )):
        if download.id in _running or not download.content_path \
                or not os.path.exists(download.content_path):
            continue
        if time.monotonic() - _republished.get(download.id, -REPUBLISH_SECONDS) < REPUBLISH_SECONDS:
            continue
        _republished[download.id] = time.monotonic()
        name = download.torrent.name if download.torrent else f"download {download.id}"
        if await publish(session, download, name) != "error":
            published += 1
        session.commit()
    return published


def status(download: Download):
    from .qbit import TorrentStatus

    if not download.link:
        return None
    live = _live.get(download.id, {})
    size = live.get("size") or download.primary_file_size \
        or (download.torrent.size_bytes if download.torrent else 0) or 0
    done = download.progress >= 1.0
    return TorrentStatus(
        hash="", name=download.primary_file or (download.torrent.name if download.torrent else ""),
        state="uploading" if done else ("downloading" if download.id in _running else "stalledDL"),
        progress=download.progress or 0.0,
        dlspeed=0 if done else int(live.get("speed", 0)),
        upspeed=0, eta=None if done else download.eta_seconds,
        downloaded=download.downloaded_bytes or 0, uploaded=0, ratio=0.0, size=size,
        save_path=download.save_path or "", content_path=download.content_path or "",
        seeding_time=0, completion_on=None,
    )


def _file_name(resp: httpx.Response, fallback: str) -> str:
    """TV keeps this name in the library, where SxxEyy matches it to its episode."""
    name = None
    disposition = resp.headers.get("content-disposition", "")
    if match := re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I):
        name = unquote(match.group(1).strip().strip('"'))
    elif match := re.search(r'filename="?([^";]+)"?', disposition, re.I):
        name = match.group(1).strip()
    if not name:
        name = unquote(resp.url.path.rsplit("/", 1)[-1])
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    if not name.lower().endswith(VIDEO_EXTS) or name == PARTIAL:
        kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        stem = re.sub(r"[^\w.\-() \[\]]+", " ", fallback).strip() or "video"
        name = stem + VIDEO_TYPES.get(kind, ".mkv")
    return name[:200]


def _write(download_id: int, fields: dict) -> None:
    with session_scope() as s:
        download = s.get(Download, download_id)
        if download is not None:
            for key, value in fields.items():
                setattr(download, key, value)


async def _save(download_id: int, **fields) -> None:
    """Off the event loop: SQLite may be busy with a writer for seconds."""
    try:
        await asyncio.to_thread(_write, download_id, fields)
    except Exception as exc:  # noqa: BLE001 - progress is shown, not relied on
        log.warning("could not save the progress of download %s: %s", download_id, exc)


def _whole_file(where: str) -> str | None:
    try:
        names = [n for n in os.listdir(where) if n != PARTIAL]
    except OSError:
        return None
    for name in names:
        path = os.path.join(where, name)
        if name.lower().endswith(VIDEO_EXTS) and os.path.getsize(path) >= PLACEHOLDER_BYTES:
            return path
    return None


async def _fetch(download_id: int, url: str, fallback: str) -> tuple[str, int]:
    where = folder(download_id)
    os.makedirs(where, exist_ok=True)
    partial = os.path.join(where, PARTIAL)
    if not os.path.exists(partial) and (whole := _whole_file(where)):
        return whole, os.path.getsize(whole)
    offset = os.path.getsize(partial) if os.path.exists(partial) else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with outbound_client(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code in (401, 403, 404, 410):
                raise LinkGone(f"the link answered HTTP {resp.status_code}")
            if resp.status_code == 416 and offset:
                # The link may now lead to a shorter stand-in, so the file is whole only
                # if the end is where this copy stops.
                match = re.search(r"/\s*(\d+)\s*$", resp.headers.get("content-range", ""))
                if match and int(match.group(1)) == offset:
                    return _finish(where, partial, _file_name(resp, fallback)), offset
                os.remove(partial)
                raise LinkError("the link no longer leads to the file being fetched")
            if resp.status_code not in (200, 206):
                raise LinkError(f"the link answered HTTP {resp.status_code}")
            if resp.status_code == 200 and offset:
                offset = 0
            length = resp.headers.get("content-length")
            total = offset + int(length) if length and length.isdigit() else None
            kind = resp.headers.get("content-type", "").lower()
            if (total is not None and total < PLACEHOLDER_BYTES) or kind.startswith(
                ("text/", "application/json")
            ):
                raise Placeholder("the debrid service is still fetching it")
            name = _file_name(resp, fallback)
            _live[download_id] = {"size": total or 0, "speed": 0}
            await _save(download_id, primary_file_size=total, error=None,
                        state=DownloadState.downloading.value)

            done = offset
            window_bytes, window_start = 0, time.monotonic()
            last_save = 0.0
            with open(partial, "ab" if offset else "wb") as out:
                async for chunk in resp.aiter_bytes(CHUNK):
                    out.write(chunk)
                    done += len(chunk)
                    window_bytes += len(chunk)
                    now = time.monotonic()
                    if now - last_save >= SAVE_EVERY_SECONDS:
                        speed = window_bytes / max(now - window_start, 0.001)
                        window_bytes, window_start, last_save = 0, now, now
                        _live[download_id] = {"size": total or 0, "speed": speed}
                        await _save(
                            download_id,
                            downloaded_bytes=done,
                            progress=min(done / total, 0.999) if total else 0.0,
                            dl_speed=int(speed),
                            eta_seconds=int((total - done) / speed) if total and speed else None,
                        )
            if total is not None and done < total:
                raise LinkError(f"the connection ended at {done} of {total} bytes")
            return _finish(where, partial, name), done


def _finish(where: str, partial: str, name: str) -> str:
    final = os.path.join(where, name)
    os.replace(partial, final)
    return final


def _on_disk(download_id: int) -> int:
    partial = os.path.join(folder(download_id), PARTIAL)
    return os.path.getsize(partial) if os.path.exists(partial) else 0


async def _torbox_ready(download_id: int, torrent_id: int, wanted: str | None,
                        fallback: str) -> tuple[int, str] | None:
    """Waits for TorBox to hold it whole. Returns (file id, a link to it),
    or None once the download has been failed."""
    from . import torbox

    best, since = -1.0, time.monotonic()
    errors = 0
    while True:
        try:
            info = await torbox.state(torrent_id)
            errors = 0
        except (torbox.TorboxError, httpx.HTTPError) as exc:
            errors += 1
            if errors >= MOST_FAILURES:
                await _fail(download_id, fallback, f"TorBox: {exc}")
                return None
            await asyncio.sleep(TORBOX_POLL_SECONDS)
            continue
        status = str(info.get("download_state") or "").lower()
        if info.get("download_finished") and info.get("download_present", True):
            chosen = torbox.pick_file(info.get("files") or [], wanted)
            if chosen is None:
                await _fail(download_id, fallback, "TorBox holds it, but with no video in it.")
                return None
            try:
                return chosen["id"], await torbox.link(torrent_id, chosen["id"])
            except (torbox.TorboxError, httpx.HTTPError) as exc:
                await _fail(download_id, fallback, f"TorBox gave no link: {exc}")
                return None
        if "error" in status or "failed" in status:
            await _fail(download_id, fallback, f"TorBox could not fetch it ({status}).")
            return None
        progress = float(info.get("progress") or 0.0)
        if progress > best:
            best, since = progress, time.monotonic()
        elif time.monotonic() - since > TORBOX_STALL_SECONDS:
            await _fail(download_id, fallback, "TorBox found nobody sharing it for three hours.")
            return None
        speed = int(info.get("download_speed") or 0)
        _live[download_id] = {"size": int(info.get("size") or 0), "speed": speed}
        await _save(download_id, progress=min(progress, 0.999), dl_speed=speed, error=None,
                    eta_seconds=int(info["eta"]) if info.get("eta") else None,
                    state=DownloadState.downloading.value)
        await asyncio.sleep(TORBOX_POLL_SECONDS)


async def _run(download_id: int) -> None:
    from . import addons, torbox
    from .downloads import publish

    with session_scope() as s:
        download = s.get(Download, download_id)
        if download is None or not download.link:
            return
        url = download.link
        torrent = download.torrent
        fallback = torrent.name if torrent else f"download {download_id}"
        wanted = torrent.file_name if torrent else None

    on_torbox = torbox.torrent_id(url)
    file_id = None
    if on_torbox is not None:
        ready = await _torbox_ready(download_id, on_torbox, wanted, fallback)
        if ready is None:
            return
        file_id, url = ready

    asked_again = False
    waiting_since: float | None = None
    failures = 0
    while True:
        before = _on_disk(download_id)
        try:
            path, size = await _fetch(download_id, url, fallback)
            break
        except asyncio.CancelledError:
            raise
        except Placeholder as exc:
            waiting_since = waiting_since or time.monotonic()
            if time.monotonic() - waiting_since > MOST_WAIT_SECONDS:
                return await _fail(download_id, fallback, "The debrid service did not have it "
                                   "ready within an hour.")
            await _save(download_id, error=None, dl_speed=0, state=DownloadState.downloading.value)
            log.info("%s: %s", fallback, exc)
            await asyncio.sleep(WAIT_SECONDS)
        except LinkGone as exc:
            if asked_again:
                return await _fail(download_id, fallback, f"The debrid link stopped working: {exc}.")
            asked_again = True
            fresh = None
            if on_torbox is not None:
                try:
                    url = await torbox.link(on_torbox, file_id)
                    continue
                except (torbox.TorboxError, httpx.HTTPError) as error:
                    return await _fail(download_id, fallback, f"TorBox gave no new link: {error}")
            with session_scope() as s:
                download = s.get(Download, download_id)
                if download is not None and download.torrent is not None:
                    try:
                        fresh = await addons.link_for(download.torrent)
                    except Exception as error:  # noqa: BLE001
                        log.warning("could not ask for a new link: %s", error)
                if fresh:
                    download.link = fresh
            if not fresh:
                return await _fail(download_id, fallback, f"The debrid link stopped working: {exc}.")
            url = fresh
        except (LinkError, httpx.HTTPError, OSError) as exc:
            # A drop after more of the file came is a fresh start, not one more strike.
            if _on_disk(download_id) > before:
                failures = 0
            failures += 1
            if failures >= MOST_FAILURES:
                return await _fail(download_id, fallback, f"Fetching the link failed: {exc}")
            log.warning("link fetch of %s failed (%s), trying again", fallback, exc)
            await asyncio.sleep(min(10 * failures, 60))

    # Recorded as whole first: from here a failure costs a publish, never the fetch.
    with session_scope() as s:
        download = s.get(Download, download_id)
        if download is None or download.reaped_at is not None:
            return
        download.save_path = folder(download_id)
        download.content_path = path
        download.primary_file = os.path.basename(path)
        download.primary_file_size = size
        download.primary_file_index = 0
        download.downloaded_bytes = size
        download.progress = 1.0
        download.dl_speed = 0
        download.eta_seconds = 0
        download.error = None
        download.link = redact(download.link or url)
        download.completed_at = download.completed_at or utcnow()
        download.state = DownloadState.completed.value
        record_event(s, "downloads", f"fetched {fallback} from a debrid link",
                     f"{size / 1024 ** 3:.2f}GiB")

    if on_torbox is not None:
        await torbox.delete(on_torbox)
    _republished[download_id] = time.monotonic()
    try:
        with session_scope() as s:
            download = s.get(Download, download_id)
            if download is not None and download.reaped_at is None:
                await publish(s, download, fallback)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - publish_stragglers tries again
        log.exception("could not publish %s; it is tried again later", fallback)


async def _fail(download_id: int, name: str, message: str) -> None:
    from . import torbox

    def write() -> int | None:
        with session_scope() as s:
            download = s.get(Download, download_id)
            if download is None:
                return None
            on_torbox = torbox.torrent_id(download.link)
            download.state = DownloadState.error.value
            download.error = message
            download.dl_speed = 0
            if download.link:
                download.link = redact(download.link)
            record_event(s, "downloads", f"could not fetch {name}", message, level="error")
            return on_torbox

    try:
        on_torbox = await asyncio.to_thread(write)
    except Exception:  # noqa: BLE001
        log.exception("could not record that %s failed", name)
        return
    if on_torbox is not None:
        await torbox.delete(on_torbox)
