from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Base, Media, Torrent  # noqa: E402
from vibestream.services import spoken  # noqa: E402

TITLES = ["The Shawshank Redemption", "Inception", "Star Wars", "Star Wars: The Last Jedi",
          "Toy Story 2", "Breaking Bad", "Amélie", "Fast & Furious"]


def _session():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    for index, title in enumerate(TITLES, start=1):
        media = Media(title=title, media_type="movie", enrich_status="ok")
        session.add(media)
        session.flush()
        session.add(Torrent(id=index, name=title.replace(" ", "."), parsed_title=title, media_id=media.id))
    session.add(Torrent(id=99, name="Obscure.Doc.2024.1080p", parsed_title="Obscure Doc", media_id=None))
    session.commit()
    spoken.forget_pool()
    return session


def term(session, *heard):
    return spoken.meant(session, list(heard))["term"]


def test_the_words_around_a_title_are_taken_off():
    assert spoken.clean("Search for the movie Inception please") == "inception"
    assert spoken.clean("hey can you play breaking bad season two") == "breaking bad"
    assert spoken.clean("I want to watch Toy Story 2") == "toy story 2"


def test_a_misheard_title_is_the_title_it_nearly_is():
    s = _session()
    assert term(s, "search for the shaw shank redemption") == "The Shawshank Redemption"
    assert term(s, "play in ception") == "Inception"
    assert term(s, "toy story two") == "Toy Story 2"
    assert term(s, "amelie") == "Amélie"
    assert term(s, "fast and furious") == "Fast & Furious"
    assert term(s, "obscure dock") == "Obscure Doc"


def test_part_of_a_title_is_kept_so_every_match_is_found():
    s = _session()
    assert term(s, "star wars movies") == "Star Wars"
    assert term(s, "the last jedi") == "the last jedi"


def test_an_alternative_reading_can_be_the_one_that_matches():
    s = _session()
    assert term(s, "breaking bat cave thing", "breaking bad") == "Breaking Bad"


def test_nothing_like_any_title_goes_through_cleaned():
    s = _session()
    assert term(s, "search for something completely different") == "something completely different"
    assert term(s, "search for") == ""
    assert spoken.meant(s, [])["term"] == ""
