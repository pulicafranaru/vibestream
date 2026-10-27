from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream.routers import cast  # noqa: E402


def _client():
    from vibestream.db import init_db, session_scope
    from vibestream.models import DeviceName, DeviceToken, Profile

    init_db()
    with session_scope() as s:
        s.query(DeviceName).delete()
        s.query(DeviceToken).delete()
        # Every profile is open unless a test sets a PIN.
        s.query(Profile).update({Profile.pin_hash: None})
    cast._NAMES = None
    cast._PENDING.clear()
    cast.DEVICES.clear()
    app = FastAPI()
    app.include_router(cast.router)
    return TestClient(app)


def test_a_device_says_hello_and_is_listed_to_others_only():
    c = _client()
    assert c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"}).status_code == 200
    assert c.post("/api/cast/hello", json={"id": "ph", "name": "iPhone", "kind": "phone"}).status_code == 200
    names = [d["name"] for d in c.get("/api/cast/devices", params={"exclude": "ph"}).json()["devices"]]
    assert names == ["TV"]


def test_a_command_waits_in_the_inbox_until_read_once():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"})
    r = c.post("/api/cast/devices/tv/command",
               json={"type": "play", "play_id": "12", "position": 600.5, "sender": "iPhone"})
    assert r.status_code == 200
    got = c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}).json()["commands"]
    assert got == [{"type": "play", "play_id": "12", "position": 600.5, "sender": "iPhone"}]
    assert c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}).json()["commands"] == []


def test_state_is_read_back_for_the_remote():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"})
    playing = {"play_id": "12", "title": "Film", "position": 61, "duration": 5400, "paused": False}
    c.post("/api/cast/state", json={"id": "tv", "playing": playing})
    assert c.get("/api/cast/devices/tv").json()["playing"] == playing


def test_nonsense_is_refused():
    c = _client()
    assert c.post("/api/cast/hello", json={"id": "x", "name": "X", "kind": "toaster"}).status_code == 422
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"})
    assert c.post("/api/cast/devices/tv/command", json={"type": "dance"}).status_code == 422
    assert c.post("/api/cast/devices/tv/command", json={"type": "play"}).status_code == 422
    assert c.post("/api/cast/devices/gone/command", json={"type": "stop"}).status_code == 404
    assert c.get("/api/cast/inbox", params={"id": "nobody", "wait": 0}).status_code == 404


def test_the_remote_can_choose_tracks_and_their_look():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"})
    sent = [
        {"type": "subtitle", "subtitle_id": "off"},
        {"type": "subtitle", "subtitle_id": "s2"},
        {"type": "audio", "audio_index": 0},
        {"type": "appearance", "subtitle_size": "large"},
    ]
    for body in sent:
        assert c.post("/api/cast/devices/tv/command", json=body).status_code == 200
    assert c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}).json()["commands"] == sent
    for bad in ({"type": "subtitle"}, {"type": "audio"}, {"type": "appearance"}):
        assert c.post("/api/cast/devices/tv/command", json=bad).status_code == 422


def test_a_device_can_be_named_and_the_name_signs_its_commands():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "Smart TV", "kind": "tv"})
    c.post("/api/cast/hello", json={"id": "ph", "name": "iPhone", "kind": "phone"})
    assert c.put("/api/cast/devices/tv/name", json={"name": "  Main  screen "}).json()["name"] == "Main screen"
    assert c.put("/api/cast/devices/ph/name", json={"name": "Sam's iPhone"}).status_code == 200
    tv = c.get("/api/cast/devices/tv").json()
    assert (tv["name"], tv["own_name"]) == ("Main screen", "Smart TV")

    cast._NAMES = None
    cast.DEVICES.clear()
    c.post("/api/cast/hello", json={"id": "tv", "name": "Smart TV", "kind": "tv"})
    assert c.get("/api/cast/devices/tv").json()["name"] == "Main screen"

    c.post("/api/cast/devices/tv/command", json={"type": "pause", "sender_id": "ph", "sender": "iPhone"})
    got = c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}).json()["commands"]
    assert got == [{"type": "pause", "sender": "Sam's iPhone"}]

    assert c.put("/api/cast/devices/tv/name", json={"name": ""}).json()["name"] == "Smart TV"
    assert c.get("/api/cast/devices/tv").json()["name"] == "Smart TV"


