"""Admin API. Mutating requests must send X-VibeStream-Admin: 1, which a cross-site form cannot."""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import Download, Event, Media, Profile, Torrent, utcnow
from ..services import adminauth, overrides

router = APIRouter(prefix="/api/admin", tags=["admin"])

STARTED = time.time()

HEADER = "x-vibestream-admin"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _address(request: Request) -> str:
    return request.client.host if request.client else "?"


def _wants_header(request: Request) -> None:
    if request.method in UNSAFE and request.headers.get(HEADER) != "1":
        raise HTTPException(403, "missing the admin header")


def require_admin(request: Request) -> str:
    token = request.cookies.get(adminauth.COOKIE)
    if adminauth.session_for(token) is None:
        raise HTTPException(401, "sign in to the admin dashboard")
    _wants_header(request)
    return token


locked = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _refuse(exc: adminauth.AuthError):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    raise HTTPException(exc.status, exc.detail, headers=headers)


def _signed_in(request: Request, response: Response, token: str) -> dict:
    response.set_cookie(
        adminauth.COOKIE, token, max_age=int(adminauth.LIFETIME.total_seconds()),
        httponly=True, samesite="strict", secure=request.url.scheme == "https",
        path="/api/admin",
    )
    return {"ok": True}


@router.get("/about")
def about(request: Request):
    return {
        "version": request.app.version,
        "started_at": STARTED,
        "uptime_seconds": round(time.time() - STARTED),
        "server_time": time.time(),
        "python": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "client_ip": request.client.host if request.client else None,
    }


@locked.get("/version")
async def version():
    """The running version, and the newest release when update_check allows asking."""
    from ..services import updates

    return await updates.status()


@locked.get("/health")
async def health(session: Session = Depends(get_session)):
    result: dict[str, dict] = {}

    if settings.filelist_configured:
        from ..services.filelist import FilelistClient, budget

        ok, detail = await FilelistClient().check_credentials()
        result["filelist"] = {
            "configured": True, "ok": ok, "detail": detail,
            "requests_remaining": budget.remaining(),
            "categories": settings.filelist_categories,
        }
    else:
        result["filelist"] = {"configured": False, "ok": False,
                              "detail": "FILELIST_USERNAME / FILELIST_PASSKEY not set"}

    if settings.addons_configured:
        from ..services import addons

        ok, detail = await addons.check()
        result["addons"] = {"configured": True, "ok": ok, "detail": detail,
                            "names": [addons.label(a) for a in addons.addresses()]}
    else:
        result["addons"] = {"configured": False, "ok": False, "detail": "Switched off"}

    if settings.torbox_configured:
        from ..services import torbox

        ok, detail = await torbox.account()
        result["torbox"] = {"configured": True, "ok": ok, "detail": detail,
                            "names": [f"TorBox {detail}"] if ok else None}

    if settings.tmdb_configured:
        from ..services.tmdb import TMDBClient

        ok, detail = await TMDBClient().check_key()
        result["tmdb"] = {"configured": True, "ok": ok, "detail": detail}
    else:
        result["tmdb"] = {"configured": False, "ok": False, "detail": "TMDB_API_KEY not set"}

    if settings.qbit_configured:
        from ..services.qbit import QbitClient

        client = QbitClient()
        ok, detail = await client.check()
        await client.close()
        result["qbittorrent"] = {"configured": True, "ok": ok, "detail": detail}
    else:
        result["qbittorrent"] = {"configured": False, "ok": False,
                                 "detail": "QBIT_PASSWORD not set"}

    needed = [v for k, v in result.items() if k not in ("filelist", "addons")]
    # TorBox is optional: only one that is set up has to work.
    sources = [result[k] for k in ("filelist", "addons") if result[k]["configured"]]
    return {
        "ok": all(v["ok"] for v in needed) and bool(sources) and all(v["ok"] for v in sources),
        "missing": settings.missing(),
        "integrations": result,
    }


