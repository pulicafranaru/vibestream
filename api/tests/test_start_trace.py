from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream.routers import player  # noqa: E402


def _client():
    from vibestream.db import init_db

    init_db()
    app = FastAPI()
    app.include_router(player.router)
    return TestClient(app)


def test_a_stall_is_logged_with_its_lines():
    from vibestream.db import session_scope
    from vibestream.models import Event

    c = _client()
    r = c.post("/api/play/59/trace", json={"reason": "stall", "lines": ["+0.000 start", "+1.200 ready"]})
    assert r.status_code == 200
    with session_scope() as s:
        event = s.query(Event).filter(Event.message == "start stall: 59").one()
        assert event.level == "warn"
        assert event.detail == "+0.000 start\n+1.200 ready"


def test_an_overlong_trace_is_refused():
    c = _client()
    r = c.post("/api/play/59/trace", json={"reason": "stall", "lines": ["x"] * 601})
    assert r.status_code == 422


def test_a_diagnostic_report_is_logged_under_its_topic():
    from vibestream.db import session_scope
    from vibestream.models import Event
    from vibestream.routers import diag

    app = FastAPI()
    app.include_router(diag.router)
    c = TestClient(app)
    r = c.post("/api/diag/orientation", json={"reason": "stuck", "lines": ["lock portrait"]})
    assert r.status_code == 200
    with session_scope() as s:
        event = s.query(Event).filter(Event.message == "orientation stuck").one()
        assert event.source == "diag" and event.detail == "lock portrait"
