"""Publishing finished downloads into the library by hardlink, falling back to a copy."""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
from dataclasses import dataclass

from ..config import settings
from ..models import Download, Media
from ..titles import library_folder_name

log = logging.getLogger(__name__)

VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".wmv", ".mpg")
SIDECAR_EXT = (".srt", ".sub", ".idx", ".ass", ".ssa", ".nfo")
SKIP_PATTERNS = re.compile(r"(sample|trailer|proof|screens?)", re.I)


class LibraryError(RuntimeError):
    pass


def _safe_join(root: str, name: str) -> str:
    candidate = os.path.abspath(os.path.join(root, name))
    root_abs = os.path.abspath(root)
    if candidate != root_abs and not candidate.startswith(root_abs + os.sep):
        raise LibraryError(f"refusing to write outside the library root: {candidate}")
    return candidate


def _link_or_copy(src: str, dst: str) -> str:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return "existing"
    try:
        os.link(src, dst)
        return "linked"
    except OSError as exc:
        if exc.errno in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.EMLINK, errno.ENOTSUP):
            log.warning("hardlink failed (%s), copying instead: %s", exc.strerror, src)
            shutil.copy2(src, dst)
            return "copied"
        raise


def _interesting_files(root: str) -> list[str]:
    if os.path.isfile(root):
        return [root]
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            lowered = name.lower()
            if not lowered.endswith(VIDEO_EXT + SIDECAR_EXT):
                continue
            full = os.path.join(dirpath, name)
            if lowered.endswith(VIDEO_EXT):
                # A "sample" that is actually large is the feature, so judge by size.
                if SKIP_PATTERNS.search(name) and os.path.getsize(full) < 300 * 1024 * 1024:
                    continue
            out.append(full)
    return sorted(out)


def target_directory(media: Media | None, download: Download) -> tuple[str, bool]:
    torrent = download.torrent
    is_tv = bool(
        (media and media.media_type == "tv")
        or (torrent and torrent.season is not None)
    )
    title = (media.title if media and media.title else None) or (
        torrent.parsed_title if torrent else None
    ) or (torrent.name if torrent else "Unknown")
    year = (media.year if media else None) or (torrent.parsed_year if torrent else None)

    folder = library_folder_name(title, year)
    if is_tv:
        base = _safe_join(settings.shows_dir, folder)
        season = torrent.season if torrent and torrent.season is not None else 1
        return _safe_join(base, f"Season {season:02d}"), True
    return _safe_join(settings.movies_dir, folder), False


def _destination(source: str, src: str, dest_dir: str, is_tv: bool) -> str:
    if os.path.isfile(source):
        if is_tv:
            # A single episode keeps its scene name: SxxEyy is what the episode matcher reads.
            return _safe_join(dest_dir, os.path.basename(src))
        return _safe_join(dest_dir, os.path.basename(dest_dir) + os.path.splitext(src)[1])
    return _safe_join(dest_dir, os.path.relpath(src, source))


@dataclass
class PublishResult:
    path: str
    linked: int = 0
    copied: int = 0
    existing: int = 0

    @property
    def degraded(self) -> bool:
        return self.copied > 0


def publish(
    download: Download, media: Media | None = None, only: set[str] | None = None
) -> PublishResult:
    """Idempotent. A copy fallback is reported so the caller can warn: it doubles disk use."""
    source, dest_dir, is_tv = plan(download, media)
    return publish_files(source, dest_dir, is_tv, only, download.id)


def plan(download: Download, media: Media | None = None) -> tuple[str, str, bool]:
    source = download.content_path or download.save_path
    if not source:
        raise LibraryError("download has no content_path yet")
    if not os.path.exists(source):
        raise LibraryError(f"download content is missing on disk: {source}")
    dest_dir, is_tv = target_directory(media, download)
    return source, dest_dir, is_tv


