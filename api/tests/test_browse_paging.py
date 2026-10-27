from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.routers import catalog  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    yield s
    s.close()


def test_deep_pages_of_shows_are_full(session):
    """A show is a release per episode, so a slab sized by the page runs out before the titles do."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    shows, episodes = 30, 20
    for n in range(shows):
        session.add(Media(id=n + 1, title=f"Show {n}", media_type="tv"))
    release = 0
    for n in range(shows):
        for e in range(episodes):
            release += 1
            session.add(Torrent(id=release, name=f"Show.{n}.S01E{e:02d}", media_id=n + 1,
                                season=1, episode=e, upload_date=start + timedelta(minutes=release)))
    session.commit()

    stmt = lambda: catalog._browse_query(None, None, None, "tv", None, None, None)  # noqa: E731
    seen = []
    for offset in range(0, shows, 5):
        cards, _total = catalog._page(session, stmt(), "newest", 5, offset)
        assert len(cards) == 5, offset
        seen += [card["media_id"] for card in cards]
    assert len(set(seen)) == shows
    cards, _ = catalog._page(session, stmt(), "newest", 5, shows)
    assert cards == []


def test_the_people_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr(catalog, "_people", {})
    monkeypatch.setattr(catalog, "PEOPLE_MAX", 3)
    for person in range(10):
        catalog._remember_person(person, {"name": str(person)})
    assert sorted(catalog._people) == [7, 8, 9]


def test_a_season_tmdb_does_not_have_is_not_asked_about_again_at_once(session, monkeypatch):
    from vibestream.services import shows

    session.add(Media(id=1, title="Show", media_type="tv", tmdb_id=1399))
    session.commit()
    asked = []

    async def sync(_s, _m, number):
        asked.append(number)
        return None

    monkeypatch.setattr(shows, "sync_episodes", sync)
    monkeypatch.setattr(catalog, "_missing_seasons", {})
    monkeypatch.setattr(catalog, "settings",
                        dataclasses.replace(catalog.settings, tmdb_api_key="k", addons_enabled=False))
    for _ in range(3):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(catalog.season_detail(1, 999, None, session))
        assert caught.value.status_code == 404
    assert asked == [999]
