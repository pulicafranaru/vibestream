from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.tmdb import extract_facts  # noqa: E402


def test_a_limited_series():
    facts = extract_facts({
        "type": "Miniseries",
        "number_of_seasons": 1,
        "number_of_episodes": 4,
        "created_by": [{"name": "A Creator"}],
        "networks": [{"name": "Netflix"}],
        "aggregate_credits": {"cast": [
            {"name": "Second", "order": 1}, {"name": "Mike Tyson", "order": 0},
        ]},
        "keywords": {"results": [{"name": "boxing"}, {"name": "biography"}]},
        "content_ratings": {"results": [
            {"iso_3166_1": "DE", "rating": "16"}, {"iso_3166_1": "US", "rating": "TV-MA"},
        ]},
    }, "tv")
    assert facts["limited"] is True
    assert facts["cast"] == ["Mike Tyson", "Second"]
    assert facts["crew_heading"] == "Creators" and facts["crew"] == ["A Creator"]
    assert facts["keywords"] == ["boxing", "biography"]
    assert facts["certification"] == "TV-MA"
    assert facts["episodes"] == 4 and facts["networks"] == ["Netflix"]


FILM = {
    "credits": {
        "cast": [{"name": "Lead"}],
        "crew": [{"name": "Writer", "job": "Screenplay"},
                 {"name": "The Director", "job": "Director"}],
    },
    "keywords": {"keywords": [{"name": "heist"}]},
    "release_dates": {"results": [
        {"iso_3166_1": "US", "release_dates": [{"certification": ""},
                                               {"certification": "R"}]},
        {"iso_3166_1": "RO", "release_dates": [{"certification": "N-15"}]},
    ]},
    "production_companies": [{"name": "A Studio"}],
}


def test_a_film():
    facts = extract_facts(FILM, "movie")
    assert facts["crew_heading"] == "Director" and facts["crew"] == ["The Director"]
    assert facts["certification"] == "R"
    assert facts["keywords"] == ["heist"] and facts["studios"] == ["A Studio"]
    assert "limited" not in facts


def test_nothing_known_is_empty_not_an_error():
    facts = extract_facts({}, "movie")
    assert facts["cast"] == [] and facts["certification"] is None
    assert facts["crew_heading"] is None


def test_the_whole_cast_is_kept_for_the_about_tab():
    from vibestream.services.tmdb import extract_facts

    people = [{"name": f"Actor {i}", "order": i} for i in range(20)]
    facts = extract_facts({"credits": {"cast": people}}, "movie")
    assert len(facts["cast"]) == 8
    assert facts["cast_all"] == [f"Actor {i}" for i in range(20)]


def test_the_rating_comes_from_the_regions_set_first():
    from vibestream.config import settings

    saved = settings.rating_regions
    object.__setattr__(settings, "rating_regions", ["RO", "US"])
    try:
        assert extract_facts(FILM, "movie")["certification"] == "N-15"
    finally:
        object.__setattr__(settings, "rating_regions", saved)
