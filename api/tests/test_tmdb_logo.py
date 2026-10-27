from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services import tmdb  # noqa: E402


def details(*logos):
    return {"images": {"logos": list(logos)}}


def test_english_before_no_language_before_the_rest():
    found = tmdb._logo(details(
        {"iso_639_1": None, "file_path": "/plain.png", "vote_average": 9},
        {"iso_639_1": "en", "file_path": "/english.png", "vote_average": 1},
    ))
    assert found == "/english.png"


def test_png_before_svg_then_votes():
    found = tmdb._logo(details(
        {"iso_639_1": "en", "file_path": "/vector.svg", "vote_average": 9},
        {"iso_639_1": "en", "file_path": "/low.png", "vote_average": 2},
        {"iso_639_1": "en", "file_path": "/high.png", "vote_average": 5},
    ))
    assert found == "/high.png"


def test_none_is_an_answer_and_is_recorded():
    assert tmdb._logo({}) is None
    assert tmdb.extract_facts({}, "movie")["logo"] is None
