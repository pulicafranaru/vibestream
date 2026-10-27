from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Episode, Media, Season, utcnow  # noqa: E402
from vibestream.routers.player import next_episode  # noqa: E402


@pytest.fixture
def show():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="A Show", media_type="tv")
    session.add(media)
    session.flush()
    seasons = {}
    for number in (0, 1, 2):
        seasons[number] = Season(media_id=media.id, number=number)
        session.add(seasons[number])
    session.flush()

    def add(season: int, number: int, prepared: bool = True) -> Episode:
        episode = Episode(
            media_id=media.id, season_id=seasons[season].id,
            season_number=season, number=number, name=f"S{season}E{number}",
            prepared_at=utcnow() if prepared else None,
        )
        session.add(episode)
        session.flush()
        return episode

    yield session, add
    session.close()


def test_the_next_episode_in_the_same_season(show):
    session, add = show
    first = add(1, 1)
    second = add(1, 2)
    assert next_episode(session, first)["play_id"] == f"e{second.id}"


def test_the_end_of_a_season_leads_into_the_next_one(show):
    session, add = show
    last = add(1, 6)
    opener = add(2, 1)
    add(2, 2)
    assert next_episode(session, last)["play_id"] == f"e{opener.id}"


def test_a_gap_is_not_jumped(show):
    session, add = show
    first = add(1, 1)
    add(1, 2, prepared=False)
    add(1, 3)
    assert next_episode(session, first) is None


def test_specials_are_not_part_of_the_run(show):
    session, add = show
    finale = add(2, 8)
    add(0, 1)
    assert next_episode(session, finale) is None


def test_the_last_episode_has_no_next(show):
    session, add = show
    assert next_episode(session, add(2, 8)) is None


def test_a_film_has_no_next(show):
    session, _ = show
    assert next_episode(session, None) is None
