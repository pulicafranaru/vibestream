from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import (  # noqa: E402
    Base, Download, Media, MyListItem, Profile, Torrent, WatchProgress, utcnow,
)
from vibestream.routers import catalog, profiles  # noqa: E402
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


def test_adding_is_per_profile_and_idempotent():
    session, me, other, films = world()
    profiles.add_to_my_list(me.id, films[0].id, session=session)
    profiles.add_to_my_list(me.id, films[0].id, session=session)
    assert profiles.list_my_list(me.id, session=session) == [films[0].id]
    assert profiles.list_my_list(other.id, session=session) == []
    profiles.remove_from_my_list(me.id, films[0].id, session=session)
    assert profiles.list_my_list(me.id, session=session) == []


def test_the_home_row_is_newest_first_and_only_mine():
    session, me, other, films = world()
    now = utcnow()
    session.add_all([
        MyListItem(profile_id=me.id, media_id=films[0].id, added_at=now - timedelta(days=2)),
        MyListItem(profile_id=me.id, media_id=films[2].id, added_at=now),
        MyListItem(profile_id=other.id, media_id=films[1].id, added_at=now),
    ])
    session.commit()
    built = {row.id: row for row in rows.home_rows(session, profile_id=me.id)}
    assert [media.title for media, _ in built["mylist"].items] == ["Third", "First"]


def test_the_screen_says_what_has_been_started():
    session, me, other, films = world()
    for film in films[:2]:
        profiles.add_to_my_list(me.id, film.id, session=session)
    download = Download(torrent_id=1, state="linked")
    session.add(download)
    session.flush()
    session.add(WatchProgress(profile_id=me.id, download_id=download.id, resume_seconds=600))
    session.commit()
    items = catalog.my_list(session=session, profile_id=me.id)["items"]
    assert {item["title"]: item["started"] for item in items} == {"First": True, "Second": False}
