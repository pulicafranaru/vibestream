from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Episode, EpisodeProgress, Media, Profile, Season, utcnow  # noqa: E402
from vibestream.services.nextup import next_up  # noqa: E402


@pytest.fixture
def show():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    media = Media(title="A Show", media_type="tv")
    profile = Profile(name="Someone")
    session.add_all([media, profile])
    session.flush()
    season = Season(media_id=media.id, number=1)
    session.add(season)
    session.flush()
    episodes = []
    for number in range(1, 5):
        episode = Episode(media_id=media.id, season_id=season.id, season_number=1,
                          number=number, name=f"E{number}", runtime=40,
                          prepared_at=utcnow() if number != 4 else None)
        session.add(episode)
        episodes.append(episode)
    session.flush()

    def watch(index: int, seconds: float, finished: bool = False):
        session.add(EpisodeProgress(
            profile_id=profile.id, episode_id=episodes[index].id,
            resume_seconds=0.0 if finished else seconds, runtime_seconds=2400.0,
            finished_at=utcnow() if finished else None, updated_at=utcnow(),
        ))
        session.flush()

    yield session, media, profile, episodes, watch
    session.close()


def test_nothing_watched_starts_at_the_first_playable_episode(show):
    session, media, profile, episodes, _ = show
    offer = next_up(session, media.id, profile.id)
    assert offer["kind"] == "start" and offer["label"] == "S1:E1"


def test_part_way_through_resumes_that_episode(show):
    session, media, profile, episodes, watch = show
    watch(1, 600)
    offer = next_up(session, media.id, profile.id)
    assert (offer["kind"], offer["label"], offer["resume_seconds"]) == ("resume", "S1:E2", 600)
    assert offer["resume_percent"] == 25.0


def test_finishing_an_episode_offers_the_next(show):
    session, media, profile, episodes, watch = show
    watch(0, 0, finished=True)
    offer = next_up(session, media.id, profile.id)
    assert (offer["kind"], offer["label"]) == ("next", "S1:E2")


def test_the_next_episode_not_being_ready_offers_from_the_top_instead(show):
    session, media, profile, episodes, watch = show
    watch(2, 0, finished=True)
    offer = next_up(session, media.id, profile.id)
    assert offer["label"] == "S1:E1" and offer["kind"] == "start"
