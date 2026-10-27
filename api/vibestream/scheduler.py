from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select

from .config import settings
from .db import record_event, session_scope
from .models import Download, DownloadState, Torrent

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


async def job_sweep() -> None:
    from .services.filelist import sweep_categories

    if settings.filelist_configured:
        try:
            with session_scope() as session:
                await sweep_categories(session)
        except Exception:
            log.exception("filelist sweep failed")
    await job_discover()


async def job_discover() -> None:
    if settings.addons_configured:
        from .services import addons

        try:
            with session_scope() as session:
                await addons.discover(session)
        except Exception:
            log.exception("addon discovery failed")


async def job_enrich() -> None:
    from .models import EnrichStatus, Media
    from .services.tmdb import backfill_facts, enrich_media_details, enrich_pending

    if not settings.tmdb_configured:
        return
    try:
        with session_scope() as session:
            unlinked = session.scalar(
                select(func.count()).select_from(Torrent).where(Torrent.media_id.is_(None))
            )
            if unlinked:
                await enrich_pending(session, limit=200)

            undetailed = session.scalar(
                select(func.count())
                .select_from(Media)
                .where(
                    Media.tmdb_id.is_not(None),
                    Media.enrich_status == EnrichStatus.pending.value,
                )
            )
            if undetailed:
                await enrich_media_details(session, limit=300)

            await backfill_facts(session, limit=300)
    except Exception:
        log.exception("tmdb enrichment failed")

    from .services import coverage

    try:
        with session_scope() as session:
            coverage.refresh(session)
    except Exception:
        log.exception("coverage refresh failed")


async def job_sync() -> None:
    from .services import linkfetch
    from .services.downloads import sync_active

    try:
        with session_scope() as session:
            linkfetch.ensure_running(session)
    except Exception:
        log.exception("could not resume the link downloads")
    try:
        with session_scope() as session:
            active = session.scalar(
                select(func.count())
                .select_from(Download)
                .where(
                    Download.reaped_at.is_(None),
                    Download.state.notin_(
                        [DownloadState.removed.value, DownloadState.error.value]
                    ),
                )
            )
            if not active:
                return
            await sync_active(session)
    except Exception:
        log.exception("download sync failed")


async def job_stills() -> None:
    from .services import stills

    try:
        await stills.backfill()
    except Exception:
        log.exception("still backfill failed")


async def job_keyframes() -> None:
    from .services import live, preparation

    if not live.everywhere():
        return
    try:
        await preparation.index_backlog()
    except Exception:
        log.exception("keyframe backfill failed")


def start() -> None:
    if scheduler.running:
        return

    try:
        sweep_trigger = CronTrigger.from_crontab(settings.filelist_sweep_cron)
    except ValueError:
        log.warning(
            "invalid FILELIST_SWEEP_CRON %r, falling back to every 4 hours",
            settings.filelist_sweep_cron,
        )
        sweep_trigger = IntervalTrigger(hours=4)

    scheduler.add_job(job_sweep, sweep_trigger, id="sweep", max_instances=1,
                      coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(job_discover, IntervalTrigger(hours=1), id="discover",
                      max_instances=1, coalesce=True)
    scheduler.add_job(job_enrich, IntervalTrigger(minutes=5), id="enrich",
                      max_instances=1, coalesce=True)
    scheduler.add_job(job_sync, IntervalTrigger(seconds=10), id="sync",
                      max_instances=1, coalesce=True)
    scheduler.add_job(job_keyframes, IntervalTrigger(minutes=2), id="keyframes",
                      max_instances=1, coalesce=True)
    scheduler.add_job(job_stills, IntervalTrigger(minutes=10), id="stills",
                      max_instances=1, coalesce=True)

    scheduler.start()
    with session_scope() as session:
        record_event(
            session, "scheduler", "started",
            f"sweep={settings.filelist_sweep_cron} missing={settings.missing()}",
        )
    log.info("scheduler started")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
