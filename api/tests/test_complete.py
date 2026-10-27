from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Media  # noqa: E402
from vibestream.schemas import media_card  # noqa: E402


def card(media_type, coverage):
    return media_card(Media(id=1, title="T", media_type=media_type, coverage=coverage), [], {})


def test_a_show_with_every_episode_is_complete():
    assert card("tv", 1.0)["complete"] is True
    assert card("tv", 0.985)["complete"] is True


def test_a_show_missing_episodes_or_unmeasured_is_not():
    assert card("tv", 0.6)["complete"] is False
    assert card("tv", None)["complete"] is False


def test_a_film_is_never_called_complete():
    assert card("movie", 1.0)["complete"] is False
