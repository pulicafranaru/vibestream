"""Delete watched titles after a grace period. Manual only.

All must hold: everything watched, last play older than REAPER_GRACE_DAYS, the
seeding obligation met (REAPER_MIN_SEED_HOURS or REAPER_MIN_SEED_RATIO), and
not pinned with `keep`. Disk pressure can override only the grace period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import record_event
from ..models import (
    Download,
    DownloadState,
    Episode,
    EpisodeProgress,
    WatchProgress,
    utcnow,
)
from . import library
from .qbit import QbitClient

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    download: Download
    reason: str
    bytes_freed: int
    last_played: object | None = None


@dataclass
class ReapReport:
    considered: int = 0
    reaped: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    dry_run: bool = False
    free_before: int = 0
    free_after: int = 0


def _seeding_satisfied(download: Download) -> tuple[bool, str]:
    if download.link:
        return True, "fetched from a debrid link, so nothing to seed"
    min_seconds = settings.reaper_min_seed_hours * 3600
    if settings.reaper_min_seed_ratio > 0 and download.ratio >= settings.reaper_min_seed_ratio:
        return True, f"ratio {download.ratio:.2f} >= {settings.reaper_min_seed_ratio}"
    if min_seconds > 0 and download.seeding_seconds >= min_seconds:
        hours = download.seeding_seconds / 3600
        return True, f"seeded {hours:.1f}h >= {settings.reaper_min_seed_hours}h"
    if min_seconds <= 0 and settings.reaper_min_seed_ratio <= 0:
        return True, "no seeding requirement configured"
    return False, (
        f"seeded {download.seeding_seconds / 3600:.1f}h of "
        f"{settings.reaper_min_seed_hours}h, ratio {download.ratio:.2f} of "
        f"{settings.reaper_min_seed_ratio}"
    )


def seeding_obligation(download: Download) -> dict:
    met, detail = _seeding_satisfied(download)
    return {
        "met": met,
        "detail": detail,
        "hours": round((download.seeding_seconds or 0) / 3600, 1),
        "min_hours": settings.reaper_min_seed_hours,
        "ratio": round(download.ratio or 0.0, 2),
        "min_ratio": settings.reaper_min_seed_ratio,
    }


def _watch_verdict(session: Session, download: Download) -> tuple[bool, object | None, str]:
    episodes = list(session.scalars(
        select(Episode.id).where(Episode.download_id == download.id)
    ))
    if episodes:
        finished: dict[int, object] = {}
        for row in session.scalars(
            select(EpisodeProgress).where(
                EpisodeProgress.episode_id.in_(episodes),
                EpisodeProgress.finished_at.is_not(None),
            )
        ):
            if row.episode_id not in finished or row.finished_at > finished[row.episode_id]:
                finished[row.episode_id] = row.finished_at
        unwatched = [e for e in episodes if e not in finished]
        if unwatched:
            return False, None, f"{len(unwatched)} of {len(episodes)} episodes still unwatched"
        return True, max(finished.values()), f"all {len(episodes)} episode(s) watched"

    dates = [
        row.finished_at
        for row in session.scalars(
            select(WatchProgress).where(
                WatchProgress.download_id == download.id,
                WatchProgress.finished_at.is_not(None),
            )
        )
    ]
    if not dates:
        return False, None, "not watched to the end yet"
    return True, max(dates), "watched"


def find_candidates(session: Session, ignore_grace: bool = False) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    skipped: list[str] = []

    live = session.scalars(
        select(Download).where(
            Download.reaped_at.is_(None),
            Download.state.in_(
                [
                    DownloadState.completed.value,
                    DownloadState.seeding.value,
                    DownloadState.linked.value,
                ]
            ),
        )
    )

    cutoff = utcnow() - timedelta(days=settings.reaper_grace_days)

    for download in live:
        label = download.torrent.name if download.torrent else f"download {download.id}"

        if download.keep:
            skipped.append(f"{label}: pinned with keep")
            continue

        watched, last_played, why = _watch_verdict(session, download)
        if not watched:
            skipped.append(f"{label}: {why}")
            continue

        within_grace = last_played and last_played > cutoff
        if within_grace and not ignore_grace:
            remaining = (last_played - cutoff).days
            skipped.append(
                f"{label}: watched recently, {remaining}d of grace remaining"
            )
            continue

        seeded, seed_why = _seeding_satisfied(download)
        if not seeded:
            # Never overridden, not even under disk pressure.
            skipped.append(f"{label}: seeding obligation not met ({seed_why})")
            continue

        reason = (
            "disk pressure, grace period overridden"
            if within_grace
            else f"watched, grace period elapsed ({seed_why})"
        )
        candidates.append(
            Candidate(
                download=download,
                reason=reason,
                bytes_freed=download.downloaded_bytes or 0,
                last_played=last_played,
            )
        )

    candidates.sort(key=lambda c: (c.last_played is None, c.last_played))
    return candidates, skipped


async def run_reaper(session: Session, dry_run: bool | None = None) -> ReapReport:
    dry = (not settings.reaper_enabled) if dry_run is None else dry_run
    report = ReapReport(dry_run=dry)
    report.free_before = library.free_bytes()

    under_pressure = report.free_before < settings.reaper_min_free_gb * (1024 ** 3)
    candidates, skipped = find_candidates(session, ignore_grace=under_pressure)

    report.considered = len(candidates) + len(skipped)
    report.skipped = skipped

    if under_pressure:
        record_event(
            session,
            "reaper",
            "disk pressure, grace period relaxed",
            f"free={report.free_before / 1024 ** 3:.1f}GB "
            f"threshold={settings.reaper_min_free_gb}GB",
            level="warn",
        )

    if not candidates:
        report.free_after = report.free_before
        record_event(
            session, "reaper",
            f"nothing to reap ({len(skipped)} held back)",
            "; ".join(skipped[:10]) or None,
        )
        return report

    client: QbitClient | None = None
    if not dry:
        client = QbitClient()

    try:
        for candidate in candidates:
            download = candidate.download
            label = download.torrent.name if download.torrent else f"download {download.id}"

            if dry:
                report.reaped.append(f"[dry run] {label}: {candidate.reason}")
                report.bytes_freed += candidate.bytes_freed
                continue

            try:
                from . import downloads

                paths = downloads.artefact_paths(session, download)
                # Library first: if this fails, the torrent data is still intact.
                downloads.unpublish(session, download)

                if download.info_hash and client:
                    await client.delete(download.info_hash, delete_files=True)
                if download.link:
                    from . import linkfetch

                    linkfetch.remove_files(download.id)

                downloads.retire(session, download, paths)
                session.commit()

                report.reaped.append(f"{label}: {candidate.reason}")
                report.bytes_freed += candidate.bytes_freed
                record_event(
                    session, "reaper", f"removed {label}", candidate.reason, level="warn"
                )
            except Exception as exc:
                session.rollback()
                message = f"{label}: {exc}"
                report.errors.append(message)
                record_event(session, "reaper", "removal failed", message, level="error")
                log.exception("reaper failed on download %s", download.id)
    finally:
        if client:
            await client.close()

    session.commit()
    report.free_after = library.free_bytes()
    record_event(
        session,
        "reaper",
        f"{'would remove' if dry else 'removed'} {len(report.reaped)} title(s), "
        f"{report.bytes_freed / 1024 ** 3:.1f}GB",
        f"errors={len(report.errors)} held_back={len(report.skipped)}",
    )
    return report