@locked.get("/events")
def events(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=1000),
    source: str | None = None,
    level: str | None = None,
):
    stmt = select(Event).order_by(Event.ts.desc()).limit(limit)
    if source:
        stmt = stmt.where(Event.source == source)
    if level:
        stmt = stmt.where(Event.level == level)
    return [
        {
            "id": e.id, "ts": e.ts.isoformat(), "level": e.level,
            "source": e.source, "message": e.message, "detail": e.detail,
        }
        for e in session.scalars(stmt)
    ]


@locked.post("/sweep")
async def trigger_sweep(session: Session = Depends(get_session)):
    from ..services.filelist import SweepResult, sweep_categories

    result = await sweep_categories(session) if settings.filelist_configured \
        or not settings.addons_configured else SweepResult()
    if settings.addons_configured:
        from ..services import addons

        result.inserted += await addons.discover(session, force=True)
    return {
        "fetched": result.fetched, "inserted": result.inserted,
        "updated": result.updated, "skipped": result.skipped,
        "errors": result.errors,
    }


@locked.post("/enrich")
async def trigger_enrich(
    limit: int = Query(200, ge=1, le=5000), session: Session = Depends(get_session)
):
    from ..services.tmdb import enrich_media_details, enrich_pending

    lookups = await enrich_pending(session, limit=limit)
    details = await enrich_media_details(session, limit=limit)
    return {
        "lookups": {
            "matched": lookups.matched, "notfound": lookups.notfound,
            "failed": lookups.failed,
        },
        "details": {
            "matched": details.matched, "notfound": details.notfound,
            "failed": details.failed,
        },
    }


@locked.post("/reap")
async def trigger_reap(
    dry_run: bool = Query(True, description="report only, delete nothing"),
    session: Session = Depends(get_session),
):
    from ..services.reaper import run_reaper

    report = await run_reaper(session, dry_run=dry_run)
    return {
        "dry_run": report.dry_run,
        "considered": report.considered,
        "reaped": report.reaped,
        "skipped": report.skipped,
        "errors": report.errors,
        "gb_freed": round(report.bytes_freed / 1024 ** 3, 2),
        "free_before_gb": round(report.free_before / 1024 ** 3, 1),
        "free_after_gb": round(report.free_after / 1024 ** 3, 1),
    }


class SetUp(BaseModel):
    code: str
    password: str


class SignIn(BaseModel):
    password: str


class NewPassword(BaseModel):
    current: str
    new: str


@router.get("/auth/state")
def auth_state(request: Request):
    configured = adminauth.configured()
    if not configured:
        adminauth.setup_code()
    return {
        "configured": configured,
        "signed_in": adminauth.session_for(request.cookies.get(adminauth.COOKIE)) is not None,
        "min_password": adminauth.MIN_PASSWORD,
    }


@router.post("/auth/setup")
def auth_setup(body: SetUp, request: Request, response: Response):
    _wants_header(request)
    try:
        token = adminauth.set_up(body.code, body.password, _address(request),
                                 request.headers.get("user-agent", ""))
    except adminauth.AuthError as exc:
        _refuse(exc)
    return _signed_in(request, response, token)


@router.post("/auth/login")
def auth_login(body: SignIn, request: Request, response: Response):
    _wants_header(request)
    try:
        token = adminauth.sign_in(body.password, _address(request),
                                  request.headers.get("user-agent", ""))
    except adminauth.AuthError as exc:
        _refuse(exc)
    return _signed_in(request, response, token)


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    _wants_header(request)
    adminauth.sign_out(request.cookies.get(adminauth.COOKIE))
    response.delete_cookie(adminauth.COOKIE, path="/api/admin")
    return {"ok": True}


@locked.post("/auth/password")
def auth_password(body: NewPassword, request: Request, token: str = Depends(require_admin)):
    try:
        adminauth.change_password(token, body.current, body.new, _address(request))
    except adminauth.AuthError as exc:
        _refuse(exc)
    return {"ok": True}


