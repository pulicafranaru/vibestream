from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.routers import catalog  # noqa: E402
from vibestream.services import tmdb  # noqa: E402


class FakeTMDB:
    async def person(self, person_id):
        return {"name": "Kathy Bates", "profile_path": "/k.jpg", "combined_credits": {
            "cast": [{"id": 100, "media_type": "tv"}, {"id": 200, "media_type": "movie"},
                     {"id": 300, "media_type": "movie"}],
            "crew": [{"id": 400, "media_type": "movie"}],
        }}


def test_lists_the_titles_the_catalog_can_download_most_popular_first(monkeypatch):
    monkeypatch.setattr(tmdb, "TMDBClient", FakeTMDB)
    monkeypatch.setattr(type(catalog.settings), "tmdb_configured", property(lambda _s: True))
    catalog._people.clear()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    rows = [
        (1, "Matlock", "tv", 100, 50.0, True),
        (2, "Misery", "movie", 200, 80.0, True),
        (3, "Not uploaded", "movie", 300, 99.0, False),
        (4, "Directed", "movie", 400, 10.0, True),
        (5, "Same id, other kind", "tv", 200, 99.0, True),
    ]
    for id, title, kind, tmdb_id, popularity, released in rows:
        session.add(Media(id=id, title=title, media_type=kind, tmdb_id=tmdb_id,
                          popularity=popularity, coverage=1.0 if kind == "tv" else None))
        if released:
            session.add(Torrent(id=id * 10, name=title, media_id=id, size_bytes=1))
    session.commit()

    page = asyncio.run(catalog.person(5951, session))
    assert page["name"] == "Kathy Bates"
    assert [c["title"] for c in page["items"]] == ["Misery", "Matlock", "Directed"]
