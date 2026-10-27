"""Any origin may call the API, but never with the admin's cookie."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from vibestream.main import app  # noqa: E402

EVIL = "https://evil.example"


def test_a_cross_origin_admin_preflight_is_not_granted_credentials():
    client = TestClient(app)
    reply = client.options("/api/admin/auth/state", headers={
        "Origin": EVIL,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-vibestream-admin",
    })
    assert reply.headers.get("access-control-allow-credentials") != "true"
    # The wildcard, not the caller's origin reflected back.
    assert reply.headers.get("access-control-allow-origin") == "*"


def test_a_cross_origin_request_is_answered_without_credentials():
    client = TestClient(app)
    reply = client.get("/healthz", headers={"Origin": EVIL})
    assert reply.status_code == 200
    assert reply.headers.get("access-control-allow-origin") == "*"
    assert reply.headers.get("access-control-allow-credentials") != "true"
