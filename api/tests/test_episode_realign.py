from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.services.shows import (  # noqa: E402
    file_title,
    realign_by_title,
    title_score,
)

TYRANTS_FILES = {
    1: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E01.Idi.Amin.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
    2: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E02.Fidel.Castro.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
    3: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E03.Josef.Goebbels.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
    4: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E04.Gaddafi.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
    5: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E05.Saddam.Hussein.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
    6: "/lib/Secret.Sex.Lives.Of.Tyrants.S01E06.Mao.1080p.AMZN.WEB-DL.DDP2.0.H.264-RAWR.mkv",
}

TYRANTS_NAMES = {
    1: "Joseph Goebbels: The Randy Goat Of Babelsberg",
    2: "Idi Amin: The Butcher Of Uganda",
    3: "Muammar Gaddafi: The Desert Deviant",
    4: "Mao Zedong: The Red Emperor of Lust",
    5: "Saddam Hussein: Madman of the Middle East",
    6: "Fidel Castro: The Bastard of Havana",
}


def test_file_title_stops_at_the_resolution():
    assert file_title("Chernobyl.S01E02.Please.Remain.Calm.2160p.MAX.WEB-DL.x265.mkv") == (
        "Please Remain Calm"
    )


def test_file_title_is_none_when_the_release_names_no_episode():
    assert file_title("Some.Show.S01E02.1080p.WEB-DL.H.264-GRP.mkv") is None


def test_a_misspelled_forename_still_matches_on_the_surname():
    # "Josef" against "Joseph" is the case the threshold exists for.
    assert title_score("Josef Goebbels", TYRANTS_NAMES[1]) == 0.5


def test_tyrants_is_realigned_onto_the_right_subjects():
    result = realign_by_title(dict(TYRANTS_FILES), dict(TYRANTS_NAMES))
    assert result[2] == TYRANTS_FILES[1]
    assert result[6] == TYRANTS_FILES[2]
    assert result[1] == TYRANTS_FILES[3]
    assert result[3] == TYRANTS_FILES[4]
    assert result[5] == TYRANTS_FILES[5]
    assert result[4] == TYRANTS_FILES[6]


def test_a_release_the_numbers_already_place_is_left_alone():
    files = {
        1: "/lib/Chernobyl.S01E01.1.23.45.2160p.MAX.WEB-DL.x265.mkv",
        2: "/lib/Chernobyl.S01E02.Please.Remain.Calm.2160p.MAX.WEB-DL.x265.mkv",
        3: "/lib/Chernobyl.S01E03.Open.Wide.O.Earth.2160p.MAX.WEB-DL.x265.mkv",
    }
    names = {1: "1:23:45", 2: "Please Remain Calm", 3: "Open Wide, O Earth"}
    assert realign_by_title(dict(files), names) == files


def test_unnamed_episodes_leave_the_numbering_alone():
    files = {1: "/lib/Show.S01E01.Pilot.1080p.WEB-DL.mkv"}
    assert realign_by_title(dict(files), {1: "", 2: ""}) == files


def test_indistinguishable_titles_leave_the_numbering_alone():
    # Both episodes score identically, so the titles cannot break the tie and
    # the number has to stand.
    files = {
        1: "/lib/Show.S01E01.Part.One.1080p.WEB-DL.mkv",
        2: "/lib/Show.S01E02.Part.One.1080p.WEB-DL.mkv",
    }
    names = {1: "Part One", 2: "Part One"}
    assert realign_by_title(dict(files), names) == files


def test_a_partial_season_maps_onto_the_right_episodes():
    held = {1: TYRANTS_FILES[1], 3: TYRANTS_FILES[3]}
    result = realign_by_title(held, dict(TYRANTS_NAMES))
    assert result == {2: TYRANTS_FILES[1], 1: TYRANTS_FILES[3]}
