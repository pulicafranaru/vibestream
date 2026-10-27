from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.routers import catalog  # noqa: E402


def world():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    titles = [
        ("Heist", "movie", ["Crime", "Thriller"], True),
        ("Laughs", "movie", ["Comedy"], True),
        ("Unreleased", "movie", ["Western"], False),
        ("Detectives", "tv", ["Crime", "Drama"], True),
    ]
    for index, (title, kind, genres, released) in enumerate(titles, start=1):
        media = Media(title=title, media_type=kind, genres=json.dumps(genres))
        session.add(media)
        session.flush()
        if released:
            session.add(Torrent(id=index, name=f"{title}.1080p", media_id=media.id))
    session.commit()
    return session


def test_films_only_and_only_what_can_be_browsed():
    session = world()
    found = catalog.genres(session=session, media_type="movie", order="name")
    assert [g["name"] for g in found] == ["Comedy", "Crime", "Thriller"]


def test_shows_count_their_own():
    session = world()
    found = catalog.genres(session=session, media_type="tv", order="popular")
    assert {g["name"]: g["count"] for g in found} == {"Crime": 1, "Drama": 1}
