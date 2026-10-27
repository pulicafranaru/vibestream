from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Clip
from ..services import clips as clip_service
from ..services import smartcrop
from .profiles import current_profile_id, resolve_profile

router = APIRouter(prefix="/api/clips", tags=["clips"])


class NewClip(BaseModel):
    play_id: str
    start: float
    end: float


class Keyframe(BaseModel):
    t: float
    # Fractions of the frame's width and height; zoom 1 is the full height.
    x: float
    y: float = 0.5
    zoom: float = 1.0


class VerticalEdit(BaseModel):
    keyframes: list[Keyframe]


def _payload(clip: Clip) -> dict:
    return {
        "id": clip.id,
        "media_id": clip.media_id,
        "play_id": clip.play_id,
        "title": clip.title,
        "subtitle": clip.subtitle,
        "start": round(clip.start_seconds, 3),
        "end": round(clip.end_seconds, 3),
        "duration": round(clip.duration_seconds, 1),
        "created_at": clip.created_at.isoformat() if clip.created_at else None,
        "video": f"/api/clips/{clip.id}/video.mp4",
        "thumb": f"/api/clips/{clip.id}/thumb.jpg",
    }


@router.get("")
def list_clips(
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    profile = resolve_profile(session, profile_id)
    rows = session.scalars(
        select(Clip).where(Clip.profile_id == profile.id).order_by(Clip.created_at.desc())
    )
    return {"items": [_payload(c) for c in rows]}


@router.post("")
async def save_clip(
    body: NewClip,
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    from .player import _info, _load

    length = body.end - body.start
    if body.start < 0 or length < clip_service.MIN_SECONDS:
        raise HTTPException(400, "a clip has to be at least two seconds long")
    if length > clip_service.MAX_SECONDS + 0.5:
        raise HTTPException(400, "a clip can be at most two minutes long")

    target = _load(session, body.play_id)
    info = await _info(target.path)
    profile = resolve_profile(session, profile_id)
    presentation = target.presentation()
    episode = presentation.get("episode")
    clip = Clip(
        profile_id=profile.id,
        media_id=target.media_id,
        play_id=body.play_id,
        title=presentation.get("title") or target.title or "",
        subtitle=(f"S{episode['season']}:E{episode['number']} {episode.get('name') or ''}".strip()
                  if episode else None),
        start_seconds=body.start,
        end_seconds=body.end,
        duration_seconds=length,
    )
    session.add(clip)
    session.commit()
    try:
        real = await clip_service.cut(clip.id, info, body.start, body.end)
    except clip_service.ClipError as exc:
        session.delete(clip)
        session.commit()
        status = 409 if isinstance(exc, clip_service.ClipUnavailable) else 500
        raise HTTPException(status, f"could not cut the clip: {exc}") from exc
    clip.duration_seconds = real
    clip.start_seconds = max(0.0, body.end - real)
    session.commit()
    asyncio.get_running_loop().run_in_executor(None, clip_service.picture, clip.id)
    smartcrop.ensure(clip.id)
    return _payload(clip)


def _own(session: Session, clip_id: int) -> Clip:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "unknown clip")
    return clip


@router.get("/{clip_id}/video.mp4")
def clip_video(clip_id: int, session: Session = Depends(get_session)):
    _own(session, clip_id)
    path = clip_service.video_path(clip_id)
    if not os.path.exists(path):
        raise HTTPException(404, "the clip's video is missing")
    # FileResponse answers Range requests, which AVPlayer needs for an MP4.
    return FileResponse(path, media_type="video/mp4",
                        headers={"Cache-Control": "public, max-age=604800, immutable"})


@router.get("/{clip_id}/thumb.jpg")
def clip_thumb(clip_id: int, session: Session = Depends(get_session)):
    _own(session, clip_id)
    path = clip_service.thumb_path(clip_id)
    if not os.path.exists(path):
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800, immutable"})


@router.get("/{clip_id}/vertical")
def get_vertical(clip_id: int, session: Session = Depends(get_session)):
    _own(session, clip_id)
    crop = smartcrop.cached(clip_id)
    if crop is None:
        smartcrop.ensure(clip_id)
    try:
        with open(clip_service.vertical_path(clip_id), encoding="utf-8") as fh:
            keyframes = json.load(fh).get("keyframes") or []
    except (OSError, ValueError):
        keyframes = []
    return {"picture": clip_service.picture(clip_id), "crop": crop, "keyframes": keyframes}


@router.put("/{clip_id}/vertical")
def put_vertical(clip_id: int, body: VerticalEdit, session: Session = Depends(get_session)):
    clip = _own(session, clip_id)
    path = clip_service.vertical_path(clip_id)
    keyframes = sorted(
        ({"t": round(min(max(k.t, 0.0), clip.duration_seconds), 3),
          "x": round(min(max(k.x, 0.0), 1.0), 4),
          "y": round(min(max(k.y, 0.0), 1.0), 4),
          "zoom": round(min(max(k.zoom, 1.0), 4.0), 3)} for k in body.keyframes),
        key=lambda k: k["t"],
    )
    if not keyframes:
        try:
            os.remove(path)
        except OSError:
            pass
        return {"keyframes": []}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "keyframes": keyframes}, fh)
    os.replace(path + ".part", path)
    return {"keyframes": keyframes}


@router.delete("/{clip_id}")
def delete_clip(clip_id: int, session: Session = Depends(get_session)):
    clip = _own(session, clip_id)
    session.delete(clip)
    session.commit()
    clip_service.remove(clip_id)
    smartcrop.remove(clip_id)
    return {"deleted": clip_id}
