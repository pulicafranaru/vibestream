from __future__ import annotations

from vibestream.services import stills
from vibestream.services.stills import Frame, score


def frame(**overrides) -> Frame:
    base = dict(time=0.0, luma=118.0, low=30.0, high=200.0, saturation=30.0, entropy=0.8, blur=3.0)
    base.update(overrides)
    return Frame(**base)


def test_a_black_frame_is_never_chosen():
    assert score(frame(luma=8.0)) < 0


def test_a_detailed_well_exposed_sharp_frame_beats_the_bad_ones():
    good = score(frame())
    assert good > score(frame(luma=40.0))
    assert good > score(frame(luma=235.0))
    assert good > score(frame(low=100.0, high=130.0))
    assert good > score(frame(entropy=0.3))
    assert good > score(frame(blur=12.0))
    assert good > score(frame(saturation=0.0))


def test_candidates_skip_the_opening_and_the_credits():
    times = stills.candidate_times(3000.0)
    assert len(times) == stills.CANDIDATES
    assert times[0] == 3000.0 * stills.FIRST
    assert abs(times[-1] - 3000.0 * stills.LAST) < 1e-6
    assert stills.candidate_times(0.0) == []


def test_ffmpeg_metadata_is_read_as_numbers():
    text = "frame:0    pts:0      pts_time:0\nlavfi.signalstats.YAVG=56.36\nlavfi.blur=6.6\n"
    assert stills.parse_metadata(text) == {"lavfi.signalstats.YAVG": 56.36, "lavfi.blur": 6.6}


def test_the_rendition_playlist_maps_times_to_segments(tmp_path, monkeypatch):
    folder = tmp_path / "r"
    folder.mkdir()
    (folder / "index.m3u8").write_text(
        '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6.0,\nseg0.m4s\n#EXTINF:6.0,\nseg1.m4s\n#EXT-X-ENDLIST\n'
    )
    (folder / "init.mp4").write_bytes(b"I")
    (folder / "seg0.m4s").write_bytes(b"A")
    (folder / "seg1.m4s").write_bytes(b"B")
    monkeypatch.setattr(stills.hls, "playlist_path_for", lambda path: str(folder / "index.m3u8"))
    source = stills.Source("/gone/episode.mkv")
    assert source.usable and source.file is None
    assert source.input_for(7.5) == (["-i", "pipe:0"], b"IB")
    assert source.input_for(1.0)[1] == b"IA"


def test_black_bars_are_found_and_cost_a_little():
    values = {"lavfi.cropdetect.x1": 60, "lavfi.cropdetect.x2": 419, "lavfi.cropdetect.y1": 0,
              "lavfi.cropdetect.y2": 269, "lavfi.cropdetect.w": 360, "lavfi.cropdetect.h": 270,
              "lavfi.cropdetect.x": 60, "lavfi.cropdetect.y": 0}
    picture = stills.crop_of(values)
    assert abs(picture["left"] - 0.125) < 0.01 and abs(picture["width"] - 0.75) < 0.01
    assert picture["height"] == 1.0
    assert score(frame(**picture)) < score(frame())
    assert "crop=iw*0.75" in stills.fill_chain(frame(**picture))
    assert stills.fill_chain(frame()).startswith("crop='min")


def test_no_bars_found_is_the_whole_frame():
    assert stills.crop_of({}) == {"left": 0.0, "top": 0.0, "width": 1.0, "height": 1.0}
