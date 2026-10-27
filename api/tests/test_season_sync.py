from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Season  # noqa: E402
from vibestream.services import shows  # noqa: E402


class FakeTMDB:
    async def tv_season(self, tmdb_id, number):
        return {"episodes": [
            {"episode_number": 1, "id": 11, "name": "One"},
            {"episode_number": 2, "id": 12, "name": "Two"},
        ]}


def test_the_first_answer_has_the_episodes(monkeypatch):
    # As the app's own sessions are: nothing is reloaded on commit.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    media = Media(title="Show", media_type="tv", tmdb_id=99)
    session.add(media)
    session.flush()
    session.add(Season(media_id=media.id, number=3))
    session.commit()
    monkeypatch.setattr(shows, "TMDBClient", FakeTMDB)

    season = asyncio.run(shows.sync_episodes(session, media, 3))
    assert [e.name for e in sorted(season.episodes, key=lambda e: e.number)] == ["One", "Two"]
