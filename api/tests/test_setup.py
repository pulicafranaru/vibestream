from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.config import settings  # noqa: E402
from vibestream.models import KV, AdminAccount, AdminSession, Media  # noqa: E402
from vibestream.routers import admin  # noqa: E402
from vibestream.services import adminauth  # noqa: E402

H = {"X-VibeStream-Admin": "1"}


@pytest.fixture
def blank(tmp_path):
    saved = {k: getattr(settings, k) for k in ("filelist_username", "filelist_passkey",
                                                "tmdb_api_key", "qbit_download_dir")}
    for key in ("filelist_username", "filelist_passkey", "tmdb_api_key"):
        object.__setattr__(settings, key, "")
    object.__setattr__(settings, "qbit_download_dir", str(tmp_path))
    db.init_db()
    with db.session_scope() as s:
        s.query(AdminSession).delete()
        s.query(AdminAccount).delete()
        s.query(KV).filter(KV.key == admin.SETUP_DONE).delete()
    adminauth._setup_code = None
    adminauth.reset_throttle()
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(admin.locked)
    c = TestClient(app)
    c.get("/api/admin/auth/state")
    r = c.post("/api/admin/auth/setup",
               json={"code": adminauth.setup_code(), "password": "correct horse battery"}, headers=H)
    assert r.status_code == 200, r.text
    yield c
    for key, value in saved.items():
        object.__setattr__(settings, key, value)


def test_a_new_server_is_not_set_up(blank):
    state = blank.get("/api/admin/setup").json()
    assert state["done"] is False
    assert state["filelist"] == {"configured": False}
    assert state["tmdb"] == {"configured": False}
    assert state["storage"]["free_bytes"] > 0


def test_a_check_says_what_is_missing_before_asking_anyone(blank):
    r = blank.post("/api/admin/setup/check/filelist", headers=H).json()
    assert r == {"ok": False, "detail": "Enter the username and the passkey."}
    r = blank.post("/api/admin/setup/check/tmdb", headers=H).json()
    assert r == {"ok": False, "detail": "Enter the API key."}
    assert blank.post("/api/admin/setup/check/qbittorrent", headers=H).status_code == 404


def test_a_check_asks_the_service(blank, monkeypatch):
    from vibestream.services import filelist

    async def answer(self):
        return False, "invalid passkey"

    monkeypatch.setattr(filelist.FilelistClient, "check_credentials", answer)
    object.__setattr__(settings, "filelist_username", "someone")
    object.__setattr__(settings, "filelist_passkey", "0" * 32)
    r = blank.post("/api/admin/setup/check/filelist", headers=H).json()
    assert r == {"ok": False, "detail": "invalid passkey"}


def test_finishing_is_remembered(blank):
    r = blank.post("/api/admin/setup/finish", headers=H).json()
    assert r == {"done": True, "looking": False}
    assert blank.get("/api/admin/setup").json()["done"] is True


def test_a_server_set_up_from_env_has_nothing_to_walk_through(blank):
    object.__setattr__(settings, "filelist_username", "someone")
    object.__setattr__(settings, "filelist_passkey", "0" * 32)
    object.__setattr__(settings, "tmdb_api_key", "k" * 32)
    with db.session_scope() as s:
        if not s.query(Media).count():
            s.add(Media(tmdb_id=1, media_type="movie", title="A Film"))
    assert blank.get("/api/admin/setup").json()["done"] is True


def test_signed_out_there_is_no_setup(blank):
    blank.cookies.clear()
    assert blank.get("/api/admin/setup").status_code == 401
