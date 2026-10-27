from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media  # noqa: E402
from vibestream.services.filelist import upsert_torrent  # noqa: E402


def test_a_release_of_a_title_already_here_is_linked_at_once():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    film = Media(title="Night of the Living Dead", year=1968, media_type="movie",
                 imdb_id="tt0063350", tmdb_id=10331)
    session.add(film)
    session.commit()

    row, created = upsert_torrent(session, {
        "id": 943249, "name": "Night.of.the.Living.Dead.1968.1080p.Blu-ray.AVC.LPCM.2.0-MONUMENT",
        "category": 20, "imdb": "tt0063350", "size": 40_000_000_000, "seeders": 4,
    })
    assert created and row.media_id == film.id

    stranger, _ = upsert_torrent(session, {
        "id": 943250, "name": "Some.Other.Film.2020.1080p", "category": 4, "imdb": "tt9999999",
    })
    assert stranger.media_id is None
