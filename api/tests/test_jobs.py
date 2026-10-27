from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select

from vibestream.models import Download, DownloadJob
from vibestream.services import downloads, jobs

from .test_episode_downloads import FILES, world  # noqa: F401  (the fixture)

PACK = "Show.S01.1080p.WEB-DL/"


def files(progress: dict[int, float], wanted: set[int]) -> list[dict]:
    return [
        {"index": i, "name": PACK + p, "size": 1000, "progress": progress.get(i, 0.0),
         "priority": 1 if i in wanted else 0}
        for i, p in enumerate(FILES)
    ]


def ask(session, torrent, episode=None, everything=False):
    download = asyncio.run(downloads.request_download(
        session, torrent.id, episode_id=episode.id if episode else None, everything=everything
    ))
    jobs.record(session, download, torrent, episode_id=None if everything else
                (episode.id if episode else None))
    return download


def listed(session):
    return [j for j in jobs.live_jobs(session)]


def test_each_episode_asked_for_is_its_own_job(world):
    session, torrent, eps = world
    first = ask(session, torrent, eps[1])
    first.state = "linked"
    session.commit()
    ask(session, torrent, eps[2])
    ask(session, torrent, eps[2])
    got = listed(session)
    assert [j.episode_id for j in got] == [eps[2].id, eps[1].id]
    assert {j.kind for j in got} == {"episode"}
    assert len({j.download_id for j in got}) == 1


def test_a_job_counts_only_its_own_file(world):
    session, torrent, eps = world
    download = ask(session, torrent, eps[2])
    download.state = "downloading"
    session.commit()
    job = listed(session)[0]
    item = jobs.describe(session, job, None, files({1: 1.0, 2: 0.5}, {2}))
    assert item["state"] == "downloading"
    assert item["percent"] == 50.0
    assert item["size_bytes"] == 1000 and item["downloaded_bytes"] == 500
    assert item["label"] == "S1:E3" and item["episode"]["name"] == "Third"


def test_a_pack_playable_for_old_episodes_is_not_ready_for_the_new_one(world):
    session, torrent, eps = world
    download = ask(session, torrent, eps[1])
    eps[1].download_id = download.id
    eps[1].file_path = "/x/e2.mkv"
    eps[1].prepared_at = download.wanted_at
    download.library_path = "/x"
    download.state = "linked"
    session.commit()
    ask(session, torrent, eps[2])
    by_episode = {j.episode_id: jobs.describe(session, j) for j in listed(session)}
    assert by_episode[eps[1].id]["state"] == "ready"
    assert by_episode[eps[1].id]["play_id"] == f"e{eps[1].id}"
    assert by_episode[eps[2].id]["state"] == "downloading"


def test_the_whole_season_is_one_job(world):
    session, torrent, eps = world
    ask(session, torrent, everything=True)
    got = listed(session)
    assert len(got) == 1 and got[0].kind == "season"
    assert jobs.describe(session, got[0])["label"] == "Season 1"


def test_old_downloads_become_one_job_per_episode(world):
    session, torrent, eps = world
    download = Download(torrent_id=torrent.id, state="linked",
                        wanted_files=json.dumps([FILES[2]]))
    session.add(download)
    session.flush()
    eps[0].download_id = download.id
    eps[0].file_path = "/x/e1.mkv"
    session.commit()
    assert jobs.backfill(session) == 2
    assert sorted(j.episode_id for j in session.scalars(select(DownloadJob))) == \
        [eps[0].id, eps[2].id]
    assert jobs.backfill(session) == 0


def test_an_episode_deleted_another_way_leaves_the_list(world):
    session, torrent, eps = world
    download = ask(session, torrent, eps[1])
    download.state = "linked"
    download.wanted_files = json.dumps([FILES[2]])
    session.commit()
    job = session.scalar(select(DownloadJob).where(DownloadJob.episode_id == eps[1].id))
    assert jobs.describe(session, job) is None


def test_trackers_never_carry_the_passkey():
    url = "https://tracker.example.org/announce.php?passkey=0123456789abcdef0123456789abcdef"
    assert jobs.tracker_host(url) == "tracker.example.org"
    assert "0123456789abcdef" not in jobs.scrub(f"rejected {url}")
    assert jobs.tracker_host("** [DHT] **") == "[DHT]"


def test_the_piece_map_squeezes_into_cells():
    states = [2] * 500 + [1] * 10 + [0] * 490
    cells = jobs.piece_map(states, buckets=10)
    assert cells["count"] == 1000
    assert cells["have"][:5] == [100] * 5 and cells["have"][-1] == 0
    assert cells["busy"][5] == 1 and sum(cells["busy"]) == 1


def test_speed_gives_the_time_left(world):
    session, torrent, eps = world
    download = ask(session, torrent, eps[2])
    download.state = "downloading"
    session.commit()
    status = SimpleNamespace(dlspeed=100, eta=9999)
    item = jobs.describe(session, listed(session)[0], status, files({2: 0.5}, {2}))
    assert item["dl_speed"] == 100 and item["eta_seconds"] == 5
