from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.models import Event, utcnow  # noqa: E402
from vibestream.routers import diag  # noqa: E402


def _client():
    db.init_db()
    with db.session_scope() as s:
        s.query(Event).filter(Event.source == "diag").delete()
    diag._sent.clear()
    app = FastAPI()
    app.include_router(diag.router)
    return TestClient(app)


def _diag_events():
    with db.session_scope() as s:
        return [(e.message, e.detail) for e in s.query(Event).filter(Event.source == "diag")]


def test_a_report_is_kept_small():
    c = _client()
    lines = [f"{n:04d} " + "x" * 1000 for n in range(600)]
    assert c.post("/api/diag/rotation", json={"reason": "sideways", "lines": lines}).status_code == 200
    [(message, detail)] = _diag_events()
    assert message == "rotation sideways"
    assert len(detail.encode()) <= diag.MAX_DETAIL
    assert detail.splitlines()[-1].startswith("0599 ")


def test_an_address_sends_only_a_few_in_a_while():
    c = _client()
    for _ in range(diag.PER_ADDRESS):
        assert c.post("/api/diag/t", json={"reason": "r"}).status_code == 200
    assert c.post("/api/diag/t", json={"reason": "r"}).status_code == 429
    assert len(_diag_events()) == diag.PER_ADDRESS


def test_old_reports_go():
    c = _client()
    with db.session_scope() as s:
        s.add(Event(source="diag", message="old", ts=utcnow() - timedelta(days=30)))
        s.add(Event(source="reaper", message="kept", ts=utcnow() - timedelta(days=30)))
    c.post("/api/diag/t", json={"reason": "new"})
    assert [m for m, _ in _diag_events()] == ["t new"]
    with db.session_scope() as s:
        assert s.query(Event).filter(Event.message == "kept").count() == 1
