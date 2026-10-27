from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.models import Profile  # noqa: E402
from vibestream.routers import profiles  # noqa: E402


def _setup():
    db.init_db()
    with db.session_scope() as session:
        keep = Profile(name="Other")
        mine = Profile(name="Locked")
        session.add_all([keep, mine])
        session.flush()
        pid = mine.id
    profiles._FAILURES.clear()
    app = FastAPI()
    app.include_router(profiles.router)
    return TestClient(app), pid


def _has_pin(c, pid):
    return next(p for p in c.get("/api/profiles").json()["profiles"] if p["id"] == pid)["has_pin"]


def test_a_pin_is_set_checked_changed_and_removed():
    c, pid = _setup()
    assert _has_pin(c, pid) is False
    for bad in ("123", "12345", "12a4", "١٢٣٤"):
        assert c.put(f"/api/profiles/{pid}/pin", json={"pin": bad}).status_code == 422
    assert c.put(f"/api/profiles/{pid}/pin", json={"pin": "0420"}).json()["has_pin"] is True

    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0420"}).status_code == 200
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0421"}).status_code == 403

    assert c.put(f"/api/profiles/{pid}/pin", json={"pin": "1111"}).status_code == 403
    assert c.put(f"/api/profiles/{pid}/pin", json={"pin": "1111", "current": "0000"}).status_code == 403
    assert c.put(f"/api/profiles/{pid}/pin", json={"pin": "1111", "current": "0420"}).status_code == 200
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "1111"}).status_code == 200

    assert c.put(f"/api/profiles/{pid}/pin", json={"pin": None, "current": "1111"}).json()["has_pin"] is False
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "9999"}).status_code == 200


def test_the_pin_is_not_stored_as_typed():
    c, pid = _setup()
    c.put(f"/api/profiles/{pid}/pin", json={"pin": "2468"})
    with db.session_scope() as s:
        stored = s.get(Profile, pid).pin_hash
    assert "2468" not in stored and "$" in stored


def test_five_wrong_in_a_row_wait_thirty_seconds(monkeypatch):
    c, pid = _setup()
    c.put(f"/api/profiles/{pid}/pin", json={"pin": "1357"})
    clock = [1000.0]
    monkeypatch.setattr(profiles.time, "monotonic", lambda: clock[0])
    for _ in range(4):
        assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0000"}).status_code == 403
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "1357"}).status_code == 200
    for _ in range(5):
        assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0000"}).status_code == 403
    r = c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "1357"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) == 31
    clock[0] += 31
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "1357"}).status_code == 200


def test_deleting_a_locked_profile_wants_its_pin():
    c, pid = _setup()
    c.put(f"/api/profiles/{pid}/pin", json={"pin": "8642"})
    assert c.delete(f"/api/profiles/{pid}").status_code == 403
    assert c.delete(f"/api/profiles/{pid}", headers={"X-Profile-Pin": "1111"}).status_code == 403
    assert c.delete(f"/api/profiles/{pid}", headers={"X-Profile-Pin": "8642"}).status_code == 200


def test_changing_a_locked_profile_wants_its_pin():
    c, pid = _setup()
    c.put(f"/api/profiles/{pid}/pin", json={"pin": "8642"})
    assert c.patch(f"/api/profiles/{pid}?is_kids=false").status_code == 403
    assert c.patch(f"/api/profiles/{pid}?name=Mine",
                   headers={"X-Profile-Pin": "1111"}).status_code == 403
    r = c.patch(f"/api/profiles/{pid}?name=Mine&is_kids=true", headers={"X-Profile-Pin": "8642"})
    assert r.status_code == 200
    assert r.json()["name"] == "Mine" and r.json()["is_kids"] is True


def test_the_kids_flag_is_kept_by_an_edit():
    c, pid = _setup()
    assert c.patch(f"/api/profiles/{pid}?is_kids=true").json()["is_kids"] is True
    assert c.patch(f"/api/profiles/{pid}?avatar=teal-wink").json()["is_kids"] is True
    assert c.patch(f"/api/profiles/{pid}?is_kids=false").json()["is_kids"] is False


def test_every_lockout_is_longer_than_the_last(monkeypatch):
    c, pid = _setup()
    c.put(f"/api/profiles/{pid}/pin", json={"pin": "1357"})
    clock = [1000.0]
    monkeypatch.setattr(profiles.time, "monotonic", lambda: clock[0])
    waits = []
    for _ in range(4):
        for _ in range(5):
            assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0000"}).status_code == 403
        r = c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0000"})
        assert r.status_code == 429
        waits.append(int(r.headers["Retry-After"]))
        clock[0] += waits[-1]
    assert waits == [31, 61, 121, 241]
    assert c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "1357"}).status_code == 200
    for _ in range(5):
        c.post(f"/api/profiles/{pid}/pin/check", json={"pin": "0000"})
    assert c.post(f"/api/profiles/{pid}/pin/check",
                  json={"pin": "0000"}).headers["Retry-After"] == "31"


def test_a_profile_that_watched_and_clipped_can_be_deleted(monkeypatch):
    """Episode progress and clips refer to the profile with no cascade."""
    from vibestream.models import (
        Clip, DeviceName, Episode, EpisodeProgress, Media, Season,
    )
    from vibestream.services import clips, smartcrop

    removed = []
    monkeypatch.setattr(clips, "remove", removed.append)
    monkeypatch.setattr(smartcrop, "remove", lambda _id: None)
    c, pid = _setup()
    device = "phone-" + str(pid)
    with db.session_scope() as s:
        media = Media(title="Show", media_type="tv")
        s.add(media)
        s.flush()
        season = Season(media_id=media.id, number=1)
        s.add(season)
        s.flush()
        episode = Episode(media_id=media.id, season_id=season.id, season_number=1, number=1)
        s.add(episode)
        s.flush()
        s.add(EpisodeProgress(profile_id=pid, episode_id=episode.id, resume_seconds=12))
        clip = Clip(profile_id=pid, media_id=media.id, play_id="e1")
        s.add(clip)
        s.add(DeviceName(id=device, name="Phone", owner_id=pid))
        s.flush()
        clip_id = clip.id

    assert c.delete(f"/api/profiles/{pid}").status_code == 200
    with db.session_scope() as s:
        assert s.query(EpisodeProgress).filter_by(profile_id=pid).count() == 0
        assert s.query(Clip).filter_by(profile_id=pid).count() == 0
        assert s.get(DeviceName, device).owner_id is None
    assert removed == [clip_id]
