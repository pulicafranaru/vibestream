from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.config import settings  # noqa: E402
from vibestream.models import AdminAccount, AdminSession, SettingOverride  # noqa: E402
from vibestream.routers import admin  # noqa: E402
from vibestream.services import adminauth, overrides  # noqa: E402

H = {"X-VibeStream-Admin": "1"}
GOOD = "correct horse battery"


def _client():
    db.init_db()
    with db.session_scope() as s:
        s.query(AdminSession).delete()
        s.query(AdminAccount).delete()
        s.query(SettingOverride).delete()
    adminauth._setup_code = None
    adminauth.reset_throttle()
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(admin.locked)
    return TestClient(app)


def _set_up(c):
    assert c.get("/api/admin/auth/state").json()["configured"] is False
    code = adminauth.setup_code()
    r = c.post("/api/admin/auth/setup", json={"code": code, "password": GOOD}, headers=H)
    assert r.status_code == 200, r.text
    return code


def test_the_first_password_wants_the_setup_code():
    c = _client()
    c.get("/api/admin/auth/state")
    code = adminauth.setup_code()
    assert len(code) == 9 and code[4] == "-"
    assert c.post("/api/admin/auth/setup", json={"code": "AAAA-AAAA", "password": GOOD},
                  headers=H).status_code == 403
    assert c.post("/api/admin/auth/setup", json={"code": code, "password": "short"},
                  headers=H).status_code == 422
    r = c.post("/api/admin/auth/setup", json={"code": code.replace("-", "").lower(), "password": GOOD},
               headers=H)
    assert r.status_code == 200
    assert c.get("/api/admin/auth/state").json() == {"configured": True, "signed_in": True,
                                                     "min_password": adminauth.MIN_PASSWORD}
    assert adminauth.setup_code() is None
    assert c.post("/api/admin/auth/setup", json={"code": code, "password": GOOD},
                  headers=H).status_code == 409


def test_the_password_is_kept_only_as_a_scrypt_hash():
    c = _client()
    _set_up(c)
    with db.session_scope() as s:
        stored = s.query(AdminAccount).one().password_hash
    assert stored.startswith("scrypt$") and GOOD not in stored
    assert adminauth.verify_password(stored, GOOD)
    assert not adminauth.verify_password(stored, GOOD + "!")
    with db.session_scope() as s:
        tokens = [row.token_hash for row in s.query(AdminSession)]
    cookie = c.cookies.get(adminauth.COOKIE)
    assert cookie not in tokens and len(tokens) == 1


def test_everything_but_about_wants_a_session_and_changes_want_the_header():
    c = _client()
    assert c.get("/api/admin/about").status_code == 200
    assert c.get("/api/admin/overview").status_code == 401
    assert c.get("/api/admin/events").status_code == 401
    assert c.put("/api/admin/config", json={"quality_max_gb": 20}, headers=H).status_code == 401
    _set_up(c)
    assert c.get("/api/admin/overview").status_code == 200
    assert c.put("/api/admin/config", json={"quality_max_gb": 20}).status_code == 403
    assert c.post("/api/admin/auth/login", json={"password": GOOD}).status_code == 403


def test_five_wrong_passwords_wait_and_the_wait_grows(monkeypatch):
    c = _client()
    _set_up(c)
    c.post("/api/admin/auth/logout", headers=H)
    clock = [1000.0]
    monkeypatch.setattr(adminauth.time, "monotonic", lambda: clock[0])
    for _ in range(5):
        assert c.post("/api/admin/auth/login", json={"password": "nope nope nope"}, headers=H).status_code == 403
    r = c.post("/api/admin/auth/login", json={"password": GOOD}, headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) == 31
    clock[0] += 31
    assert c.post("/api/admin/auth/login", json={"password": "nope nope nope"}, headers=H).status_code == 403
    r = c.post("/api/admin/auth/login", json={"password": GOOD}, headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) == 61
    clock[0] += 61
    assert c.post("/api/admin/auth/login", json={"password": GOOD}, headers=H).status_code == 200


def test_many_misses_from_anywhere_pause_sign_in(monkeypatch):
    c = _client()
    _set_up(c)
    clock = [5000.0]
    monkeypatch.setattr(adminauth.time, "monotonic", lambda: clock[0])
    for i in range(adminauth.GLOBAL_MISSES):
        with pytest.raises(adminauth.AuthError):
            adminauth.sign_in("wrong wrong", f"203.0.113.{i}", "")
    with pytest.raises(adminauth.AuthError) as caught:
        adminauth.sign_in(GOOD, "198.51.100.9", "")
    assert caught.value.status == 429


