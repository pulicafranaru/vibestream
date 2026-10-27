"""Without VIDEO-RANGE or FRAME-RATE in the master, AVFoundation refuses the variant (-12927, -12646)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.hls import master_playlist  # noqa: E402
from vibestream.services.mediainfo import MediaInfo, VideoStream  # noqa: E402


def info(*, transfer, hdr):
    media = MediaInfo(
        path="/data/x.mkv", container="matroska,webm",
        duration=9545.7, bitrate=28_143_362,
    )
    media.video = VideoStream(
        index=0, codec="hevc", profile="Main 10", width=3836, height=2074,
        pix_fmt="yuv420p10le", bit_depth=10, frame_rate=23.976,
        is_hdr=hdr, is_dolby_vision=False, color_transfer=transfer,
    )
    return media


def stream_inf(playlist):
    return next(l for l in playlist.splitlines() if l.startswith("#EXT-X-STREAM-INF"))


def test_pq_is_declared_for_hdr10():
    line = stream_inf(master_playlist(info(transfer="smpte2084", hdr=True), "/api/play/11"))
    assert "VIDEO-RANGE=PQ" in line


def test_hlg_is_declared_separately():
    line = stream_inf(master_playlist(info(transfer="arib-std-b67", hdr=True), "/api/play/11"))
    assert "VIDEO-RANGE=HLG" in line


def test_sdr_is_declared_for_ordinary_video():
    line = stream_inf(master_playlist(info(transfer="bt709", hdr=False), "/api/play/11"))
    assert "VIDEO-RANGE=SDR" in line


def test_hdr_without_a_transfer_curve_is_still_not_sdr():
    """bt2020 primaries alone set is_hdr, and PQ is the safer of the two."""
    line = stream_inf(master_playlist(info(transfer=None, hdr=True), "/api/play/11"))
    assert "VIDEO-RANGE=PQ" in line


def test_frame_rate_is_declared():
    line = stream_inf(master_playlist(info(transfer="smpte2084", hdr=True), "/api/play/11"))
    assert "FRAME-RATE=23.976" in line


def test_frame_rate_is_omitted_rather_than_invented():
    """An absent frame rate is a probe that came back short, not 0 fps."""
    media = info(transfer="bt709", hdr=False)
    media.video.frame_rate = None
    assert "FRAME-RATE" not in stream_inf(master_playlist(media, "/api/play/11"))


def test_subtitles_do_not_displace_the_video_attributes():
    tracks = [{"id": "emb4", "label": "English", "language": "en", "default": True}]
    line = stream_inf(
        master_playlist(info(transfer="smpte2084", hdr=True), "/api/play/11", tracks)
    )
    assert "VIDEO-RANGE=PQ" in line
    assert "FRAME-RATE=23.976" in line
    assert line.endswith('SUBTITLES="subs"')


def test_the_chosen_audio_track_reaches_the_variant():
    media = info(transfer="smpte2084", hdr=True)
    assert master_playlist(media, "/api/play/11").splitlines()[-1] == "/api/play/11/index.m3u8"
    chosen = master_playlist(media, "/api/play/11", query="?audio=2")
    assert chosen.splitlines()[-1] == "/api/play/11/index.m3u8?audio=2"
