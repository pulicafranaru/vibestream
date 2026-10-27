from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent, utcnow  # noqa: E402
from vibestream.routers.catalog import _browse_query, _page  # noqa: E402


def test_the_title_beats_a_newer_release_that_only_contains_the_words():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    now = utcnow()
    shows = [
        ("The Simpsons", "The.Simpsons.S37E04.The.Boy.In.The.Bubble.1080p", now),
        ("Mad About the Boy in Paris", "Mad.About.the.Boy.in.Paris.2025.1080p", now - timedelta(days=1)),
        ("The Boy in the Striped Pyjamas", "The.Boy.in.the.Striped.Pajamas.2008.1080p", now - timedelta(days=900)),
    ]
    for index, (title, name, when) in enumerate(shows, start=1):
        media = Media(title=title, media_type="movie", enrich_status="ok")
        session.add(media)
        session.flush()
        session.add(Torrent(id=index, name=name, parsed_title=title, media_id=media.id, upload_date=when))
    session.commit()

    query = _browse_query("the boy in", None, None, None, None, None, None)
    cards, _total = _page(session, query, "newest", 10, 0, "the boy in")
    assert [card["title"] for card in cards] == [
        "The Boy in the Striped Pyjamas", "Mad About the Boy in Paris", "The Simpsons",
    ]
