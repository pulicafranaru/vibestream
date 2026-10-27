from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Event, Media, Season  # noqa: E402
from vibestream.services import filelist  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    yield s
    s.close()


class Tracker:
    def __init__(self, *_a, **_k):
        pass

    async def search(self, query, limit=100):
        raise filelist.FilelistError("tracker down")


def test_a_failed_live_search_leaves_nothing_pending(session, monkeypatch):
    """Pending writes must not hold SQLite's write lock through network calls."""
    monkeypatch.setattr(filelist, "FilelistClient", Tracker)
    result = asyncio.run(filelist.search_live(session, "the tudors"))
    assert result.error
    assert not session.new and not session.in_transaction()
    assert session.query(Event).filter(Event.source == "filelist").count() == 1


def test_a_live_search_leaves_nothing_pending(session, monkeypatch):
    class Empty(Tracker):
        async def search(self, query, limit=100):
            return []

    monkeypatch.setattr(filelist, "FilelistClient", Empty)
    asyncio.run(filelist.search_live(session, "nothing"))
    assert not session.new and not session.in_transaction()


def test_a_season_whose_sync_failed_on_a_write_still_opens(session, monkeypatch):
    from vibestream.routers import catalog
    from vibestream.services import shows

    media = Media(id=1, title="Show", media_type="tv")
    session.add_all([media, Season(media_id=1, number=1)])
    session.commit()

    async def broken(s, m, number):
        s.add(Season(media_id=1, number=1))
        s.flush()

    monkeypatch.setattr(shows, "sync_episodes", broken)
    monkeypatch.setattr(catalog, "settings",
                        dataclasses.replace(catalog.settings, tmdb_api_key="k", addons_enabled=False))
    page = asyncio.run(catalog.season_detail(1, 1, None, session))
    assert page is not None
