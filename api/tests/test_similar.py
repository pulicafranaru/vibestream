from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.routers.catalog import similar  # noqa: E402


def add(session, id, title, kind, genres, keywords=(), torrent=True):
    media = Media(id=id, title=title, media_type=kind, genres=json.dumps(genres),
                  facts=json.dumps({"keywords": list(keywords)}), poster_path="/p.jpg")
    session.add(media)
    if torrent:
        session.add(Torrent(id=id * 10, name=f"{title}.1080p", media_id=id, size_bytes=1))
    return media


def test_ranks_by_what_is_shared_and_skips_what_cannot_be_downloaded():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    add(session, 1, "Heist", "movie", ["Crime", "Thriller"], ["bank robbery"])
    add(session, 2, "Crime only", "movie", ["Crime"])
    add(session, 3, "Same keyword", "movie", ["Crime", "Thriller"], ["bank robbery"])
    add(session, 4, "Comedy", "movie", ["Comedy"])
    add(session, 5, "A show", "tv", ["Crime", "Thriller"])
    add(session, 6, "No release", "movie", ["Crime", "Thriller"], torrent=False)
    session.commit()

    titles = [card["title"] for card in similar(1, 24, session)["items"]]
    assert titles == ["Same keyword", "Crime only"]
