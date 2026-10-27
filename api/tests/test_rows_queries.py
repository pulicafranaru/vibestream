from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import (  # noqa: E402
    Base, Download, Episode, EpisodeProgress, Media, Profile, Season, Torrent,
    WatchProgress, utcnow,
)
from vibestream.services import rows  # noqa: E402


def _queries(films: int, episodes: int) -> int:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Profile(id=1, name="Me"))
    for n in range(1, films + 1):
        session.add(Media(id=n, title=f"Film {n}", media_type="movie"))
        session.add(Torrent(id=n, name=f"Film.{n}", media_id=n))
        session.add(Download(id=n, torrent_id=n, state="linked", prepared_at=utcnow()))
        session.add(WatchProgress(profile_id=1, download_id=n, resume_seconds=600,
                                  runtime_seconds=6000))
    show = 1000
    session.add(Media(id=show, title="Show", media_type="tv"))
    session.add(Season(id=1, media_id=show, number=1))
    for n in range(1, episodes + 1):
        session.add(Episode(id=n, media_id=show, season_id=1, season_number=1, number=n))
        session.add(EpisodeProgress(profile_id=1, episode_id=n, resume_seconds=5))
    session.commit()
    session.expunge_all()

    count = [0]

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_args):
        count[0] += 1

    rows.continue_watching(session, profile_id=1, limit=40)
    session.close()
    return count[0]


def test_continue_watching_does_not_ask_once_per_title():
    assert _queries(films=3, episodes=3) == _queries(films=15, episodes=30)
