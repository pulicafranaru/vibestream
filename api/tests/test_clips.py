from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.routers.clips import NewClip, save_clip  # noqa: E402

from .test_live import clips  # noqa: E402,F401  (the fixture)


@pytest.mark.parametrize("start,end,message", [
    (10, 11, "at least two seconds"),
    (10, 131, "at most two minutes"),
    (-1, 20, "at least two seconds"),
])
def test_lengths_outside_the_limits_are_refused(start, end, message):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(save_clip(NewClip(play_id="e1", start=start, end=end), None, None))
    assert caught.value.status_code == 400 and message in caught.value.detail


def _person(x, strength=1.0):
    side = strength ** 0.5 * 0.4
    return {"box": [x - side / 2, 0.1, x + side / 2, 0.1 + side], "confidence": 1.0, "kind": 0,
            "focus": [x - 0.03, x + 0.03]}


def test_a_two_shot_holds_on_one_face_rather_than_the_gap_between():
    from vibestream.services import smartcrop

    # Two faces too far apart to share a tall frame, each the stronger in
    # turn: the frame must settle on one of them, not on the middle.
    samples = [(t / 4, [_person(0.2, 1.0 if t % 2 else 0.8), _person(0.8, 0.8 if t % 2 else 1.0)])
               for t in range(20)]
    plan = smartcrop.plan([], samples, 16 / 9, 5.0)
    xs = [x for shot in plan["shots"] for _t, x in shot["points"]]
    assert all(abs(x - 0.2) < 0.06 for x in xs) or all(abs(x - 0.8) < 0.06 for x in xs)


def test_a_still_subject_off_centre_is_held_on_and_a_cut_may_jump():
    from vibestream.services import smartcrop

    samples = [(t / 4, [_person(0.25 if t < 12 else 0.75)]) for t in range(24)]
    plan = smartcrop.plan([3.0], samples, 16 / 9, 6.0)
    first, second = plan["shots"]
    assert first["points"] == [[0.0, 0.25]]
    assert len(second["points"]) == 1 and abs(second["points"][0][1] - 0.75) < 0.01


def test_nobody_in_shot_plays_from_the_middle():
    from vibestream.services import smartcrop

    plan = smartcrop.plan([], [(t / 4, []) for t in range(8)], 16 / 9, 2.0)
    assert plan["shots"] == [{"start": 0.0, "end": 2.0, "points": [[0.0, 0.5]]}]


def test_the_vertical_edit_is_kept_clamped_and_cleared(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from vibestream.models import Base, Clip
    from vibestream.routers import clips as router
    from vibestream.services import clips as service

    monkeypatch.setattr(service, "CLIPS_DIR", str(tmp_path))
    monkeypatch.setattr(router.smartcrop, "ensure", lambda clip_id: None)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Clip(id=7, profile_id=1, media_id=1, play_id="1", title="Heist",
                     start_seconds=0, end_seconds=10, duration_seconds=10))
    session.commit()

    kept = router.put_vertical(7, router.VerticalEdit(keyframes=[
        router.Keyframe(t=8, x=1.4, zoom=9), router.Keyframe(t=-1, x=0.3)]), session)
    assert kept["keyframes"] == [
        {"t": 0.0, "x": 0.3, "y": 0.5, "zoom": 1.0},
        {"t": 8.0, "x": 1.0, "y": 0.5, "zoom": 4.0},
    ]
    assert router.get_vertical(7, session)["keyframes"] == kept["keyframes"]
    router.put_vertical(7, router.VerticalEdit(keyframes=[]), session)
    assert router.get_vertical(7, session)["keyframes"] == []


def test_a_title_played_live_is_clipped_from_its_source(tmp_path, monkeypatch, clips):  # noqa: F811
    from vibestream.services import clips as service
    from vibestream.services import hls, mediainfo

    monkeypatch.setattr(hls, "CACHE_ROOT", str(tmp_path / "hls"))
    monkeypatch.setattr(mediainfo, "PROBE_CACHE", str(tmp_path / "probe"))
    monkeypatch.setattr(service, "CLIPS_DIR", str(tmp_path / "clips"))
    info = asyncio.run(mediainfo.probe(clips["mkv"]))

    real = asyncio.run(service.cut(1, info, 2.0, 5.0))
    assert 2.5 <= real <= 6.0
    made = asyncio.run(mediainfo.probe(service.video_path(1)))
    assert [a.codec for a in made.audio] == ["aac"]
    assert (tmp_path / "clips" / "1.jpg").exists()
    assert not list((tmp_path / "clips").glob("*.part.mp4"))


def test_nothing_to_clip_from_is_said_plainly(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from vibestream.services import clips as service
    from vibestream.services import hls

    monkeypatch.setattr(hls, "CACHE_ROOT", str(tmp_path / "hls"))
    gone = SimpleNamespace(path=str(tmp_path / "gone.mkv"), video=None)
    with pytest.raises(service.ClipUnavailable):
        asyncio.run(service.cut(1, gone, 2.0, 5.0))
