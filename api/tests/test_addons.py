"""Stremio addons as a release source."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.config import settings  # noqa: E402
from vibestream.models import Base, Download, Episode, Media, Season, Torrent  # noqa: E402
from vibestream.schemas import media_card  # noqa: E402
from vibestream.services import addons, downloads, offered  # noqa: E402
from vibestream.services.shows import releases_for  # noqa: E402

PACK = {
    "name": "Torrentio\n4k HDR",
    "title": "Game.of.Thrones.S01.2160p.UHD.BluRay.x265.10bit.HDR-DON[rartv]\n"
             "Game.of.Thrones.S01E02.The.Kingsroad.2160p.UHD.BluRay.x265-DON.mkv\n"
             "\U0001F464 14 \U0001F4BE 15.31 GB ⚙️ RARBG",
    "infoHash": "98FA5648554A67748BED7F8CF58559B2660A5C4D",
    "fileIdx": 1,
    "behaviorHints": {"filename": "Game.of.Thrones.S01E02.The.Kingsroad.2160p.UHD.BluRay.x265-DON.mkv"},
    "sources": ["tracker:udp://tracker.example:1337/announce", "dht:98fa5648554a67748bed7f8cf58559b2660a5c4d"],
}
SINGLE = {
    "title": "Game.of.Thrones.S01E02.1080p.WEB-DL.x264\n\U0001F464 7 \U0001F4BE 1.2 GB ⚙️ EZTV",
    "infoHash": "1111111111111111111111111111111111111111",
}
COMPLETE = {
    "title": "Game of Thrones Complete Series\nSeason 1/Episode 1.mkv\n\U0001F464 30 \U0001F4BE 300 GB ⚙️ 1337x",
    "infoHash": "2222222222222222222222222222222222222222",
}


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    show = Media(title="Game of Thrones", media_type="tv", imdb_id="tt0944947")
    film = Media(title="The Shawshank Redemption", media_type="movie", imdb_id="tt0111161")
    session.add_all([show, film])
    session.commit()
    saved = {k: getattr(settings, k) for k in
             ("addons_enabled", "addon_urls", "filelist_username", "filelist_passkey")}
    object.__setattr__(settings, "addons_enabled", True)
    object.__setattr__(settings, "addon_urls", ["https://addon.example"])
    object.__setattr__(settings, "filelist_username", "")
    object.__setattr__(settings, "filelist_passkey", "")
    addons._asked.clear()
    yield session, show, film
    for key, value in saved.items():
        object.__setattr__(settings, key, value)
    session.close()


def test_a_stream_is_read_as_its_torrent():
    found = addons.parse_stream(PACK)
    assert found.info_hash == "98fa5648554a67748bed7f8cf58559b2660a5c4d"
    assert found.name.startswith("Game.of.Thrones.S01.2160p")
    assert found.inner.startswith("Game.of.Thrones.S01E02")
    assert found.seeders == 14
    assert found.size_bytes == int(15.31 * 1024 ** 3)
    assert found.provider == "RARBG"
    assert found.trackers == ["udp://tracker.example:1337/announce"]
    single = addons.parse_stream(SINGLE)
    assert single.inner is None and single.seeders == 7 and single.provider == "EZTV"
    assert addons.parse_stream({"title": "x", "url": "https://example.invalid/x.mkv"}) is None


def test_the_address_from_the_configure_page_is_taken_as_it_comes():
    copied = "stremio://addons.strem.fun/providers=yts|sort=size/manifest.json"
    assert addons.base_url(copied) == "https://addons.strem.fun/providers=yts|sort=size"
    assert addons.base_url("https://addons.strem.fun/") == "https://addons.strem.fun"


def test_releases_are_kept_once_per_torrent_and_numbered_clear_of_filelist(world):
    session, show, _ = world
    pack, created = addons.store(session, show, addons.parse_stream(PACK), 1, 2)
    assert created and pack.id == addons.FIRST_ID
    again, created = addons.store(session, show, addons.parse_stream(PACK), 1, 3)
    assert not created and again.id == pack.id
    single, _ = addons.store(session, show, addons.parse_stream(SINGLE), 1, 2)
    assert single.id == addons.FIRST_ID + 1
    assert (pack.season, pack.episode) == (1, None)
    assert (single.season, single.episode) == (1, 2)
    assert pack.origin == "addon" and pack.category == 27 and pack.category_name == "RARBG"
    assert addons.FIRST_ID + 1 < 2 ** 31


def test_a_complete_series_grows_to_every_season_it_is_found_under(world):
    session, show, _ = world
    found = addons.parse_stream(COMPLETE)
    row, _ = addons.store(session, show, found, 3, 1)
    assert (row.season, row.season_end, row.episode) == (3, None, None)
    addons.store(session, show, found, 1, 1)
    addons.store(session, show, found, 5, 1)
    assert (row.season, row.season_end) == (1, 5)


def test_a_film_remembers_its_file_for_a_box_set(world):
    session, _, film = world
    item = {"title": "Trilogy 1080p\nPart.Two.1080p.mkv\n\U0001F464 9 \U0001F4BE 20 GB ⚙️ 1337x",
            "infoHash": "3" * 40, "behaviorHints": {"filename": "Part.Two.1080p.mkv"}}
    row, _ = addons.store(session, film, addons.parse_stream(item))
    assert row.file_name == "Part.Two.1080p.mkv" and row.season is None


def test_a_question_is_asked_once_while_its_answer_is_fresh(world, monkeypatch):
    session, show, _ = world
    asked = []

    async def answer(kind, imdb_id, season=None, episode=None):
        asked.append((kind, imdb_id, season, episode))
        return [PACK, SINGLE]

    monkeypatch.setattr(addons, "streams", answer)
    assert asyncio.run(addons._ask(session, show, 1, 2)) == 2
    assert asyncio.run(addons._ask(session, show, 1, 2)) == 0
    assert asked == [("tv", "tt0944947", 1, 2)]
    assert len(show.torrents) == 2


def test_a_season_asks_only_about_episodes_nothing_covers(world, monkeypatch):
    session, show, _ = world
    season = Season(media_id=show.id, number=1, episode_count=3, air_date="2011-04-17")
    session.add(season)
    session.flush()
    for n in (1, 2, 3):
        session.add(Episode(media_id=show.id, season_id=season.id, season_number=1,
                            number=n, air_date="2011-04-17"))
    session.commit()
    asked = []

    async def answer(kind, imdb_id, season=None, episode=None):
        asked.append(episode)
        return [SINGLE] if episode == 1 else []

    monkeypatch.setattr(addons, "streams", answer)
    asyncio.run(addons.refresh_season(session, show, 1))
    assert sorted(asked) == [1, 3]


def test_a_server_with_addons_alone_offers_no_filelist_release(world):
    session, _, film = world
    filelist = Torrent(id=5, name="The.Shawshank.Redemption.1994.1080p.BluRay", media_id=film.id,
                       resolution="1080p", seeders=50)
    held = Torrent(id=6, name="The.Shawshank.Redemption.1994.720p.BluRay", media_id=film.id,
                   resolution="720p", seeders=50)
    session.add_all([filelist, held, Download(torrent_id=6, state="linked")])
    session.commit()
    public, _ = addons.store(session, film, addons.parse_stream(
        {"title": "The Shawshank Redemption 1994 2160p BluRay\n\U0001F464 191 \U0001F4BE 6.91 GB ⚙️ YTS",
         "infoHash": "c3da9a3dc2ce14d0d4fc0e87d1b2023502f8dcd6"}))
    session.commit()
    names = {t.id for t in offered.offered(film.torrents)}
    assert names == {public.id, held.id}
    card = media_card(film, film.torrents, {6: session.get(Download, 1)})
    assert card["primary_release_id"] == public.id
    assert 5 not in {r["id"] for r in card["releases"]}

    object.__setattr__(settings, "addons_enabled", False)
    assert len(offered.offered(film.torrents)) == 3


def test_an_episode_is_offered_from_an_addon_on_an_addon_server(world):
    session, show, _ = world
    session.add(Torrent(id=9, name="Game.of.Thrones.S01.1080p", media_id=show.id, season=1))
    addons.store(session, show, addons.parse_stream(SINGLE), 1, 2)
    session.commit()
    assert [t.origin for t in releases_for(session, show, 1, 2)] == ["addon"]


def test_a_magnet_names_its_trackers():
    link = addons.magnet("ab" * 20, "Some Film", '["udp://one.example:80/announce"]')
    assert link.startswith("magnet:?xt=urn:btih:" + "ab" * 20)
    assert "dn=Some%20Film" in link
    assert "tr=udp%3A%2F%2Fone.example%3A80%2Fannounce" in link
    assert "tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce" in link


def test_an_addon_release_is_fetched_through_qbittorrent(world, monkeypatch, tmp_path):
    session, _, film = world
    row, _ = addons.store(session, film, addons.parse_stream(
        {"title": "Film 1080p\n\U0001F464 3 \U0001F4BE 1 GB ⚙️ YTS", "infoHash": "4" * 40}))
    session.commit()
    asked = []

    async def from_qbit(info_hash, name, announce):
        asked.append(info_hash)
        # Past the 100 bytes below which a cached .torrent is not trusted.
        return b"d7:comment200:" + b"x" * 200 + b"4:infod4:name4:filee" + b"e"

    monkeypatch.setattr(addons, "metadata_bytes", from_qbit)
    monkeypatch.setattr(downloads, "TORRENT_CACHE_DIR", str(tmp_path))

    class Scope:
        def __enter__(self):
            return session

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr("vibestream.db.session_scope", lambda: Scope())
    first = asyncio.run(downloads.fetch_torrent_bytes(row.id))
    again = asyncio.run(downloads.fetch_torrent_bytes(row.id))
    assert first == again and first.startswith(b"d")
    assert asked == ["4" * 40]


COMET = {
    "name": "[RD+] Comet 2160p",
    "description": "\U0001F4C4 The.Shawshank.Redemption.1994.2160p.UHD.BluRay.x265-GROUP.mkv\n"
                   "\U0001F4BE 18.5 GB \U0001F464 120\n\U0001F50E ThePirateBay",
    "url": "https://comet.example/playback/secret/" + "5" * 40 + "/0/film.mkv",
    "behaviorHints": {"filename": "The.Shawshank.Redemption.1994.2160p.UHD.BluRay.x265-GROUP.mkv",
                      "videoSize": 19864223744},
}
MEDIAFUSION = {
    "name": "MediaFusion | P2P 1080p",
    "description": "\U0001F4C2 The Shawshank Redemption 1994 1080p BluRay\n"
                   "\U0001F4BE 2.1 GB \U0001F464 44\n\U0001F517 1337x",
    "infoHash": "6" * 40,
}


def test_any_addon_is_read_whatever_its_words():
    comet = addons.parse_stream(COMET)
    assert comet.info_hash == "5" * 40
    assert comet.link == COMET["url"]
    assert comet.name.startswith("The.Shawshank.Redemption.1994.2160p")
    assert (comet.seeders, comet.provider) == (120, "ThePirateBay")
    assert comet.size_bytes == int(18.5 * 1024 ** 3)

    fusion = addons.parse_stream(MEDIAFUSION)
    assert fusion.name == "The Shawshank Redemption 1994 1080p BluRay"
    assert (fusion.seeders, fusion.provider, fusion.link) == (44, "1337x", None)

    noted = addons.parse_stream({
        "title": "Film.2020.1080p.WEB\n\U0001F464 5 \U0001F4BE 2 GB ⚙️ YTS\nMulti Audio / \U0001F1EC\U0001F1E7",
        "infoHash": "7" * 40,
    })
    assert noted.inner is None and noted.provider == "YTS"

    bare = addons.parse_stream({"url": "https://x.example/" + "8" * 40,
                                "behaviorHints": {"filename": "Film.2020.720p.mkv", "videoSize": 5}})
    assert (bare.name, bare.size_bytes) == ("Film.2020.720p.mkv", 5)


def test_two_addons_naming_one_torrent_make_one_release(world):
    session, _, film = world
    seen_by_both = {**MEDIAFUSION, "infoHash": "5" * 40}
    merged = addons._merged([seen_by_both, COMET])
    assert len(merged) == 1
    assert merged[0].seeders == 120 and merged[0].link == COMET["url"]
    row, _ = addons.store(session, film, merged[0])
    assert row.linkable and row.origin == "addon"


def test_an_addon_that_fails_leaves_the_others_answering(world, monkeypatch):
    object.__setattr__(settings, "addon_urls", ["https://up.example", "https://down.example"])

    async def ask_one(address, kind, imdb_id, season=None, episode=None):
        if "down" in address:
            raise addons.AddonError("down.example answered HTTP 502")
        return [MEDIAFUSION]

    monkeypatch.setattr(addons, "ask_one", ask_one)
    assert asyncio.run(addons.streams("movie", "tt0111161")) == [MEDIAFUSION]

    object.__setattr__(settings, "addon_urls", ["https://down.example"])
    with pytest.raises(addons.AddonError):
        asyncio.run(addons.streams("movie", "tt0111161"))


def test_an_addon_is_named_by_its_host_never_its_key():
    assert addons.label("https://torrentio.strem.fun/realdebrid=SECRETKEY") == "torrentio.strem.fun"


def test_a_release_the_debrid_service_holds_needs_no_seeders(world):
    from vibestream.services import ranking

    session, _, film = world
    swarm, _ = addons.store(session, film, addons.parse_stream(
        {"title": "Film.1994.1080p.BluRay.x264\n\U0001F464 50 \U0001F4BE 2 GB", "infoHash": "a" * 40}))
    held, _ = addons.store(session, film, addons.parse_stream(
        {"name": "[RD+] Torrentio\n1080p", "description": "Film.1994.1080p.BluRay.x264\n\U0001F4BE 2 GB",
         "url": "https://debrid.example/" + "b" * 40}))
    # Torrentio's way of saying the service would have to fetch it first.
    fetched_first, _ = addons.store(session, film, addons.parse_stream(
        {"name": "[RD download] Torrentio\n1080p", "description": "Film.1994.1080p.WEB\n\U0001F4BE 2 GB",
         "url": "https://debrid.example/" + "c" * 40}))
    assert held.held and held.linkable
    assert fetched_first.linkable and not fetched_first.held
    ranked = ranking.rank([swarm, fetched_first, held])
    assert [s.torrent for s in ranked] == [held, swarm, fetched_first]
    assert ranked[0].score > 0 > ranked[2].score


def test_each_addon_says_held_its_own_way():
    def held(name):
        return addons.parse_stream({"name": name, "description": "Film.2020.1080p",
                                    "url": "https://d.example/" + "d" * 40}).held

    assert held("[RD+] Torrentio 4k") and held("[RD\u26a1] Comet 2160p")
    assert held("MediaFusion | RD \u26a1\ufe0f 1080p")
    assert not held("[RD download] Torrentio") and not held("[RD\u2b07\ufe0f] Comet")
    assert not held("MediaFusion | RD \u23f3 1080p") and not held("Some addon 1080p")


def test_a_film_an_addon_offers_as_a_link_is_fetched_from_it(world, monkeypatch):
    from vibestream.services import linkfetch

    session, show, film = world
    row, _ = addons.store(session, film, addons.parse_stream(COMET))
    session.commit()
    started = []

    async def link_for(torrent, season=None, episode=None):
        return "https://debrid.example/fresh/film.mkv"

    monkeypatch.setattr(addons, "link_for", link_for)
    monkeypatch.setattr(linkfetch, "start", started.append)
    download = asyncio.run(downloads.request_download(session, row.id))
    assert download.link == "https://debrid.example/fresh/film.mkv"
    assert download.info_hash is None and download.state == "downloading"
    assert started == [download.id]

    pack, _ = addons.store(session, show, addons.parse_stream({**PACK, "url": "https://d.example/x"}), 1, 2)
    assert pack.linkable and not downloads._by_link(pack, None, False)


def test_a_link_download_owes_no_seeding():
    from vibestream.models import Download as Row
    from vibestream.services import reaper

    met, _ = reaper._seeding_satisfied(Row(link="https://debrid.example/x", ratio=0.0,
                                           seeding_seconds=0))
    assert met


def test_addon_addresses_are_kept_as_a_list():
    from vibestream.services import overrides

    cleaned = overrides.clean(
        "addon_urls", "stremio://a.example/conf/manifest.json  https://b.example/\nhttps://b.example")
    assert cleaned == ["https://a.example/conf", "https://b.example"]
    with pytest.raises(overrides.Invalid):
        overrides.clean("addon_urls", ["not an address"])


def test_torrentio_settings_saved_before_become_addon_settings():
    import json

    from vibestream.db import engine, session_scope
    from vibestream.models import SettingOverride
    from vibestream.services import overrides

    Base.metadata.create_all(engine)
    saved = (settings.addons_enabled, settings.addon_urls)
    with session_scope() as s:
        s.add(SettingOverride(key="torrentio_enabled", value="true"))
        s.add(SettingOverride(key="torrentio_url", value=json.dumps("https://torrentio.strem.fun/x")))
    try:
        overrides.load()
        assert settings.addons_enabled is True
        assert settings.addon_urls == ["https://torrentio.strem.fun/x"]
        with session_scope() as s:
            assert s.get(SettingOverride, "torrentio_url") is None
            assert json.loads(s.get(SettingOverride, "addon_urls").value) == [
                "https://torrentio.strem.fun/x"]
    finally:
        with session_scope() as s:
            for key in ("addons_enabled", "addon_urls"):
                row = s.get(SettingOverride, key)
                if row is not None:
                    s.delete(row)
        object.__setattr__(settings, "addons_enabled", saved[0])
        object.__setattr__(settings, "addon_urls", saved[1])


def test_a_question_the_page_stopped_waiting_for_is_asked_again(world, monkeypatch):
    session, _, film = world
    calls = []

    async def slow(kind, imdb_id, season=None, episode=None):
        calls.append(imdb_id)
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(addons, "streams", slow)

    async def page():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(addons._ask(session, film), timeout=0.05)

    asyncio.run(page())
    assert not addons._fresh("tt0111161:None:None")

    async def quick(kind, imdb_id, season=None, episode=None):
        calls.append(imdb_id)
        return [MEDIAFUSION]

    monkeypatch.setattr(addons, "streams", quick)
    assert asyncio.run(addons._ask(session, film)) == 1
    assert calls == ["tt0111161", "tt0111161"]


def test_a_slow_addon_is_left_out_not_waited_for(world, monkeypatch):
    object.__setattr__(settings, "addon_urls", ["https://quick.example", "https://slow.example"])
    monkeypatch.setattr(addons, "ANSWER_SECONDS", 0.05)

    async def ask_one(address, kind, imdb_id, season=None, episode=None):
        if "slow" in address:
            await asyncio.sleep(5)
        return [MEDIAFUSION]

    monkeypatch.setattr(addons, "ask_one", ask_one)
    assert asyncio.run(addons.streams("movie", "tt0111161")) == [MEDIAFUSION]


def test_an_odd_size_does_not_lose_the_answer():
    found = addons.parse_stream({"title": "Film.2020.720p\n\U0001F4BE 1,234.5 MB \U0001F464 3",
                                 "infoHash": "e" * 40})
    assert found.size_bytes == int(1234.5 * 1024 ** 2)
    assert addons.parse_stream({"title": "Film\n\U0001F4BE 2,5 GB", "infoHash": "f" * 40}).size_bytes \
        == int(2.5 * 1024 ** 3)
    assert addons._size("1.2.3", "GB") == 0


def test_an_address_that_cannot_be_asked_is_an_addon_error():
    with pytest.raises(addons.AddonError):
        # Refused by httpx before anything is sent.
        asyncio.run(addons.ask_one("https://addon.example:abc", "movie", "tt0111161"))


def test_one_title_failing_does_not_stop_the_trending_rows(world, monkeypatch):
    session, show, film = world
    asked = []

    async def refresh_title(session, media, background=False):
        asked.append(media.title)
        if media is show:
            raise RuntimeError("TMDB said no")
        return 2

    async def titles_for(session, results):
        return [show, film]

    class Client:
        async def trending(self, kind):
            return [{"id": 1}]

    monkeypatch.setattr(addons, "refresh_title", refresh_title)
    monkeypatch.setattr(addons, "_titles_for", titles_for)
    monkeypatch.setattr("vibestream.services.tmdb.TMDBClient", lambda: Client())
    object.__setattr__(settings, "tmdb_api_key", settings.tmdb_api_key or "k" * 32)
    assert asyncio.run(addons.discover(session, force=True)) == 2
    assert asked == ["Game of Thrones", "The Shawshank Redemption"]


def test_a_tile_on_an_addon_server_never_offers_a_filelist_release(world):
    session, _, film = world
    filelist = Torrent(id=11, name="The.Shawshank.Redemption.1994.1080p", media_id=film.id, seeders=9)
    session.add(filelist)
    session.commit()
    card = media_card(film, [], {}, fallback=filelist)
    assert card["primary_release_id"] is None


def test_addon_addresses_go_to_the_browser_masked():
    from vibestream.services import overrides

    secret = "https://torrentio.strem.fun/realdebrid=SECRETKEY1234"
    saved = settings.addon_urls
    object.__setattr__(settings, "addon_urls", [secret])
    try:
        shown = overrides._shown(overrides.FIELDS["addon_urls"], [secret])
        assert shown == ["https://torrentio.strem.fun/…1234"] and "SECRET" not in shown[0]
        assert overrides.clean("addon_urls", shown + ["https://b.example"]) == [secret, "https://b.example"]
        with pytest.raises(overrides.Invalid, match="Paste it again"):
            overrides.clean("addon_urls", ["https://other.example/…abcd"])
        with pytest.raises(overrides.Invalid) as wrong:
            overrides.clean("addon_urls", ["https://x.example:99999/realdebrid=KEY"])
        assert "KEY" not in str(wrong.value)
        with pytest.raises(overrides.Invalid, match="switch them off"):
            overrides.clean("addon_urls", ["  "])
    finally:
        object.__setattr__(settings, "addon_urls", saved)


def test_every_version_says_where_it_came_from(world):
    from vibestream.schemas import torrent_summary

    session, _, film = world
    filelist = Torrent(id=12, name="The.Shawshank.Redemption.1994.1080p", media_id=film.id)
    public, _ = addons.store(session, film, addons.parse_stream(MEDIAFUSION))
    held, _ = addons.store(session, film, addons.parse_stream(
        {**COMET, "name": "[RD+] Comet 2160p"}))
    assert (torrent_summary(filelist)["origin_label"], torrent_summary(filelist)["debrid"]) == ("Filelist", False)
    assert torrent_summary(public)["origin_label"] == "1337x"
    assert torrent_summary(held)["origin_label"] == "ThePirateBay" and torrent_summary(held)["debrid"]


def test_filelist_is_preferred_at_the_same_resolution_never_above_it(world):
    from vibestream.services import ranking

    session, _, film = world
    filelist = Torrent(id=13, name="The.Shawshank.Redemption.1994.1080p.BluRay.x264", media_id=film.id,
                       resolution="1080p", source="BluRay", video_codec="x264", seeders=20)
    public_1080, _ = addons.store(session, film, addons.parse_stream(
        {"title": "The.Shawshank.Redemption.1994.1080p.BluRay.x265\n\U0001F464 300 \U0001F4BE 2 GB",
         "infoHash": "1" * 40}))
    public_2160, _ = addons.store(session, film, addons.parse_stream(
        {"title": "The.Shawshank.Redemption.1994.2160p.WEB-DL.x265\n\U0001F464 30 \U0001F4BE 9 GB",
         "infoHash": "2" * 40}))
    ranked = [s.torrent for s in ranking.rank([public_1080, filelist, public_2160])]
    assert ranked == [public_2160, filelist, public_1080]
