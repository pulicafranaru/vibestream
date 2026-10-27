from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import (  # noqa: E402
    Base, Download, Episode, EpisodeProgress, Media, Profile, Season, Torrent, utcnow,
)
from vibestream.services.plan import show_plan  # noqa: E402


@pytest.fixture
def show(monkeypatch):
    from vibestream.services import downloads as dl_service

    monkeypatch.setattr(dl_service, "cached_meta", lambda _id: None)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    media = Media(title="A Show", media_type="tv")
    profile = Profile(name="Someone")
    session.add_all([media, profile])
    session.flush()
    episodes = {}
    for number, count in ((1, 4), (2, 2)):
        season = Season(media_id=media.id, number=number, episode_count=count,
                        synced_at=utcnow())
        session.add(season)
        session.flush()
        for slot in range(1, count + 1):
            episode = Episode(media_id=media.id, season_id=season.id,
                              season_number=number, number=slot, name=f"E{slot}",
                              air_date="2008-01-20")
            session.add(episode)
            episodes[(number, slot)] = episode
    session.add_all([
        Torrent(id=100, name="A.Show.S01.1080p", media_id=media.id, season=1,
                size_bytes=8 * 1024 ** 3, seeders=10),
        Torrent(id=101, name="A.Show.S01E04.1080p", media_id=media.id, season=1,
                episode=4, size_bytes=2 * 1024 ** 3, seeders=10),
        Torrent(id=102, name="A.Show.S02.1080p", media_id=media.id, season=2,
                size_bytes=4 * 1024 ** 3, seeders=10),
    ])
    session.commit()

    def hold(*slots, prepared=True):
        for slot in slots:
            episodes[slot].file_path = f"/x/{slot}.mkv"
            episodes[slot].prepared_at = utcnow() if prepared else None
        session.commit()

    def watch(*slots):
        for slot in slots:
            session.add(EpisodeProgress(
                profile_id=profile.id, episode_id=episodes[slot].id,
                runtime_seconds=2400.0, finished_at=utcnow(), updated_at=utcnow(),
            ))
        session.commit()

    def plan(downloads=None):
        return asyncio.run(show_plan(session, media, profile.id, downloads or {}))

    yield session, episodes, hold, watch, plan
    session.close()


def test_nothing_here_asks_what_to_get_first_episode_first(show):
    _, episodes, _, _, plan = show
    result = plan()
    assert result["primary"] == {"action": "choose"}
    kinds = [o["kind"] for o in result["offers"]]
    assert kinds == ["episode", "season", "series"]
    first = result["offers"][0]
    assert first["title"] == "Episode 1"
    assert first["fetch"] == [{"release_id": 100, "episode_id": episodes[(1, 1)].id}]
    assert (first["size_gb"], first["size_exact"]) == (2.0, False)
    assert result["offers"][1]["fetch"] == [{"release_id": 100, "all": False}]
    assert [f["release_id"] for f in result["offers"][2]["fetch"]] == [100, 102]


def test_an_unwatched_episode_here_is_played(show):
    _, _, hold, watch, plan = show
    hold((1, 1), (1, 2), (1, 3))
    watch((1, 1))
    primary = plan()["primary"]
    assert (primary["action"], primary["label"]) == ("play", "S1:E2")


def test_one_still_being_prepared_says_so(show):
    _, _, hold, watch, plan = show
    hold((1, 1))
    hold((1, 2), prepared=False)
    watch((1, 1))
    primary = plan()["primary"]
    assert (primary["action"], primary["label"]) == ("preparing", "S1:E2")


def test_all_watched_offers_the_next_episode(show):
    _, _, hold, watch, plan = show
    hold((1, 1), (1, 2), (1, 3))
    watch((1, 1), (1, 2), (1, 3))
    result = plan()
    primary = result["primary"]
    assert (primary["action"], primary["label"]) == ("download", "S1:E4")
    assert primary["offer"]["fetch"] == [{"release_id": 101, "episode_id": None}]
    assert result["offers"][0]["title"] == "Next Episode"


def test_the_next_one_on_its_way_shows_its_progress(show):
    session, _, hold, watch, plan = show
    hold((1, 1), (1, 2), (1, 3))
    watch((1, 1), (1, 2), (1, 3))
    download = Download(torrent_id=101, state="downloading", progress=0.4)
    session.add(download)
    session.commit()
    primary = plan({101: download})["primary"]
    assert (primary["action"], primary["label"], primary["torrent_id"]) == (
        "downloading", "S1:E4", 101,
    )


def test_everything_watched_and_nothing_more_rewatches_from_the_start(show):
    _, _, hold, watch, plan = show
    every = [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2)]
    hold(*every)
    watch(*every)
    primary = plan()["primary"]
    assert (primary["action"], primary["label"]) == ("rewatch", "S1:E1")


def test_after_a_season_the_next_season_is_next(show):
    _, _, hold, watch, plan = show
    season_one = [(1, 1), (1, 2), (1, 3), (1, 4)]
    hold(*season_one)
    watch(*season_one)
    result = plan()
    assert result["primary"]["label"] == "S2:E1"
    assert result["offers"][1]["title"] == "Season 2"