@locked.get("/auth/sessions")
def auth_sessions(token: str = Depends(require_admin)):
    return {"sessions": adminauth.sessions(token)}


@locked.delete("/auth/sessions/{public_id}")
def auth_end_session(public_id: str, token: str = Depends(require_admin)):
    try:
        adminauth.end_session(public_id, token)
    except adminauth.AuthError as exc:
        _refuse(exc)
    return {"ok": True}


def _disks() -> list[dict]:
    places = [("Movies", settings.movies_dir), ("Shows", settings.shows_dir),
              ("Downloads", settings.qbit_download_dir)]
    disks: dict[int, dict] = {}
    for label, path in places:
        if not path or not os.path.isdir(path):
            continue
        device = os.stat(path).st_dev
        stat = os.statvfs(path)
        entry = disks.setdefault(device, {
            "labels": [], "paths": [],
            "total": stat.f_blocks * stat.f_frsize,
            "free": stat.f_bavail * stat.f_frsize,
        })
        entry["labels"].append(label)
        entry["paths"].append(path)
    return list(disks.values())


@locked.get("/overview")
def overview(request: Request, session: Session = Depends(get_session)):
    from ..services import live
    from ..services.preparation import COMPLETE_STATES
    from . import cast

    playable = (
        select(Media.media_type, func.count(func.distinct(Media.id)))
        .join(Torrent, Torrent.media_id == Media.id)
        .join(Download, Download.torrent_id == Torrent.id)
        .where(Download.state.in_(COMPLETE_STATES))
        .group_by(Media.media_type)
    )
    library = {kind: n for kind, n in session.execute(playable)}
    states = {state: n for state, n in session.execute(
        select(Download.state, func.count()).group_by(Download.state))}
    moving = []
    for d in session.scalars(
        select(Download).where(Download.state.in_(["requested", "adding", "downloading", "paused"]))
        .order_by(Download.requested_at.desc()).limit(8)
    ):
        media = d.torrent.media if d.torrent else None
        moving.append({
            "id": d.id, "state": d.state, "progress": d.progress, "speed": d.dl_speed,
            "eta": d.eta_seconds, "title": media.title if media else (d.torrent.name if d.torrent else ""),
            "poster": media.poster_path if media and hasattr(media, "poster_path") else None,
        })
    since = utcnow() - timedelta(hours=24)
    problems = session.scalar(
        select(func.count()).select_from(Event)
        .where(Event.ts >= since, Event.level.in_(["error", "warn"]))) or 0
    now = time.monotonic()
    return {
        "version": request.app.version,
        "uptime_seconds": round(time.time() - STARTED),
        "engine": settings.playback_engine,
        "library": {"movies": library.get("movie", 0), "shows": library.get("tv", 0)},
        "downloads": states,
        "moving": moving,
        "disks": _disks(),
        "live_streams": len(live._streams),
        "profiles": session.scalar(select(func.count()).select_from(Profile)) or 0,
        "devices_online": sum(1 for d in cast.DEVICES.values() if d.online(now)),
        "problems_24h": problems,
        "missing": settings.missing(),
    }


@locked.get("/config")
def config():
    from ..services.filelist import CATEGORY_NAMES, VIDEO_CATEGORIES

    return {
        "fields": overrides.describe(),
        "categories": [{"id": i, "name": CATEGORY_NAMES.get(i, str(i))} for i in sorted(VIDEO_CATEGORIES)],
    }


@locked.put("/config")
async def config_save(request: Request):
    changes = await request.json()
    if not isinstance(changes, dict) or not changes:
        raise HTTPException(422, "send the settings to change")
    try:
        overrides.save(changes)
    except overrides.Invalid as exc:
        try:
            raise HTTPException(422, {"fields": json.loads(str(exc))}) from None
        except ValueError:
            raise HTTPException(422, str(exc)) from None
    return config()


