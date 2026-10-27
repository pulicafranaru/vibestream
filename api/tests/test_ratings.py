from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vibestream import db  # noqa: E402
from vibestream.models import Media, Profile, Rating  # noqa: E402
from vibestream.routers import profiles  # noqa: E402


def _profile_and_title():
    db.init_db()
    with db.session_scope() as session:
        profile = Profile(name="Rater")
        media = Media(title="Rated", media_type="movie")
        session.add_all([profile, media])
        session.flush()
        return profile.id, media.id


def test_love_is_refused_and_like_is_kept():
    profile_id, media_id = _profile_and_title()
    app = FastAPI()
    app.include_router(profiles.router)
    client = TestClient(app)
    path = next(r.path for r in app.routes if getattr(r, "name", "") == "set_rating")
    url = path.replace("{profile_id}", str(profile_id)).replace("{media_id}", str(media_id))
    assert client.put(url, params={"value": 2}).status_code == 422
    assert client.put(url, params={"value": 1}).status_code == 200


def test_loves_left_over_become_likes_at_start():
    profile_id, media_id = _profile_and_title()
    with db.session_scope() as session:
        session.add(Rating(profile_id=profile_id, media_id=media_id, value=2))
    db.init_db()
    with db.session_scope() as session:
        assert session.query(Rating).filter_by(media_id=media_id).one().value == 1
