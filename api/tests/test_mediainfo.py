from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.mediainfo import SubtitleStream, VideoStream  # noqa: E402
from vibestream.services.subtitles import (  # noqa: E402
    _track_label,
    normalise_language,
    srt_to_vtt,
)


def video(width, height):
    return VideoStream(
        index=0, codec="hevc", profile="Main 10", width=width, height=height,
        pix_fmt="yuv420p10le", bit_depth=10, frame_rate=24.0,
        is_hdr=True, is_dolby_vision=False,
    )


def test_standard_resolutions():
    assert video(3840, 2160).resolution_label == "2160p"
    assert video(1920, 1080).resolution_label == "1080p"
    assert video(1280, 720).resolution_label == "720p"


def test_letterboxed_film_is_not_downgraded():
    """A 2.35:1 1080p film is 1920x800. Judging by height alone calls it 720p."""
    assert video(1920, 800).resolution_label == "1080p"
    assert video(3840, 1600).resolution_label == "2160p"
    assert video(1280, 534).resolution_label == "720p"


def test_pillarboxed_and_odd_widths():
    assert video(1998, 1080).resolution_label == "1080p"
    assert video(4096, 1716).resolution_label == "2160p"


def sub(codec="subrip", language="eng", title=None, sdh=False, forced=False):
    return SubtitleStream(
        index=2, codec=codec, language=language, title=title,
        is_default=False, is_forced=forced, is_hearing_impaired=sdh,
    )


def test_plain_track_label():
    assert _track_label(sub(), "en") == "English"


def test_sdh_is_not_duplicated():
    assert _track_label(sub(title="SDH", sdh=True), "en") == "English (SDH)"


def test_forced_and_sdh_combine():
    assert _track_label(sub(sdh=True, forced=True), "en") == "English (Forced, SDH)"


def test_meaningful_title_is_kept():
    assert _track_label(sub(title="Signs & Songs"), "en") == "English (Signs & Songs)"


def test_title_restating_language_is_dropped():
    assert _track_label(sub(title="English"), "en") == "English"


def test_generic_title_is_dropped():
    assert _track_label(sub(title="Subtitle"), "en") == "English"


def test_language_normalisation():
    assert normalise_language("eng") == "en"
    assert normalise_language("rum") == "ro"
    assert normalise_language("ron") == "ro"
    assert normalise_language(None) == "und"


def test_srt_to_vtt_conversion():
    srt = "1\n00:00:01,500 --> 00:00:04,000\nHello\n\n"
    vtt = srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:04.000" in vtt


def test_srt_to_vtt_is_idempotent_for_vtt_input():
    vtt = "WEBVTT\n\n00:00:01.500 --> 00:00:04.000\nHello\n"
    assert srt_to_vtt(vtt).count("WEBVTT") == 1