def test_guesses_made_at_once_are_counted_before_the_slow_hash(monkeypatch):
    """Concurrent guesses must not all pass the gate while the hash is computed."""
    import threading
    import time as real_time

    c = _client()
    _set_up(c)
    adminauth.reset_throttle()
    hashed = []

    def slow_verify(_stored, _password):
        hashed.append(1)
        real_time.sleep(0.2)
        return False

    monkeypatch.setattr(adminauth, "verify_password", slow_verify)

    def guess():
        try:
            adminauth.sign_in("wrong wrong", "203.0.113.9", "")
        except adminauth.AuthError:
            pass

    threads = [threading.Thread(target=guess) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(hashed) == adminauth.PER_ADDRESS_FREE


def test_forwarded_addresses_are_believed_only_from_named_proxies():
    """X-Forwarded-For is not trusted, so a client cannot pick a fresh address per guess."""
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert '"--forwarded-allow-ips", "*"' not in dockerfile
    assert "ENV FORWARDED_ALLOW_IPS=127.0.0.1" in dockerfile


def test_sessions_end_unused_on_sign_out_and_on_a_new_password(monkeypatch):
    c = _client()
    _set_up(c)
    other = TestClient(c.app)
    assert other.post("/api/admin/auth/login", json={"password": GOOD}, headers=H).status_code == 200
    listed = c.get("/api/admin/auth/sessions").json()["sessions"]
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1

    assert c.post("/api/admin/auth/password", json={"current": "wrong wrong", "new": "another long one"},
                  headers=H).status_code == 403
    assert c.post("/api/admin/auth/password", json={"current": GOOD, "new": "another long one"},
                  headers=H).status_code == 200
    assert c.get("/api/admin/overview").status_code == 200
    assert other.get("/api/admin/overview").status_code == 401

    # Twelve hours unused.
    later = adminauth.utcnow() + adminauth.IDLE + timedelta(minutes=1)
    monkeypatch.setattr(adminauth, "utcnow", lambda: later)
    assert c.get("/api/admin/overview").status_code == 401


def test_signing_out_ends_the_session():
    c = _client()
    _set_up(c)
    cookie = c.cookies.get(adminauth.COOKIE)
    c.post("/api/admin/auth/logout", headers=H)
    assert adminauth.session_for(cookie) is None


def test_settings_are_checked_kept_applied_and_reset(monkeypatch):
    c = _client()
    _set_up(c)
    before = settings.quality_max_gb
    try:
        fields = c.get("/api/admin/config").json()["fields"]
        assert "qbit_password" not in fields and "qbit_url" not in fields
        r = c.put("/api/admin/config", json={"quality_max_gb": 25, "filelist_sweep_cron": "every tuesday"},
                  headers=H)
        assert r.status_code == 422 and "filelist_sweep_cron" in r.json()["detail"]["fields"]
        assert settings.quality_max_gb == before

        r = c.put("/api/admin/config", json={"quality_max_gb": 25, "filelist_categories": [21, 4, 4]},
                  headers=H)
        assert r.status_code == 200
        assert settings.quality_max_gb == 25 and settings.filelist_categories == [4, 21]
        assert r.json()["fields"]["quality_max_gb"]["changed_at"]
        assert c.put("/api/admin/config", json={"filelist_categories": [7]}, headers=H).status_code == 422
        assert c.put("/api/admin/config", json={"qbit_password": "x"}, headers=H).status_code == 422

        object.__setattr__(settings, "quality_max_gb", before)
        overrides.load()
        assert settings.quality_max_gb == 25

        assert c.delete("/api/admin/config/quality_max_gb", headers=H).status_code == 200
        assert settings.quality_max_gb == before
    finally:
        for key in ("quality_max_gb", "filelist_categories"):
            overrides.reset(key)


def test_secrets_never_go_back_to_the_browser():
    c = _client()
    _set_up(c)
    try:
        c.put("/api/admin/config", json={"tmdb_api_key": "abcdef0123456789wxyz"}, headers=H)
        shown = c.get("/api/admin/config").json()["fields"]["tmdb_api_key"]["value"]
        assert shown == {"set": True, "ends": "wxyz"}
        assert "abcdef0123456789wxyz" not in c.get("/api/admin/config").text
    finally:
        overrides.reset("tmdb_api_key")