@locked.delete("/config/{key}")
def config_reset(key: str):
    try:
        overrides.reset(key)
    except overrides.Invalid as exc:
        raise HTTPException(422, str(exc)) from None
    return config()


SETUP_DONE = "setup_done"


def _setup_done(session: Session) -> bool:
    from ..db import kv_get

    if kv_get(session, SETUP_DONE) == "1":
        return True
    return bool(settings.has_source and settings.tmdb_configured
                and session.scalar(select(func.count(Media.id))))


async def _check(name: str) -> dict:
    if name == "filelist":
        if not settings.filelist_configured:
            return {"ok": False, "detail": "Enter the username and the passkey."}
        from ..services.filelist import FilelistClient

        ok, detail = await FilelistClient().check_credentials()
    elif name == "addons":
        if not settings.addons_configured:
            return {"ok": False, "detail": "Enter an addon's address first."}
        from ..services import addons

        ok, detail = await addons.check()
    else:
        if not settings.tmdb_configured:
            return {"ok": False, "detail": "Enter the API key."}
        from ..services.tmdb import TMDBClient

        ok, detail = await TMDBClient().check_key()
    return {"ok": ok, "detail": detail}


@locked.get("/setup")
def setup_state(session: Session = Depends(get_session)):
    import shutil

    try:
        free = shutil.disk_usage(settings.qbit_download_dir).free
    except OSError:
        free = None
    return {
        "done": _setup_done(session),
        "filelist": {"configured": settings.filelist_configured},
        "addons": {"configured": settings.addons_configured},
        "tmdb": {"configured": settings.tmdb_configured},
        "storage": {"path": settings.qbit_download_dir, "free_bytes": free},
    }


@locked.post("/setup/check/{name}")
async def setup_check(name: str):
    if name not in ("filelist", "addons", "tmdb"):
        raise HTTPException(404, "no such step")
    return await _check(name)


@locked.post("/setup/finish")
async def setup_finish(session: Session = Depends(get_session)):
    import asyncio

    from ..db import kv_set, record_event
    from ..scheduler import job_enrich, job_sweep

    kv_set(session, SETUP_DONE, "1")
    record_event(session, "admin", "setup finished")
    session.commit()

    async def first_look() -> None:
        await job_sweep()
        await job_enrich()

    # Not awaited: the sweep and lookups take minutes.
    if settings.has_source:
        asyncio.get_running_loop().create_task(first_look())
    return {"done": True, "looking": settings.has_source}


class DeviceChange(BaseModel):
    name: str | None = None
    # A profile id, or 0 for shared.
    owner_id: int | None = None


@locked.get("/profiles")
def admin_profiles(session: Session = Depends(get_session)):
    from .profiles import serialise

    return {"profiles": [serialise(p) for p in session.scalars(select(Profile).order_by(Profile.id))]}


@locked.delete("/profiles/{profile_id}/pin")
def admin_reset_pin(profile_id: int, session: Session = Depends(get_session)):
    from . import profiles

    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    profile.pin_hash = None
    session.commit()
    profiles._FAILURES.pop(profile_id, None)
    return profiles.serialise(profile)


@locked.get("/devices")
def admin_devices():
    from . import cast

    return {"devices": cast.known_devices()}


@locked.patch("/devices/{device_id}")
def admin_device(device_id: str, body: DeviceChange, session: Session = Depends(get_session)):
    from . import cast

    if body.name is not None:
        cast.rename(device_id, cast.Rename(name=body.name))
    if body.owner_id is not None:
        if body.owner_id and session.get(Profile, body.owner_id) is None:
            raise HTTPException(404, "unknown profile")
        try:
            cast.set_owner(device_id, body.owner_id or None)
        except cast.Personal:
            raise HTTPException(409, "A phone or tablet belongs to whoever uses it.")
    return {"devices": cast.known_devices()}


@locked.delete("/devices/{device_id}")
def admin_forget_device(device_id: str):
    from . import cast

    cast.forget(device_id)
    return {"devices": cast.known_devices()}
