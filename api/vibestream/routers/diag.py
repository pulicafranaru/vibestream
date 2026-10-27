from __future__ import annotations

import time
from collections import deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import get_session, record_event
from ..models import Event, utcnow

router = APIRouter(prefix="/api/diag", tags=["diag"])

MAX_LINES = 200
MAX_LINE = 300
MAX_DETAIL = 16 * 1024
PER_ADDRESS = 10
WINDOW_SECONDS = 10 * 60
KEEP = timedelta(days=14)

_sent: dict[str, deque[float]] = {}


class Report(BaseModel):
    reason: str = Field(max_length=40)
    lines: list[str] = Field(default_factory=list, max_length=600)


def _allowed(address: str) -> bool:
    now = time.monotonic()
    times = _sent.setdefault(address, deque())
    while times and times[0] < now - WINDOW_SECONDS:
        times.popleft()
    if len(times) >= PER_ADDRESS:
        return False
    times.append(now)
    if len(_sent) > 1000:
        for key in [k for k, v in _sent.items() if not v or v[-1] < now - WINDOW_SECONDS]:
            _sent.pop(key, None)
    return True


def _detail(lines: list[str]) -> str:
    kept: list[str] = []
    size = 0
    for line in reversed(lines[-MAX_LINES:]):
        line = line[:MAX_LINE]
        size += len(line.encode("utf-8", "replace")) + 1
        if size > MAX_DETAIL:
            break
        kept.append(line)
    return "\n".join(reversed(kept))


@router.post("/{topic}")
def report(topic: str, body: Report, request: Request, session: Session = Depends(get_session)):
    if not _allowed(request.client.host if request.client else "?"):
        raise HTTPException(429, "too many reports", headers={"Retry-After": str(WINDOW_SECONDS)})
    record_event(session, "diag", f"{topic[:40]} {body.reason}", _detail(body.lines), level="warn")
    session.execute(delete(Event).where(Event.source == "diag", Event.ts < utcnow() - KEEP))
    session.commit()
    return {"ok": True}