def publish_files(source: str, dest_dir: str, is_tv: bool, only: set[str] | None = None,
                  label: object = "") -> PublishResult:
    files = _interesting_files(source)
    # A file partly here because a piece it shares with a wanted one was
    # fetched must not be linked as if it were whole.
    if only is not None:
        stems = {os.path.splitext(path)[0] for path in only}
        files = [
            f for f in files
            if os.path.normpath(f) in only
            or any(os.path.normpath(f).startswith(stem) for stem in stems)
        ]
    if not files:
        raise LibraryError(f"no video files found under {source}")

    os.makedirs(dest_dir, exist_ok=True)
    result = PublishResult(path=dest_dir)
    for src in files:
        dst = _destination(source, src, dest_dir, is_tv)
        outcome = _link_or_copy(src, dst)
        setattr(result, outcome, getattr(result, outcome) + 1)

    if result.degraded:
        log.warning(
            "published %s to %s but had to COPY %s file(s): hardlinking failed, "
            "so this consumed real disk space. Check that the download directory "
            "and the library share a single mount inside the container.",
            label, dest_dir, result.copied,
        )
    else:
        log.info(
            "published %s file(s) to %s (%s hardlinked)",
            result.linked + result.existing, dest_dir, result.linked,
        )
    return result


def _roots() -> list[str]:
    return [os.path.abspath(settings.movies_dir), os.path.abspath(settings.shows_dir)]


def _inside_library(path: str) -> str:
    target = os.path.abspath(path)
    roots = _roots()
    if not any(target.startswith(root + os.sep) for root in roots):
        raise LibraryError(f"refusing to delete outside the library roots: {target}")
    if target in roots:
        raise LibraryError(f"refusing to delete a library root: {target}")
    return target


def _same_bytes(a: str, b: str) -> bool:
    try:
        if os.path.samefile(a, b):
            return True
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)


def published_files(download: Download) -> list[str]:
    source = download.content_path or download.save_path
    dest_dir = download.library_path
    if not source or not dest_dir or not os.path.exists(source) or not os.path.isdir(dest_dir):
        return []
    is_tv = os.path.abspath(dest_dir).startswith(os.path.abspath(settings.shows_dir) + os.sep)
    out = []
    for src in _interesting_files(source):
        try:
            dst = _destination(source, src, dest_dir, is_tv)
        except LibraryError:
            continue
        if _same_bytes(src, dst):
            out.append(dst)
    return out


def unpublish_files(files: list[str], library_path: str | None = None) -> int:
    """Remove files and sidecars, then folders left empty. Shared folders stay.
    Returns how many files went.
    """
    removed = 0
    folders: set[str] = set()
    for path in files:
        target = _inside_library(path)
        folder = os.path.dirname(target)
        folders.add(folder)
        names = [os.path.basename(target)]
        if target.lower().endswith(VIDEO_EXT):
            stem = os.path.splitext(os.path.basename(target))[0]
            try:
                names += [n for n in os.listdir(folder) if n.startswith(stem + ".")
                          and n.lower().endswith(SIDECAR_EXT)]
            except OSError:
                pass
        for name in names:
            try:
                os.remove(os.path.join(folder, name))
                removed += 1
            except FileNotFoundError:
                pass
    if library_path:
        folders.add(_inside_library(library_path))
    roots = _roots()
    for folder in sorted(folders, key=len, reverse=True):
        while folder not in roots and any(folder.startswith(r + os.sep) for r in roots):
            try:
                os.rmdir(folder)
            except FileNotFoundError:
                pass
            except OSError:
                break
            folder = os.path.dirname(folder)
    if removed:
        log.info("unpublished %s file(s) from %s", removed, library_path or "the library")
    return removed


def unpublish(library_path: str | None) -> bool:
    if not library_path:
        return False

    target = _inside_library(library_path)
    roots = _roots()
    if not os.path.exists(target):
        return False

    if os.path.isdir(target):
        shutil.rmtree(target)
        parent = os.path.dirname(target)
        if parent not in roots and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
    else:
        os.remove(target)

    log.info("unpublished %s", target)
    return True


def free_bytes(path: str | None = None) -> int:
    stat = os.statvfs(path or settings.movies_dir)
    return stat.f_bavail * stat.f_frsize
