"""Subtitle labels double as HLS rendition names; AVFoundation refuses duplicates (-17223)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.mediainfo import MediaInfo, SubtitleStream  # noqa: E402
from vibestream.services.subtitles import embedded_tracks  # noqa: E402


def track(index, language, title=None, forced=False, sdh=False):
    return SubtitleStream(
        index=index, codec="subrip", language=language, title=title,
        is_default=False, is_forced=forced, is_hearing_impaired=sdh,
    )


def labels(*streams):
    info = MediaInfo(path="/x.mkv", container="matroska,webm", duration=1.0, bitrate=1)
    info.subtitles = list(streams)
    return [t.label for t in embedded_tracks(info).tracks]


def test_two_untitled_tracks_in_one_language_get_distinct_labels():
    result = labels(track(2, "spa"), track(3, "spa"))
    assert result == ["Spanish", "Spanish 2"]
    assert len(set(result)) == len(result)


def test_a_third_one_keeps_counting():
    result = labels(track(2, "spa"), track(3, "spa"), track(4, "spa"))
    assert result == ["Spanish", "Spanish 2", "Spanish 3"]


def test_tracks_that_already_differ_are_left_alone():
    result = labels(track(2, "spa"), track(3, "spa", sdh=True), track(4, "fre"))
    assert sorted(result) == ["French", "Spanish", "Spanish (SDH)"]


def test_the_suffix_does_not_collide_with_a_real_title():
    result = labels(track(2, "spa"), track(3, "spa", title="Spanish 2"), track(4, "spa"))
    assert len(set(result)) == 3
    assert result[0] == "Spanish"
