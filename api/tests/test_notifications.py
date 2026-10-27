from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Download, Media, Torrent, utcnow  # noqa: E402
from vibestream.routers.notifications import notifications  # noqa: E402


def make_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_ready_failed_and_new_arrivals_newest_first():
    session = make_session()
    now = utcnow()
    film = Media(title="A Film", media_type="movie", backdrop_path="/f.jpg",
                 created_at=now - timedelta(days=60))
    broken = Media(title="Broken", media_type="movie", backdrop_path="/b.jpg",
                   created_at=now - timedelta(days=60))
    fresh = Media(title="Fresh", media_type="movie", backdrop_path="/n.jpg",
                  popularity=50.0, created_at=now - timedelta(hours=2))
    session.add_all([film, broken, fresh])
    session.flush()
    session.add_all([
        Torrent(id=1, name="A.Film.2026.1080p", media_id=film.id),
        Torrent(id=2, name="Broken.2026.1080p", media_id=broken.id),
    ])
    session.flush()
    session.add_all([
        Download(torrent_id=1, state="linked", prepared_at=now - timedelta(days=1)),
        Download(torrent_id=2, state="linked", prepare_error="disk full",
                 completed_at=now - timedelta(days=3)),
    ])
    session.commit()

    items = notifications(limit=20, session=session)["items"]
    assert [(i["kind"], i["text"]) for i in items] == [
        ("new", "Fresh"), ("ready", "A Film"), ("failed", "Broken"),
    ]
    assert items[2]["heading"] == "Couldn't Prepare"


def test_old_and_removed_things_are_not_news():
    session = make_session()
    now = utcnow()
    media = Media(title="Old", media_type="movie", backdrop_path="/o.jpg",
                  created_at=now - timedelta(days=60))
    session.add(media)
    session.flush()
    session.add_all([Torrent(id=1, name="Old.1080p", media_id=media.id),
                     Torrent(id=2, name="Gone.1080p", media_id=media.id)])
    session.flush()
    session.add_all([
        Download(torrent_id=1, state="linked", prepared_at=now - timedelta(days=45)),
        Download(torrent_id=2, state="removed", prepared_at=now - timedelta(days=1),
                 reaped_at=now),
    ])
    session.commit()
    assert notifications(limit=20, session=session)["items"] == []


def test_low_space_is_dated_from_when_it_began(monkeypatch):
    from vibestream.services import sources

    session = make_session()
    free = [10 * 1024 ** 3]
    monkeypatch.setattr(sources, "free_bytes", lambda: free[0])
    monkeypatch.setattr(sources, "floor_bytes", lambda: 50 * 1024 ** 3)

    def low():
        return [i for i in notifications(limit=20, session=session)["items"] if i["kind"] == "space"]

    first = low()
    assert len(first) == 1
    assert low()[0]["at"] == first[0]["at"]

    free[0] = 100 * 1024 ** 3
    assert low() == []
    free[0] = 10 * 1024 ** 3
    assert low()[0]["at"] > first[0]["at"]
