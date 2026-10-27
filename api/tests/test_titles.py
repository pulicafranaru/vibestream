from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.titles import library_folder_name, parse_release  # noqa: E402


def test_basic_web_dl():
    p = parse_release("Hit.Man.2024.2160p.NF.WEB-DL.DDP5.1.Atmos.H.265-HHWEB")
    assert p.title == "Hit Man"
    assert p.year == 2024
    assert p.resolution == "2160p"
    assert p.source == "WEB-DL"
    assert p.video_codec == "H.265"
    assert p.audio_codec == "DDP Atmos"
    assert p.release_group == "HHWEB"


def test_year_in_title_is_not_the_release_year():
    p = parse_release("Blade.Runner.2049.2017.2160p.MA.WEB-DL.TrueHD.Atmos.7.1.DoVi.HDR.H.265-FLUX")
    assert p.title == "Blade Runner 2049"
    assert p.year == 2017
    assert p.audio_codec == "TrueHD Atmos"
    assert p.hdr == "DV HDR"


def test_leading_year_is_a_title():
    p = parse_release("1917.2019.1080p.BluRay.DTS.x264-CtrlHD")
    assert p.title == "1917"
    assert p.year == 2019
    assert p.video_codec == "x264"
    assert p.audio_codec == "DTS"


def test_future_year_stays_in_title():
    p = parse_release("Blade.Runner.2049.1080p.BluRay.x264-GROUP")
    assert p.title == "Blade Runner 2049"
    assert p.year is None


def test_dts_hd_ma_survives_dots():
    p = parse_release("Split.2016.2160p.MA.WEB-DL.DTS-HD.MA.5.1.H.265-FLUX")
    assert p.title == "Split"
    assert p.audio_codec == "DTS-HD MA"
    assert p.video_codec == "H.265"


def test_uhd_bluray_remux():
    p = parse_release(
        "Chappie.2015.2160p.UHD.BluRay.Atmos.TrueHD.7.1.HDR.x265-CtrlHD"
    )
    assert p.title == "Chappie"
    assert p.resolution == "2160p"
    assert p.source == "BluRay"
    assert p.video_codec == "x265"
    assert p.hdr == "HDR"
    assert "TrueHD" in p.audio_codec


def test_ampersand_and_numeral_in_title():
    p = parse_release("Fast.&.Furious.7.2015.2160p.iT.WEB-DL.DD5.1.DoVi.H.265-EZPz")
    assert p.title == "Fast & Furious 7"
    assert p.year == 2015
    assert p.hdr == "DV"
    assert p.audio_codec == "DD"


def test_apostrophe_in_title():
    p = parse_release("Sarah's.Oil.2025.2160p.iT.WEB-DL.DDP5.1.HDR.H.265-FLUX")
    assert p.title == "Sarah's Oil"
    assert p.year == 2025


def test_edition_is_captured_not_dropped():
    p = parse_release(
        "Leon.1994.International.Cut.1080p.BluRay.DD5.1.x264-CtrlHD"
    )
    assert p.title == "Leon"
    assert p.year == 1994
    assert p.edition is not None and "International" in p.edition


def test_imax_edition():
    p = parse_release(
        "Mission.Impossible.Fallout.2018.IMAX.2160p.DSNP.WEB-DL.DD+5.1.Atmos.DoVi.HDR.H.265-playWEB"
    )
    assert p.title == "Mission Impossible Fallout"
    assert p.edition == "Imax"
    assert p.audio_codec == "DDP Atmos"


def test_tv_season_pack():
    p = parse_release(
        "Person.of.Interest.S01.720p.HMAX.WEB-DL.DD+5.1.H.264-playWEB"
    )
    assert p.title == "Person of Interest"
    assert p.season == 1
    assert p.episode is None
    assert p.is_tv is True
    assert p.video_codec == "H.264"


def test_tv_single_episode():
    p = parse_release("Silo.S02E05.1080p.ATVP.WEB-DL.DDP5.1.Atmos.H.264-NTb")
    assert p.title == "Silo"
    assert p.season == 2
    assert p.episode == 5
    assert p.is_tv is True


def test_tv_season_range():
    p = parse_release("The.Real.Hustle.S01-S08.480p.WEB-DL.AAC2.0.H.264-GROUP")
    assert p.title == "The Real Hustle"
    assert p.season == 1
    assert p.is_tv is True


def test_long_multiword_title():
    p = parse_release(
        "The.Princess.Switch.3.Romancing.the.Star.2021.2160p.NF.WEB-DL.DDP5.1.Atmos.H.265-FLUX"
    )
    assert p.title == "The Princess Switch 3 Romancing the Star"
    assert p.year == 2021


def test_hybrid_and_service_tags_are_dropped():
    p = parse_release(
        "Bugonia.2025.Hybrid.2160p.MA.WEB-DL.DDP5.1.Atmos.DoVi.HDR.H.265-HONE"
    )
    assert p.title == "Bugonia"
    assert p.year == 2025
    assert p.release_group == "HONE"


def test_no_release_group():
    p = parse_release("Home.Alone.1990.2160p")
    assert p.title == "Home Alone"
    assert p.year == 1990
    assert p.release_group is None


def test_web_dl_is_not_split_into_a_group():
    p = parse_release("Otherhood.2019.2160p.NF.WEB-DL.DDP5.1.H.265-XEBEC")
    assert p.source == "WEB-DL"
    assert p.release_group == "XEBEC"


def test_hdr10_plus():
    p = parse_release("Some.Film.2023.2160p.WEB-DL.DDP5.1.HDR10+.H.265-GRP")
    assert p.hdr == "HDR10+"


def test_empty_input():
    assert parse_release("").title == ""
    assert parse_release("   ").title == ""


def test_folder_naming():
    assert library_folder_name("Dune Part Two", 2024) == "Dune Part Two (2024)"
    assert library_folder_name("Ratatouille", None) == "Ratatouille"
    assert "/" not in library_folder_name("Face/Off", 1997)
    assert library_folder_name("Face/Off", 1997) == "FaceOff (1997)"
