"""Profiles and ratings. PINs keep profiles apart in the apps; they are not API authentication."""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    ContinueHidden, Download, Media, MyListItem, Profile, Rating, WatchProgress, utcnow,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

AVATAR_COLOURS = [
    "crimson", "teal", "amber", "emerald", "violet",
    "magenta", "azure", "coral", "lime", "slate",
]
AVATAR_FACES = ["smile", "grin", "wink", "surprised", "content", "cool"]

LANGUAGES = ("en", "de", "ro")


def avatar_choices() -> list[str]:
    return [f"{colour}-{face}" for colour in AVATAR_COLOURS for face in AVATAR_FACES]


# Wrong PINs in a row before a lockout. Each lockout doubles, up to a day.
PIN_TRIES = 5
PIN_LOCK_SECONDS = 30
PIN_LOCK_MAX_SECONDS = 24 * 3600
# profile id -> (wrong tries in a row, locked until (monotonic), lockouts since last success)
_FAILURES: dict[int, tuple[int, float, int]] = {}


def _digest(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000).hex()


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    return f"{salt.hex()}${_digest(pin, salt)}"


def _matches(stored: str, pin: str) -> bool:
    salt, _, digest = stored.partition("$")
    try:
        return hmac.compare_digest(_digest(pin, bytes.fromhex(salt)), digest)
    except ValueError:
        return False


def valid_pin(pin: str | None) -> bool:
    return pin is not None and len(pin) == 4 and pin.isascii() and pin.isdigit()


def check_pin(profile: Profile, pin: str | None) -> None:
    if not profile.pin_hash:
        return
    now = time.monotonic()
    wrong, until, lockouts = _FAILURES.get(profile.id, (0, 0.0, 0))
    if until > now:
        raise HTTPException(429, "too many tries", headers={"Retry-After": str(int(until - now) + 1)})
    if pin is not None and _matches(profile.pin_hash, pin):
        _FAILURES.pop(profile.id, None)
        return
    wrong += 1
    if wrong >= PIN_TRIES:
        lock = min(PIN_LOCK_SECONDS * 2 ** lockouts, PIN_LOCK_MAX_SECONDS)
        _FAILURES[profile.id] = (0, now + lock, lockouts + 1)
    else:
        _FAILURES[profile.id] = (wrong, 0.0, lockouts)
    raise HTTPException(403, "wrong pin")


def serialise(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "avatar": profile.avatar,
        "is_kids": profile.is_kids,
        "language": profile.language or "en",
        "has_pin": bool(profile.pin_hash),
        "last_used_at": profile.last_used_at.isoformat() if profile.last_used_at else None,
    }


def ensure_default_profile(session: Session) -> Profile:
    existing = session.scalar(select(Profile).order_by(Profile.id))
    if existing:
        return existing

    profile = Profile(name="Me", avatar="crimson-smile")
    session.add(profile)
    session.flush()

    adopted = 0
    legacy = session.scalars(
        select(Download).where(Download.resume_seconds > 0)
    )
    for download in legacy:
        session.add(
            WatchProgress(
                profile_id=profile.id,
                download_id=download.id,
                resume_seconds=download.resume_seconds,
                runtime_seconds=download.runtime_seconds or 0,
                finished_at=download.finished_at,
                updated_at=download.resume_updated_at or utcnow(),
            )
        )
        adopted += 1

    session.commit()
    return profile


def resolve_profile(
    session: Session, profile_id: int | None
) -> Profile:
    if profile_id:
        found = session.get(Profile, profile_id)
        if found:
            return found
    return ensure_default_profile(session)


def current_profile_id(
    x_vibestream_profile: str | None = Header(default=None),
) -> int | None:
    try:
        return int(x_vibestream_profile) if x_vibestream_profile else None
    except ValueError:
        return None


@router.get("")
def list_profiles(session: Session = Depends(get_session)):
    ensure_default_profile(session)
    rows = session.scalars(select(Profile).order_by(Profile.id)).all()
    return {"profiles": [serialise(p) for p in rows], "avatars": avatar_choices()}


@router.post("")
def create_profile(
    name: str = Query(..., min_length=1, max_length=64),
    avatar: str = Query("crimson-smile"),
    is_kids: bool = Query(False),
    language: str = Query("en"),
    session: Session = Depends(get_session),
):
    if avatar not in avatar_choices():
        raise HTTPException(400, "unknown avatar")
    if language not in LANGUAGES:
        raise HTTPException(400, "unknown language")
    clean = name.strip()
    if not clean:
        raise HTTPException(400, "name cannot be blank")

    profile = Profile(name=clean, avatar=avatar, is_kids=is_kids, language=language)
    session.add(profile)
    session.commit()
    return serialise(profile)