def test_a_phone_is_only_for_the_profile_it_belongs_to():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv", "profile_id": 2})
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "pad", "name": "iPad", "kind": "tablet", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})

    listed = lambda me: sorted(d["id"] for d in c.get("/api/cast/devices", params={"exclude": me}).json()["devices"])
    assert listed("hers") == ["tv"]
    assert listed("mine") == ["pad", "tv"]

    play = {"type": "play", "play_id": "12"}
    assert c.post("/api/cast/devices/mine/command", json={**play, "sender_id": "hers"}).status_code == 403
    assert c.post("/api/cast/devices/mine/command", json={"type": "pause", "sender_id": "hers"}).status_code == 403
    assert c.post("/api/cast/devices/mine/command", json=play).status_code == 403
    assert c.get("/api/cast/inbox", params={"id": "mine", "wait": 0}).json()["commands"] == []
    assert c.post("/api/cast/devices/pad/command", json={**play, "sender_id": "mine"}).status_code == 200
    assert c.post("/api/cast/devices/tv/command", json={**play, "sender_id": "hers"}).status_code == 200


def test_a_phone_stays_its_owners_with_nobody_chosen_and_across_a_restart():
    c = _client()
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone"})
    assert c.post("/api/cast/devices/mine/command", json={"type": "stop", "sender_id": "hers"}).status_code == 403

    cast._NAMES = None
    cast.DEVICES.clear()
    assert cast.kind_of("mine") == "phone"
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone"})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})
    assert c.post("/api/cast/devices/mine/command", json={"type": "stop", "sender_id": "hers"}).status_code == 403
    c.put("/api/cast/devices/mine/name", json={"name": "Mine"})
    c.put("/api/cast/devices/mine/name", json={"name": ""})
    cast._NAMES = None
    assert cast.owner_of("mine") == 1

    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone", "profile_id": 2})
    assert c.post("/api/cast/devices/mine/command", json={"type": "stop", "sender_id": "hers"}).status_code == 200


def test_a_phone_never_used_as_anyone_is_nobodys():
    c = _client()
    c.post("/api/cast/hello", json={"id": "new", "name": "iPhone", "kind": "phone"})
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone", "profile_id": 1})
    assert c.get("/api/cast/devices", params={"exclude": "mine"}).json()["devices"] == []


def test_a_tv_is_shared_until_the_admin_gives_it_to_a_profile():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})
    assert cast.owner_of("tv") is None
    assert c.post("/api/cast/devices/tv/command", json={"type": "stop", "sender_id": "hers"}).status_code == 200

    cast.set_owner("tv", 1)
    assert c.post("/api/cast/devices/tv/command", json={"type": "stop", "sender_id": "hers"}).status_code == 403
    cast._NAMES = None
    cast.DEVICES.clear()
    assert cast.kind_of("tv") == "tv" and cast.owner_of("tv") == 1
    off = next(d for d in cast.known_devices() if d["id"] == "tv")
    assert (off["kind"], off["own_name"], off["online"]) == ("tv", "TV", False)
    cast.set_owner("tv", None)
    assert cast.owner_of("tv") is None

    with pytest.raises(cast.Personal):
        cast.set_owner("hers", 1)
    assert cast.owner_of("hers") == 2


def test_a_play_names_only_the_senders_own_profile():
    c = _client()
    c.post("/api/cast/hello", json={"id": "tv", "name": "TV", "kind": "tv"})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})
    play = {"type": "play", "play_id": "12", "sender_id": "hers"}
    assert c.post("/api/cast/devices/tv/command", json={**play, "profile_id": 1}).status_code == 403
    assert c.post("/api/cast/devices/tv/command", json={**play, "profile_id": 2}).status_code == 200
    assert c.post("/api/cast/devices/tv/command", json={"type": "play", "play_id": "12", "profile_id": 1}).status_code == 403


def _bound(c, device_id, kind="phone", profile_id=None, **headers):
    body = {"id": device_id, "name": device_id, "kind": kind, "profile_id": profile_id}
    token = c.post("/api/cast/hello", json=body).json()["token"]
    assert c.post("/api/cast/hello", json=body,
                  headers={"X-Cast-Token": token, **headers}).status_code == 200
    return token


