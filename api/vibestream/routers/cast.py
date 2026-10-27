"""Play on another device. An in-memory switchboard: one API process, so one dict is the whole truth."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from ..db import session_scope
from ..models import DeviceName, DeviceToken, Profile, utcnow

router = APIRouter(prefix="/api/cast", tags=["cast"])

# Longer than the 25 s long poll, so a device mid-request is never missed.
ONLINE_SECONDS = 35
FORGET_SECONDS = 10 * 60
MAX_WAIT = 30
KINDS = {"tv", "phone", "tablet", "web"}
PERSONAL = {"phone", "tablet"}
COMMANDS = {"play", "pause", "resume", "seek", "skip", "stop", "subtitle", "audio", "appearance"}


@dataclass
class Device:
    id: str
    name: str
    kind: str
    profile_id: int | None = None
    last_seen: float = field(default_factory=time.monotonic)
    waiting: int = 0
    playing: dict[str, Any] | None = None
    queue: list[dict[str, Any]] = field(default_factory=list)
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def online(self, now: float) -> bool:
        return self.waiting > 0 or now - self.last_seen < ONLINE_SECONDS

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": display_name(self.id) or self.name,
            "own_name": self.name,
            "kind": self.kind,
            "profile_id": self.profile_id,
            "playing": self.playing,
        }


DEVICES: dict[str, Device] = {}

_NAMES: dict[str, str] | None = None
_OWNERS: dict[str, int] = {}
_KINDS: dict[str, str] = {}
_OWN_NAMES: dict[str, str] = {}
# device id -> (token SHA-256, PIN-verified profile id)
_TOKENS: dict[str, tuple[str, int | None]] = {}
_PENDING: dict[str, str] = {}


def _names() -> dict[str, str]:
    global _NAMES, _OWNERS, _KINDS, _OWN_NAMES
    if _NAMES is None:
        with session_scope() as s:
            rows = list(s.scalars(select(DeviceName)))
            _NAMES = {row.id: row.name for row in rows if row.name}
            _OWNERS = {row.id: row.owner_id for row in rows if row.owner_id is not None}
            _KINDS = {row.id: row.kind or "" for row in rows}
            _OWN_NAMES = {row.id: row.own_name or "" for row in rows}
            _TOKENS.clear()
            _TOKENS.update({t.id: (t.token_hash, t.profile_id) for t in s.scalars(select(DeviceToken))})
    return _NAMES


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _owns_id(device_id: str, token: str | None) -> bool:
    """Whether a request may speak as this device id: once bound to a token, only with it."""
    _names()
    bound = _TOKENS.get(device_id)
    if bound is not None:
        return token is not None and hmac.compare_digest(bound[0], _digest(token))
    if token:
        if len(device_id) > 80 or len(token) > 200:
            return False
        with session_scope() as s:
            s.merge(DeviceToken(id=device_id, token_hash=_digest(token)))
        _TOKENS[device_id] = (_digest(token), None)
        _PENDING.pop(device_id, None)
    return True


def _verified(device_id: str, profile_id: int) -> None:
    if device_id not in _TOKENS:
        return
    with session_scope() as s:
        row = s.get(DeviceToken, device_id)
        if row is not None:
            row.profile_id = profile_id
    _TOKENS[device_id] = (_TOKENS[device_id][0], profile_id)


def _sender_profile(sender_id: str | None, token: str | None) -> int | None:
    if not sender_id or not _owns_id(sender_id, token):
        return None
    return _profile_of(sender_id)


def forget_profile(profile_id: int) -> None:
    _names()
    with session_scope() as s:
        for row in s.scalars(select(DeviceToken).where(DeviceToken.profile_id == profile_id)):
            row.profile_id = None
    for device_id, (digest, verified) in list(_TOKENS.items()):
        if verified == profile_id:
            _TOKENS[device_id] = (digest, None)
    for device in DEVICES.values():
        if device.profile_id == profile_id:
            device.profile_id = None
    for device_id, owner in list(_OWNERS.items()):
        if owner == profile_id:
            _OWNERS.pop(device_id, None)


def kind_of(device_id: str) -> str | None:
    d = DEVICES.get(device_id)
    if d is not None:
        return d.kind
    _names()
    return _KINDS.get(device_id) or None


def _new_row(device_id: str, **fields: Any) -> DeviceName:
    d = DEVICES.get(device_id)
    _KINDS[device_id] = kind_of(device_id) or ""
    _OWN_NAMES[device_id] = d.name if d else ""
    return DeviceName(id=device_id, kind=_KINDS[device_id], own_name=_OWN_NAMES[device_id], **fields)


def _remember(device_id: str, kind: str, own_name: str) -> None:
    _names()
    if device_id not in _KINDS or (_KINDS[device_id], _OWN_NAMES.get(device_id)) == (kind, own_name):
        return
    with session_scope() as s:
        row = s.get(DeviceName, device_id)
        if row is not None:
            row.kind = kind
            row.own_name = own_name
    _KINDS[device_id] = kind
    _OWN_NAMES[device_id] = own_name


def owner_of(device_id: str) -> int | None:
    _names()
    return _OWNERS.get(device_id)


def _set_owner(device_id: str, profile_id: int) -> None:
    _names()
    with session_scope() as s:
        row = s.get(DeviceName, device_id)
        if row is None:
            s.add(_new_row(device_id, name="", owner_id=profile_id))
        else:
            row.owner_id = profile_id
            row.updated_at = utcnow()
    _OWNERS[device_id] = profile_id


def reachable(device: Device, sender_profile: int | None) -> bool:
    owner = owner_of(device.id)
    if device.kind in PERSONAL:
        return owner is not None and owner == sender_profile
    return owner is None or owner == sender_profile


def _profile_of(sender_id: str | None) -> int | None:
    sender = DEVICES.get(sender_id) if sender_id else None
    return sender.profile_id if sender else None


def display_name(device_id: str | None) -> str | None:
    return _names().get(device_id) if device_id else None


def _forget_stale(now: float) -> None:
    for key in [k for k, d in DEVICES.items() if d.waiting == 0 and now - d.last_seen > FORGET_SECONDS]:
        DEVICES.pop(key, None)


class Hello(BaseModel):
    id: str
    name: str
    kind: str
    profile_id: int | None = None


class State(BaseModel):
    id: str
    playing: dict[str, Any] | None = None


class Command(BaseModel):
    type: str
    play_id: str | None = None
    title: str | None = None
    position: float | None = None
    delta: float | None = None
    profile_id: int | None = None
    subtitle_id: str | None = None
    audio_index: int | None = None
    subtitle_size: str | None = None
    subtitle_style: str | None = None
    sender: str | None = None
    sender_id: str | None = None


class Rename(BaseModel):
    name: str


def _granted_profile(device_id: str, profile_id: int | None, pin: str | None) -> int | None:
    from .profiles import check_pin

    if profile_id is None:
        return None
    with session_scope() as s:
        profile = s.get(Profile, profile_id)
        if profile is None or not profile.pin_hash:
            return profile_id
        bound = _TOKENS.get(device_id)
        if bound is not None and bound[1] == profile_id:
            return profile_id
        if pin is None:
            return None
        check_pin(profile, pin)
    _verified(device_id, profile_id)
    return profile_id


@router.post("/hello")
def hello(
    body: Hello,
    x_cast_token: str | None = Header(default=None),
    x_profile_pin: str | None = Header(default=None),
):
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    if len(body.id) > 80:
        raise HTTPException(422, "not a device id")
    if not _owns_id(body.id, x_cast_token):
        raise HTTPException(403, "this device id belongs to another device")
    profile_id = _granted_profile(body.id, body.profile_id, x_profile_pin)
    now = time.monotonic()
    device = DEVICES.get(body.id)
    if device is None:
        device = DEVICES[body.id] = Device(id=body.id, name=body.name[:60], kind=body.kind)
    device.name = body.name[:60]
    device.kind = body.kind
    device.profile_id = profile_id
    device.last_seen = now
    _remember(body.id, body.kind, device.name)
    if body.kind in PERSONAL and profile_id is not None and owner_of(body.id) != profile_id:
        _set_owner(body.id, profile_id)
    _forget_stale(now)
    if body.id in _TOKENS:
        token = x_cast_token
    else:
        token = _PENDING.setdefault(body.id, secrets.token_urlsafe(24))
    return {
        "ok": True,
        "token": token,
        "profile_id": profile_id,
        "pin_required": body.profile_id is not None and profile_id is None,
    }


@router.post("/state")
def report_state(body: State, x_cast_token: str | None = Header(default=None)):
    device = DEVICES.get(body.id)
    if device is None:
        raise HTTPException(404, "say hello first")
    if not _owns_id(body.id, x_cast_token):
        raise HTTPException(403, "this device id belongs to another device")
    device.playing = body.playing
    device.last_seen = time.monotonic()
    return {"ok": True}


@router.get("/inbox")
async def inbox(
    id: str = Query(...),
    wait: float = Query(25, ge=0, le=MAX_WAIT),
    x_cast_token: str | None = Header(default=None),
):
    device = DEVICES.get(id)
    if device is None:
        raise HTTPException(404, "say hello first")
    if not _owns_id(id, x_cast_token):
        raise HTTPException(403, "this device id belongs to another device")
    device.last_seen = time.monotonic()
    if not device.queue and wait > 0:
        device.event.clear()
        device.waiting += 1
        try:
            await asyncio.wait_for(device.event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass
        finally:
            device.waiting -= 1
    device.last_seen = time.monotonic()
    commands, device.queue = device.queue, []
    return {"commands": commands}


@router.get("/devices")
def devices(exclude: str | None = None, x_cast_token: str | None = Header(default=None)):
    now = time.monotonic()
    profile = _sender_profile(exclude, x_cast_token)
    return {
        "devices": [
            d.public() for d in DEVICES.values()
            if d.online(now) and d.id != exclude and reachable(d, profile)
        ]
    }


@router.get("/devices/{device_id}")
def device(
    device_id: str,
    sender_id: str | None = None,
    x_cast_token: str | None = Header(default=None),
):
    d = DEVICES.get(device_id)
    if d is None or not d.online(time.monotonic()):
        raise HTTPException(404, "not online")
    itself = sender_id == device_id and _owns_id(device_id, x_cast_token)
    if not itself and not reachable(d, _sender_profile(sender_id, x_cast_token)):
        raise HTTPException(404, "not online")
    return d.public()


@router.post("/devices/{device_id}/command")
def command(device_id: str, body: Command, x_cast_token: str | None = Header(default=None)):
    d = DEVICES.get(device_id)
    if d is None or not d.online(time.monotonic()):
        raise HTTPException(404, "not online")
    if body.type not in COMMANDS:
        raise HTTPException(422, f"type must be one of {sorted(COMMANDS)}")
    if body.type == "play" and not body.play_id:
        raise HTTPException(422, "play needs a play_id")
    if body.type == "subtitle" and not body.subtitle_id:
        raise HTTPException(422, "subtitle needs a subtitle_id, or \"off\"")
    if body.type == "audio" and body.audio_index is None:
        raise HTTPException(422, "audio needs an audio_index")
    if body.type == "appearance" and not (body.subtitle_size or body.subtitle_style):
        raise HTTPException(422, "appearance needs a subtitle_size or a subtitle_style")
    # Device ids are not secret; only the token proves who the sender is.
    if body.sender_id and not _owns_id(body.sender_id, x_cast_token):
        raise HTTPException(403, "this is not the sending device's token")
    sender_profile = _profile_of(body.sender_id)
    if not reachable(d, sender_profile):
        raise HTTPException(403, "this device belongs to another profile")
    # Only the sender's own profile: never a way round another profile's PIN.
    if body.profile_id is not None and body.profile_id != sender_profile:
        raise HTTPException(403, "a play can only be sent as the sender's own profile")
    if body.sender_id:
        named = display_name(body.sender_id)
        if named:
            body.sender = named
        elif body.sender_id in DEVICES:
            body.sender = DEVICES[body.sender_id].name
    d.queue.append(body.model_dump(exclude_none=True, exclude={"sender_id"}))
    d.event.set()
    return {"ok": True}


@router.put("/devices/{device_id}/name")
def rename(device_id: str, body: Rename):
    name = " ".join(body.name.split())[:60]
    if len(device_id) > 80:
        raise HTTPException(422, "not a device id")
    names = _names()
    with session_scope() as s:
        row = s.get(DeviceName, device_id)
        if name:
            if row is None:
                s.add(_new_row(device_id, name=name))
            else:
                row.name = name
                row.updated_at = utcnow()
        elif row is not None and row.owner_id is not None:
            row.name = ""
            row.updated_at = utcnow()
        elif row is not None:
            s.delete(row)
            _KINDS.pop(device_id, None)
    if name:
        names[device_id] = name
    else:
        names.pop(device_id, None)
    d = DEVICES.get(device_id)
    return {"id": device_id, "name": name or (d.name if d else None)}


def known_devices() -> list[dict[str, Any]]:
    names = _names()
    now = time.monotonic()
    out: dict[str, dict[str, Any]] = {}
    with session_scope() as s:
        for row in s.scalars(select(DeviceName)):
            out[row.id] = {"id": row.id, "name": row.name or None,
                           "own_name": row.own_name or None, "kind": row.kind or None,
                           "online": False, "profile_id": None, "playing": None}
    for d in DEVICES.values():
        out[d.id] = {"id": d.id, "name": names.get(d.id), "own_name": d.name, "kind": d.kind,
                     "online": d.online(now), "profile_id": d.profile_id,
                     "playing": (d.playing or {}).get("title") if d.playing else None}
    for entry in out.values():
        entry["owner_id"] = owner_of(entry["id"])
        entry["personal"] = entry["kind"] in PERSONAL
    return sorted(out.values(), key=lambda e: (not e["online"], (e["name"] or e["own_name"] or "").lower()))


class Personal(ValueError):
    pass


def set_owner(device_id: str, profile_id: int | None) -> None:
    if kind_of(device_id) in PERSONAL:
        raise Personal(device_id)
    if profile_id is not None:
        _set_owner(device_id, profile_id)
        return
    _names()
    with session_scope() as s:
        row = s.get(DeviceName, device_id)
        if row is not None:
            if row.name:
                row.owner_id = None
                row.updated_at = utcnow()
            else:
                s.delete(row)
                _KINDS.pop(device_id, None)
    _OWNERS.pop(device_id, None)


def forget(device_id: str) -> None:
    _names()
    with session_scope() as s:
        row = s.get(DeviceName, device_id)
        if row is not None:
            s.delete(row)
        token = s.get(DeviceToken, device_id)
        if token is not None:
            s.delete(token)
    _TOKENS.pop(device_id, None)
    _PENDING.pop(device_id, None)
    (_NAMES or {}).pop(device_id, None)
    _OWNERS.pop(device_id, None)
    _KINDS.pop(device_id, None)
    DEVICES.pop(device_id, None)