@router.patch("/{profile_id}")
def update_profile(
    profile_id: int,
    name: str | None = Query(None, max_length=64),
    avatar: str | None = Query(None),
    language: str | None = Query(None),
    is_kids: bool | None = Query(None),
    x_profile_pin: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    check_pin(profile, x_profile_pin)
    if is_kids is not None:
        profile.is_kids = is_kids
    if language is not None:
        if language not in LANGUAGES:
            raise HTTPException(400, "unknown language")
        profile.language = language
    if avatar is not None:
        if avatar not in avatar_choices():
            raise HTTPException(400, "unknown avatar")
        profile.avatar = avatar
    if name is not None and name.strip():
        profile.name = name.strip()
    session.commit()
    return serialise(profile)


class PinCheck(BaseModel):
    pin: str


class PinChange(BaseModel):
    pin: str | None = None
    current: str | None = None


@router.post("/{profile_id}/pin/check")
def pin_check(profile_id: int, body: PinCheck, session: Session = Depends(get_session)):
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    check_pin(profile, body.pin)
    return {"ok": True}


@router.put("/{profile_id}/pin")
def pin_change(profile_id: int, body: PinChange, session: Session = Depends(get_session)):
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    if body.pin is not None and not valid_pin(body.pin):
        raise HTTPException(422, "a pin is four digits")
    check_pin(profile, body.current)
    profile.pin_hash = hash_pin(body.pin) if body.pin is not None else None
    session.commit()
    return serialise(profile)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    x_profile_pin: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    check_pin(profile, x_profile_pin)
    remaining = session.scalar(select(func.count()).select_from(Profile))
    if remaining <= 1:
        raise HTTPException(400, "cannot delete the only profile")
    _forget_profile(session, profile.id)
    session.delete(profile)
    session.commit()
    # After the commit: it writes in a session of its own.
    from . import cast

    cast.forget_profile(profile_id)
    return {"ok": True}


def _forget_profile(session: Session, profile_id: int) -> None:
    """Delete what does not cascade (episode progress, clips); devices given to it become shared."""
    from ..models import Clip, DeviceName, EpisodeProgress
    from ..services import clips, smartcrop

    session.execute(delete(EpisodeProgress).where(EpisodeProgress.profile_id == profile_id))
    clip_ids = list(session.scalars(select(Clip.id).where(Clip.profile_id == profile_id)))
    session.execute(delete(Clip).where(Clip.profile_id == profile_id))
    session.execute(
        update(DeviceName).where(DeviceName.owner_id == profile_id).values(owner_id=None)
    )
    for clip_id in clip_ids:
        clips.remove(clip_id)
        smartcrop.remove(clip_id)


@router.post("/{profile_id}/use")
def mark_used(profile_id: int, session: Session = Depends(get_session)):
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "unknown profile")
    profile.last_used_at = utcnow()
    session.commit()
    return serialise(profile)


@router.get("/{profile_id}/ratings")
def list_ratings(profile_id: int, session: Session = Depends(get_session)):
    rows = session.scalars(
        select(Rating).where(Rating.profile_id == profile_id)
    ).all()
    return {str(r.media_id): r.value for r in rows}


@router.put("/{profile_id}/ratings/{media_id}")
def set_rating(
    profile_id: int,
    media_id: int,
    value: int = Query(..., ge=-1, le=1),
    session: Session = Depends(get_session),
):
    if session.get(Profile, profile_id) is None:
        raise HTTPException(404, "unknown profile")
    if session.get(Media, media_id) is None:
        raise HTTPException(404, "unknown media")

    existing = session.scalar(
        select(Rating).where(
            Rating.profile_id == profile_id, Rating.media_id == media_id
        )
    )

    if value == 0:
        if existing:
            session.delete(existing)
            session.commit()
        return {"media_id": media_id, "value": 0}

    if existing:
        existing.value = value
        existing.updated_at = utcnow()
    else:
        session.add(Rating(profile_id=profile_id, media_id=media_id, value=value))
    session.commit()
    return {"media_id": media_id, "value": value}


@router.get("/{profile_id}/my-list")
def list_my_list(profile_id: int, session: Session = Depends(get_session)):
    rows = session.scalars(
        select(MyListItem.media_id)
        .where(MyListItem.profile_id == profile_id)
        .order_by(MyListItem.added_at.desc())
    ).all()
    return list(rows)


@router.put("/{profile_id}/my-list/{media_id}")
def add_to_my_list(profile_id: int, media_id: int, session: Session = Depends(get_session)):
    if session.get(Profile, profile_id) is None:
        raise HTTPException(404, "unknown profile")
    if session.get(Media, media_id) is None:
        raise HTTPException(404, "unknown media")
    existing = session.scalar(
        select(MyListItem).where(
            MyListItem.profile_id == profile_id, MyListItem.media_id == media_id
        )
    )
    if existing is None:
        session.add(MyListItem(profile_id=profile_id, media_id=media_id))
        session.commit()
    return {"media_id": media_id, "in_list": True}


@router.delete("/{profile_id}/my-list/{media_id}")
def remove_from_my_list(profile_id: int, media_id: int, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(MyListItem).where(
            MyListItem.profile_id == profile_id, MyListItem.media_id == media_id
        )
    )
    if existing is not None:
        session.delete(existing)
        session.commit()
    return {"media_id": media_id, "in_list": False}


@router.delete("/{profile_id}/continue/{media_id}")
def hide_from_continue(profile_id: int, media_id: int, session: Session = Depends(get_session)):
    if session.get(Profile, profile_id) is None:
        raise HTTPException(404, "unknown profile")
    if session.get(Media, media_id) is None:
        raise HTTPException(404, "unknown title")
    row = session.scalar(
        select(ContinueHidden).where(
            ContinueHidden.profile_id == profile_id, ContinueHidden.media_id == media_id
        )
    )
    if row is None:
        session.add(ContinueHidden(profile_id=profile_id, media_id=media_id, hidden_at=utcnow()))
    else:
        row.hidden_at = utcnow()
    session.commit()
    return {"ok": True}
