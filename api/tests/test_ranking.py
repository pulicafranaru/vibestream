from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.models import Torrent  # noqa: E402
from vibestream.services.ranking import group_alternatives, pick_primary, rank  # noqa: E402

GB = 1024 ** 3


def make(
    tid=1, resolution="2160p", source="WEB-DL", codec="H.265", hdr="HDR",
    size_gb=12, seeders=50, internal=False, files=1, season=None,
):
    return Torrent(
        id=tid, name=f"release {tid}", resolution=resolution, source=source,
        video_codec=codec, hdr=hdr, size_bytes=int(size_gb * GB), seeders=seeders,
        internal=internal, file_count=files, season=season, times_completed=50,
    )


def test_2160p_beats_1080p():
    best = pick_primary([make(1, resolution="1080p", codec="H.264", hdr=None),
                         make(2, resolution="2160p")])
    assert best.id == 2


def test_1080p_beats_720p():
    best = pick_primary([make(1, resolution="720p"), make(2, resolution="1080p")])
    assert best.id == 2


def test_oversized_remux_loses_to_sane_2160p():
    remux = make(1, source="Remux", size_gb=70, seeders=20)
    webdl = make(2, source="WEB-DL", size_gb=14, seeders=40)
    assert pick_primary([remux, webdl]).id == 2


def test_oversized_remux_is_still_offered():
    remux = make(1, source="Remux", size_gb=70)
    webdl = make(2, source="WEB-DL", size_gb=14)
    grouped = group_alternatives([remux, webdl])
    assert grouped["primary"].torrent.id == 2
    assert 1 in [alt.torrent.id for alt in grouped["alternatives"]]


def test_slightly_over_ceiling_is_only_mildly_demoted():
    big = make(1, size_gb=35)
    small = make(2, size_gb=14)
    hd = make(3, resolution="1080p", codec="H.264", hdr=None, size_gb=8)
    ranked = [s.torrent.id for s in rank([big, small, hd])]
    assert ranked[0] == 2
    assert ranked.index(1) < ranked.index(3)


def test_dead_torrent_loses_despite_better_resolution():
    dead = make(1, resolution="2160p", seeders=0)
    alive = make(2, resolution="1080p", codec="H.264", hdr=None, seeders=200)
    assert pick_primary([dead, alive]).id == 2


def test_hdr_preferred_over_sdr_at_same_resolution():
    sdr = make(1, hdr=None)
    dv = make(2, hdr="DV HDR")
    assert pick_primary([sdr, dv]).id == 2


def test_cam_never_wins():
    cam = make(1, resolution="2160p", source="CAM", seeders=999)
    webdl = make(2, resolution="720p", source="WEB-DL", codec="H.264", hdr=None)
    assert pick_primary([cam, webdl]).id == 2


def test_multi_file_disc_rip_demoted_for_movies():
    disc = make(1, files=40)
    single = make(2, files=1, size_gb=13)
    assert pick_primary([disc, single]).id == 2


def test_season_pack_not_penalised_for_many_files():
    pack = make(1, files=10, season=1, resolution="1080p", codec="H.264", hdr=None)
    other = make(2, files=1, season=1, resolution="720p", codec="H.264", hdr=None)
    assert pick_primary([pack, other]).id == 1


def test_internal_release_edges_out_equal_alternative():
    plain = make(1, internal=False, seeders=50)
    internal = make(2, internal=True, seeders=50)
    assert pick_primary([internal, plain]).id == 2


def test_fallbacks_grouped_by_resolution():
    grouped = group_alternatives([
        make(1, resolution="2160p"),
        make(2, resolution="1080p", codec="H.264", hdr=None),
        make(3, resolution="720p", codec="H.264", hdr=None),
    ])
    assert set(grouped["by_resolution"]) == {"2160p", "1080p", "720p"}
    assert grouped["primary"].torrent.id == 1


def test_empty_input():
    assert pick_primary([]) is None
    assert group_alternatives([])["primary"] is None
