"""Parental controls: adults keep a PIN, the admin makes profiles, kids see up to their ceiling."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.config import settings  # noqa: E402
from vibestream.main import app  # noqa: E402
from vibestream.models import Media, MyListItem, Profile, Torrent  # noqa: E402
from vibestream.routers import admin, profiles  # noqa: E402
from vibestream.services import maturity  # noqa: E402

ADMIN = {"x-vibestream-admin": "1"}


def _film(session, title, certification):
    media = Media(title=title, media_type="movie", enrich_status="ok", poster_path=f"/{title}.jpg",
                  backdrop_path=f"/{title}-b.jpg", overview="x", genres=json.dumps(["Drama"]),
                  facts=json.dumps({"certification": certification}))
    session.add(media)
    session.flush()
    session.add(Torrent(id=5_000_000 + media.id, name=f"{title}.2020.1080p", media_id=media.id, seeders=50,
                        resolution="1080p", origin="addon", info_hash=f"{media.id:040d}"))
    return media


@pytest.fixture
def world():
    db.init_db()
    tag = "Pc" + uuid.uuid4().hex[:6]
    with db.session_scope() as session:
        adult = Profile(name="Parent", pin_hash=profiles.hash_pin("1234"))
        kid = Profile(name="Kid", is_kids=True, max_maturity=13)
        session.add_all([adult, kid])
        cartoon = _film(session, tag + "Cartoon", "G")
        teen = _film(session, tag + "Teen", "PG-13")
        grown = _film(session, tag + "Grown", "R")
        unrated = _film(session, tag + "Unrated", None)
        session.flush()
        session.add(MyListItem(profile_id=kid.id, media_id=grown.id))
        session.add(MyListItem(profile_id=kid.id, media_id=cartoon.id))
        ids = {"tag": tag, "adult": adult.id, "kid": kid.id, "cartoon": cartoon.id, "teen": teen.id,
               "grown": grown.id, "unrated": unrated.id}
    saved = settings.parental_controls
    object.__setattr__(settings, "parental_controls", True)
    app.dependency_overrides[admin.require_admin] = lambda: "token"
    yield ids
    app.dependency_overrides.pop(admin.require_admin, None)
    object.__setattr__(settings, "parental_controls", saved)


def _as(profile_id):
    return {"X-VibeStream-Profile": str(profile_id)}


def _titles(cards, tag="Pc"):
    return sorted(card["title"].replace(tag, "Pc") for card in cards if card["title"].startswith(tag))


def test_certifications_become_ages():
    assert [maturity.age(c) for c in ("G", "TV-Y7", "PG", "PG-13", "TV-14", "15", "R", "TV-MA")] \
        == [0, 7, 10, 13, 14, 15, 17, 18]
    assert maturity.age("FSK 12") == 12 and maturity.age(None) is None and maturity.age("NR") is None
    assert [maturity.age(c) for c in ("AG", "AP", "A.P. - 12", "N - 15", "I.M.-18")] == [0, 12, 12, 15, 18]


def test_the_age_follows_the_facts_whenever_they_are_written(world):
    with db.session_scope() as session:
        media = session.get(Media, world["cartoon"])
        assert media.maturity == 0
        media.facts = json.dumps({"certification": "TV-MA"})
        assert media.maturity == 18


def test_a_kid_searches_and_browses_only_what_is_allowed(world):
    c = TestClient(app)
    kid = c.get("/api/catalog", params={"sort": "title", "q": world["tag"]}, headers=_as(world["kid"])).json()["items"]
    assert _titles(kid, world["tag"]) == ["PcCartoon", "PcTeen"]
    adult = c.get("/api/catalog", params={"sort": "title", "q": world["tag"]}, headers=_as(world["adult"])).json()["items"]
    assert _titles(adult, world["tag"]) == ["PcCartoon", "PcGrown", "PcTeen", "PcUnrated"]
    found = c.get("/api/catalog", params={"q": world["tag"] + "Grown"}, headers=_as(world["kid"])).json()["items"]
    assert found == []


def test_a_title_above_the_ceiling_is_not_there(world):
    c = TestClient(app)
    assert c.get(f"/api/catalog/media/{world['grown']}", headers=_as(world["kid"])).status_code == 404
    assert c.get(f"/api/catalog/media/{world['unrated']}", headers=_as(world["kid"])).status_code == 404
    assert c.get(f"/api/catalog/media/{world['teen']}", headers=_as(world["kid"])).status_code == 200
    assert c.get(f"/api/catalog/media/{world['grown']}", headers=_as(world["adult"])).status_code == 200
    assert c.put(f"/api/profiles/{world['kid']}/my-list/{world['teen']}",
                 headers=_as(world["kid"])).status_code == 200
    assert c.put(f"/api/profiles/{world['kid']}/my-list/{world['unrated']}",
                 headers=_as(world["kid"])).status_code == 404


def test_the_watchlist_keeps_what_is_now_above_the_ceiling_locked(world):
    c = TestClient(app)
    saved = c.get("/api/catalog/my-list", headers=_as(world["kid"])).json()["items"]
    assert {card["title"].replace(world["tag"], "Pc"): card["locked"] for card in saved
            if card["title"].startswith(world["tag"])} == {"PcCartoon": False, "PcGrown": True}
    rows = c.get("/api/catalog/home", headers=_as(world["kid"])).json()
    shown = [card for row in rows["rows"] if row["id"] != "mylist" for card in row["items"]]
    assert "PcGrown" not in _titles(shown, world["tag"]) and not any(card["locked"] for card in shown)
    assert rows["hero"] is None or not rows["hero"]["locked"]


def test_with_parental_controls_off_nothing_is_screened(world):
    object.__setattr__(settings, "parental_controls", False)
    c = TestClient(app)
    kid = c.get("/api/catalog", params={"q": world["tag"]}, headers=_as(world["kid"])).json()["items"]
    assert len(kid) == 4 and not any(card["locked"] for card in kid)


def test_only_the_admin_makes_profiles(world):
    c = TestClient(app)
    assert c.post("/api/profiles", params={"name": "Sneaky"}).status_code == 403
    made = c.post("/api/admin/profiles", json={"name": "Little", "is_kids": True, "max_maturity": 7},
                  headers=ADMIN)
    assert made.status_code == 200 and made.json()["max_maturity"] == 7
    assert c.post("/api/admin/profiles", json={"name": "Odd", "is_kids": True, "max_maturity": 9},
                  headers=ADMIN).status_code == 422
    listed = c.get("/api/profiles").json()
    assert listed["parental_controls"] is True


def test_a_kid_cannot_undo_being_a_kid(world):
    c = TestClient(app)
    kid = world["kid"]
    assert c.patch(f"/api/profiles/{kid}", params={"is_kids": "false"}).status_code == 403
    assert c.delete(f"/api/profiles/{kid}").status_code == 403
    assert c.put(f"/api/profiles/{kid}/pin", json={"pin": "0000"}).status_code == 403
    assert c.patch(f"/api/profiles/{kid}", params={"name": "Kiddo"}).status_code == 200
    assert c.patch(f"/api/admin/profiles/{kid}", json={"max_maturity": 16}, headers=ADMIN).json()["max_maturity"] == 16


def test_adults_keep_a_pin(world):
    c = TestClient(app)
    with db.session_scope() as session:
        bare = Profile(name="NoPin")
        session.add(bare)
        session.flush()
        bare_id = bare.id
    listed = {p["name"]: p for p in c.get("/api/profiles").json()["profiles"]}
    assert listed["NoPin"]["needs_pin"] and not listed["Parent"]["needs_pin"]
    assert not listed["Kid"]["needs_pin"] and not listed["Kid"]["has_pin"]
    assert c.put(f"/api/profiles/{world['adult']}/pin", json={"pin": None, "current": "1234"}).status_code == 422
    assert c.put(f"/api/profiles/{bare_id}/pin", json={"pin": "4321"}).status_code == 200
    assert c.put(f"/api/admin/profiles/{bare_id}/pin", json={"pin": "9999"}, headers=ADMIN).status_code == 200
    assert c.post(f"/api/profiles/{bare_id}/pin/check", json={"pin": "9999"}).status_code == 200
