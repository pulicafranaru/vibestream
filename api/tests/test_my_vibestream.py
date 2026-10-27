from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import (  # noqa: E402
    Base, Download, Media, Profile, Rating, Torrent, WatchProgress, utcnow,
)
from vibestream.routers import profiles  # noqa: E402
from vibestream.services import rows  # noqa: E402


def world():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    me, other = Profile(name="me"), Profile(name="other")
    films = [
        Media(title=name, media_type="movie", enrich_status="ok", poster_path=f"/{name}.jpg")
        for name in ("First", "Second", "Third")
    ]
    session.add_all([me, other, *films])
    session.flush()
    for index, film in enumerate(films, start=1):
        session.add(Torrent(id=index, name=f"{film.title}.2026.1080p", media_id=film.id))
    session.commit()
    return session, me, other, films


def watch(session, profile, torrent_id, *, finished=False, when=None):
    download = session.query(Download).filter_by(torrent_id=torrent_id).one_or_none()
    if download is None:
        download = Download(torrent_id=torrent_id, state="linked", prepared_at=utcnow())
        session.add(download)
        session.flush()
    session.add(WatchProgress(
        profile_id=profile.id, download_id=download.id, resume_seconds=600,
        runtime_seconds=6000, finished_at=utcnow() if finished else None,
        updated_at=when or utcnow(),
    ))
    session.commit()


def titles(row_items):
    return [media.title for media, *_ in row_items]


def test_a_profile_speaks_one_of_three_languages():
    session, me, _other, _films = world()
    assert profiles.serialise(me)["language"] == "en"
    unchanged = {"name": None, "avatar": None, "is_kids": None, "x_profile_pin": None}
    assert profiles.update_profile(me.id, **unchanged, language="ro",
                                   session=session)["language"] == "ro"
    with pytest.raises(HTTPException):
        profiles.update_profile(me.id, **unchanged, language="fr", session=session)
    created = profiles.create_profile(name="Guest", avatar="crimson-smile", is_kids=False,
                                      language="de", session=session)
    assert created["language"] == "de"


def test_removing_a_tile_hides_it_until_watched_again():
    session, me, other, films = world()
    watch(session, me, 1, when=utcnow() - timedelta(hours=1))
    watch(session, other, 1, when=utcnow() - timedelta(hours=1))
    assert titles(rows.continue_watching(session, profile_id=me.id)) == ["First"]

    profiles.hide_from_continue(me.id, films[0].id, session=session)
    assert rows.continue_watching(session, profile_id=me.id) == []
    assert titles(rows.continue_watching(session, profile_id=other.id)) == ["First"]

    progress = session.query(WatchProgress).filter_by(profile_id=me.id).one()
    progress.updated_at = utcnow() + timedelta(minutes=1)
    session.commit()
    assert titles(rows.continue_watching(session, profile_id=me.id)) == ["First"]


def test_liked_and_watch_again_are_per_profile_and_newest_first():
    session, me, other, films = world()
    now = utcnow()
    session.add_all([
        Rating(profile_id=me.id, media_id=films[0].id, value=1, updated_at=now - timedelta(days=1)),
        Rating(profile_id=me.id, media_id=films[1].id, value=2, updated_at=now),
        Rating(profile_id=me.id, media_id=films[2].id, value=-1, updated_at=now),
        Rating(profile_id=other.id, media_id=films[2].id, value=1, updated_at=now),
    ])
    session.commit()
    assert titles(rows.liked(session, me.id)) == ["Second", "First"]

    watch(session, me, 3, finished=True)
    watch(session, me, 1, finished=False)
    assert titles(rows.watch_again(session, me.id)) == ["Third"]
    assert rows.watch_again(session, other.id) == []

    built = {row.id for row in rows.mine_rows(session, me.id)}
    assert {"continue", "liked", "watchagain"} <= built
