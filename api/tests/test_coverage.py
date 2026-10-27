from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.services import coverage, rows  # noqa: E402

LONG_RUNNER = {"season_episodes": {"0": 7, "1": 22, "2": 22, "3": 5},
               "last_aired": [3, 5], "seasons": 3, "episodes": 49}


def test_season_packs_cover_their_seasons_and_episodes_count_one_each():
    releases = [(1, None, None), (2, None, None), (3, None, 1), (3, None, 2)]
    assert coverage.coverage(LONG_RUNNER, releases) == (22 + 22 + 2) / 49


def test_episodes_not_aired_yet_do_not_count_against_a_show():
    facts = {**LONG_RUNNER, "season_episodes": {"1": 22, "2": 22, "3": 10}}
    releases = [(1, 2, None), *[(3, None, n) for n in range(1, 6)]]
    assert coverage.coverage(facts, releases) == 1.0


def test_a_handful_of_episodes_of_a_long_show_is_next_to_nothing():
    facts = {"season_episodes": {str(n): 22 for n in range(1, 27)}, "last_aired": [26, 5]}
    releases = [(26, None, 1), (26, None, 2)]
    assert coverage.coverage(facts, releases) < 0.01


def test_a_release_with_no_season_is_the_whole_show():
    assert coverage.coverage(LONG_RUNNER, [(None, None, None)]) == 1.0


def test_without_the_season_list_the_totals_are_spread_evenly():
    facts = {"seasons": 2, "episodes": 20}
    assert coverage.coverage(facts, [(1, None, None)]) == 0.5


def test_the_genre_row_puts_a_complete_show_before_a_more_popular_fragment():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    fragment = Media(title="Fragment", media_type="tv", enrich_status="ok", poster_path="/f.jpg",
                     popularity=430.0, genres=json.dumps(["Drama"]),
                     facts=json.dumps({"season_episodes": {str(n): 22 for n in range(1, 27)},
                                       "last_aired": [26, 5]}))
    complete = Media(title="Complete", media_type="tv", enrich_status="ok", poster_path="/c.jpg",
                     popularity=60.0, genres=json.dumps(["Drama"]),
                     facts=json.dumps({"season_episodes": {"1": 10, "2": 10}, "last_aired": [2, 10]}))
    film = Media(title="Film", media_type="movie", enrich_status="ok", poster_path="/m.jpg",
                 popularity=100.0, genres=json.dumps(["Drama"]))
    session.add_all([fragment, complete, film])
    session.flush()
    session.add_all([
        Torrent(id=1, name="Fragment.S26E01.1080p", media_id=fragment.id, season=26, episode=1),
        Torrent(id=2, name="Fragment.S26E02.1080p", media_id=fragment.id, season=26, episode=2),
        Torrent(id=3, name="Complete.S01-S02.1080p", media_id=complete.id, season=1, season_end=2),
        Torrent(id=4, name="Film.2024.1080p", media_id=film.id),
    ])
    session.commit()

    coverage.refresh(session)
    assert complete.coverage == 1.0 and fragment.coverage < 0.01

    order = [media.title for media, _ in rows.by_genre(session, "Drama")]
    assert order == ["Film", "Complete", "Fragment"]


def test_the_popular_sort_fills_a_page_however_many_releases_a_show_has():
    from vibestream.routers.catalog import _browse_query, _page

    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    shows = [Media(title=f"Show {n}", media_type="tv", enrich_status="ok", popularity=100.0 - n,
                   coverage=1.0, genres=json.dumps(["Drama"])) for n in range(5)]
    session.add_all(shows)
    session.flush()
    tid = 0
    for show in shows:
        for episode in range(1, (300 if show is shows[0] else 2) + 1):
            tid += 1
            session.add(Torrent(id=tid, name=f"{show.title}.S01E{episode:02d}", media_id=show.id,
                                season=1, episode=episode))
    session.commit()

    query = _browse_query(None, None, None, "tv", "Drama", None, None)
    cards, _total = _page(session, query, "popular", 4, 0)
    assert [card["title"] for card in cards] == ["Show 0", "Show 1", "Show 2", "Show 3"]


def test_recently_added_leaves_out_a_show_the_tracker_has_little_of():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    from datetime import timedelta

    from vibestream.models import utcnow

    fragment = Media(title="FBI", media_type="tv", enrich_status="ok", poster_path="/f.jpg", coverage=0.02)
    complete = Media(title="Adults", media_type="tv", enrich_status="ok", poster_path="/a.jpg", coverage=1.0)
    session.add_all([fragment, complete])
    session.flush()
    session.add_all([
        Torrent(id=1, name="FBI.S08E05", media_id=fragment.id, season=8, episode=5, upload_date=utcnow()),
        Torrent(id=2, name="Adults.S01", media_id=complete.id, season=1,
                upload_date=utcnow() - timedelta(days=1)),
    ])
    session.commit()
    assert [m.title for m, _ in rows.recently_added(session, "tv")] == ["Adults"]