def test_a_device_id_answers_only_to_its_token_once_it_has_one():
    c = _client()
    tv = {"id": "tv", "name": "TV", "kind": "tv"}
    first = c.post("/api/cast/hello", json=tv).json()
    assert first["token"]
    # An app without token support never sends one.
    again = c.post("/api/cast/hello", json=tv).json()
    assert again["token"] == first["token"]
    assert c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}).status_code == 200

    mine = {"X-Cast-Token": first["token"]}
    assert c.post("/api/cast/hello", json=tv, headers=mine).status_code == 200
    for headers in ({}, {"X-Cast-Token": "guess"}):
        assert c.post("/api/cast/hello", json=tv, headers=headers).status_code == 403
        assert c.get("/api/cast/inbox", params={"id": "tv", "wait": 0},
                     headers=headers).status_code == 403
        assert c.post("/api/cast/state", json={"id": "tv", "playing": None},
                      headers=headers).status_code == 403
    assert c.get("/api/cast/inbox", params={"id": "tv", "wait": 0}, headers=mine).status_code == 200

    cast._NAMES = None
    cast.DEVICES.clear()
    assert c.post("/api/cast/hello", json=tv).status_code == 403
    assert c.post("/api/cast/hello", json=tv, headers=mine).status_code == 200


def test_a_sender_is_who_it_says_only_with_its_token():
    c = _client()
    token = _bound(c, "mine", profile_id=1)
    c.post("/api/cast/hello", json={"id": "pad", "name": "iPad", "kind": "tablet", "profile_id": 1})
    play = {"type": "play", "play_id": "12", "sender_id": "mine", "profile_id": 1}
    assert c.post("/api/cast/devices/pad/command", json=play).status_code == 403
    assert c.post("/api/cast/devices/pad/command", json=play,
                  headers={"X-Cast-Token": "guess"}).status_code == 403
    assert c.post("/api/cast/devices/pad/command", json=play,
                  headers={"X-Cast-Token": token}).status_code == 200
    assert c.get("/api/cast/devices", params={"exclude": "mine"}).json()["devices"] == []
    listed = c.get("/api/cast/devices", params={"exclude": "mine"},
                   headers={"X-Cast-Token": token}).json()["devices"]
    assert [d["id"] for d in listed] == ["pad"]


def test_one_device_is_shown_only_to_who_may_see_it_in_the_list():
    c = _client()
    c.post("/api/cast/hello", json={"id": "mine", "name": "iPhone", "kind": "phone", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "pad", "name": "iPad", "kind": "tablet", "profile_id": 1})
    c.post("/api/cast/hello", json={"id": "hers", "name": "iPhone", "kind": "phone", "profile_id": 2})
    assert c.get("/api/cast/devices/mine").status_code == 404
    assert c.get("/api/cast/devices/mine", params={"sender_id": "hers"}).status_code == 404
    assert c.get("/api/cast/devices/mine", params={"sender_id": "pad"}).status_code == 200
    assert c.get("/api/cast/devices/mine", params={"sender_id": "mine"}).status_code == 200


def test_saying_hello_as_a_profile_with_a_pin_wants_the_pin():
    from vibestream.db import session_scope
    from vibestream.models import Profile
    from vibestream.routers import profiles

    c = _client()
    profiles._FAILURES.clear()
    with session_scope() as s:
        locked = Profile(name="Locked", pin_hash=profiles.hash_pin("2468"))
        s.add(locked)
        s.flush()
        pid = locked.id
    body = {"id": "ph", "name": "iPhone", "kind": "phone", "profile_id": pid}
    reply = c.post("/api/cast/hello", json=body).json()
    assert reply["profile_id"] is None and reply["pin_required"] is True
    assert cast.owner_of("ph") is None
    token = reply["token"]
    mine = {"X-Cast-Token": token}
    assert c.post("/api/cast/hello", json=body,
                  headers={**mine, "X-Profile-Pin": "1111"}).status_code == 403
    granted = c.post("/api/cast/hello", json=body, headers={**mine, "X-Profile-Pin": "2468"}).json()
    assert granted["profile_id"] == pid and cast.owner_of("ph") == pid
    cast._NAMES = None
    cast.DEVICES.clear()
    assert c.post("/api/cast/hello", json=body, headers=mine).json()["profile_id"] == pid
    other = c.post("/api/cast/hello", json={**body, "id": "other"}).json()
    assert other["profile_id"] is None
