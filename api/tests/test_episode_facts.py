from __future__ import annotations

from vibestream.services.shows import episode_facts


def test_directors_writers_and_guest_stars_in_billing_order():
    item = {
        "crew": [
            {"id": 1, "name": "Ann Director", "job": "Director"},
            {"id": 2, "name": "Bo Writer", "job": "Writer"},
            {"id": 3, "name": "Cy Teleplay", "job": "Teleplay"},
            {"id": 2, "name": "Bo Writer", "job": "Story"},
            {"id": 4, "name": "Di Editor", "job": "Editor"},
        ],
        "guest_stars": [
            {"id": 6, "name": "Second Guest", "character": "Spock", "order": 2},
            {"id": 5, "name": "First Guest", "character": "", "order": 1},
        ],
    }
    facts = episode_facts(item)
    assert facts["directors"] == ["Ann Director"]
    assert facts["writers"] == ["Bo Writer", "Cy Teleplay"]
    assert facts["guest_stars"] == [
        {"name": "First Guest", "character": None},
        {"name": "Second Guest", "character": "Spock"},
    ]
    assert facts["person_ids"] == {
        "Ann Director": 1, "Bo Writer": 2, "Cy Teleplay": 3, "First Guest": 5, "Second Guest": 6,
    }


def test_an_episode_without_credits_has_empty_lists():
    assert episode_facts({}) == {"directors": [], "writers": [], "guest_stars": [], "person_ids": {}}


def test_an_episode_is_described_by_id_whether_or_not_it_is_here():
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from vibestream.db import init_db, session_scope
    from vibestream.models import Episode, Media, Season
    from vibestream.routers import catalog

    init_db()
    with session_scope() as s:
        media = Media(title="Test Show", media_type="tv")
        s.add(media)
        s.flush()
        season = Season(media_id=media.id, number=1)
        s.add(season)
        s.flush()
        episode = Episode(media_id=media.id, season_id=season.id, season_number=1, number=2,
                          name="Second", air_date="2020-01-08", runtime=44,
                          facts=json.dumps({"directors": ["Ann"], "writers": [], "guest_stars": [],
                                            "person_ids": {"Ann": 1}}))
        s.add(episode)
        s.flush()
        episode_id = episode.id

    app = FastAPI()
    app.include_router(catalog.router)
    body = TestClient(app).get(f"/api/catalog/episodes/{episode_id}/about").json()
    assert (body["number"], body["name"], body["directors"], body["runtime"]) == (2, "Second", ["Ann"], 44)
    assert TestClient(app).get("/api/catalog/episodes/999999/about").status_code == 404
