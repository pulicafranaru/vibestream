"""What a show's main button does for one profile, and what Download offers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Download, Episode, EpisodeProgress, Media, Season, Torrent
from .nextup import RESUME_MIN_SECONDS, describe
from .offered import offered

ACTIVE = ("requested", "adding", "downloading")


def _aired(episode: Episode) -> bool:
    if not episode.air_date:
        return True
    try:
        return date.fromisoformat(episode.air_date) <= date.today()
    except ValueError:
        return True


def _best(torrents: list[Torrent]) -> Torrent | None:
    from .ranking import rank

    ranked = rank(torrents)
    return ranked[0].torrent if ranked else None


def _season_pack(media: Media, number: int) -> Torrent | None:
    """The best release of exactly that season. Multi-season packs are excluded."""
    from .shows import covers

    whole = [t for t in offered(media.torrents) if t.episode is None and covers(t, number, 1)]
    single = [t for t in whole if not t.season_end or t.season_end == t.season]
    return _best(single or whole)


async def _episodes(session: Session, media: Media, seasons: list[Season],
                    upto: int) -> list[Episode]:
    from . import shows

    for season in seasons:
        if season.number <= upto and season.synced_at is None:
            await shows.sync_episodes(session, media, season.number)
    return list(session.scalars(
        select(Episode)
        .where(Episode.media_id == media.id, Episode.season_number > 0)
        .order_by(Episode.season_number, Episode.number)
    ))


async def _packs(session: Session, media: Media, releases: list[Torrent]) -> dict:
    from . import downloads as dl_service
    from . import shows

    packs: dict[int, dict | None] = {}
    for torrent in releases:
        if torrent.episode is not None:
            continue
        meta = dl_service.cached_meta(torrent.id)
        if meta is None:
            packs[torrent.id] = None
            continue
        slots = await shows.slot_files(
            session, media, torrent, shows.pack_video_paths(meta.files), sync=False
        )
        packs[torrent.id] = {"slots": slots, "sizes": {f.path: f.length for f in meta.files}}
    return packs


async def _fetching(session: Session, media: Media, episode: Episode,
                    downloads: dict[int, Download]) -> Download | None:
    from ..routers.catalog import _covering_download
    from . import shows

    releases = shows.releases_for(session, media, episode.season_number, episode.number)
    packs = await _packs(session, media, releases)
    found = _covering_download(releases, downloads, episode, packs)
    if found is None or found.state not in ACTIVE:
        return None
    return found


async def _episode_offer(session: Session, media: Media, episode: Episode,
                         first: bool) -> dict | None:
    from ..routers.catalog import _episode_share
    from . import shows

    releases = shows.releases_for(session, media, episode.season_number, episode.number)
    if not releases:
        return None
    release = releases[0]
    season = session.scalar(select(Season).where(
        Season.media_id == media.id, Season.number == episode.season_number
    ))
    packs = await _packs(session, media, [release])
    share = _episode_share(release, episode, packs.get(release.id),
                           max(1, season.episode_count if season else 1))
    return {
        "kind": "episode",
        "title": "Episode 1" if first else "Next Episode",
        "detail": f"S{episode.season_number}:E{episode.number}  {episode.name or ''}".strip(),
        "size_gb": share["episode_size_gb"] or None,
        "size_exact": share["episode_size_exact"],
        "fetch": [{
            "release_id": release.id,
            "episode_id": episode.id if release.episode is None else None,
        }],
    }


def _season_offer(media: Media, number: int, downloads: dict[int, Download]) -> dict | None:
    pack = _season_pack(media, number)
    if pack is None:
        return None
    started = downloads.get(pack.id)
    started = started if started and started.state not in ("removed", "error") else None
    return {
        "kind": "season",
        "title": f"Rest of Season {number}" if started else f"Season {number}",
        "detail": "Every episode, in one download",
        "size_gb": round((pack.size_bytes or 0) / 1024 ** 3, 1),
        "fetch": [{"release_id": pack.id, "all": bool(started)}],
    }


def _series_offer(media: Media, numbers: list[int],
                  downloads: dict[int, Download]) -> dict | None:
    if len(numbers) < 2:
        return None
    first, last = numbers[0], numbers[-1]
    spanning = [
        t for t in offered(media.torrents)
        if t.episode is None and t.season is not None
        and t.season <= first and (t.season_end or t.season) >= last
    ]
    picks = [_best(spanning)] if spanning else [_season_pack(media, n) for n in numbers]
    picks = [p for p in dict.fromkeys(p for p in picks if p)]
    if not picks:
        return None
    covered = len(numbers) if spanning else sum(
        1 for n in numbers if _season_pack(media, n) is not None
    )
    detail = f"All {len(numbers)} seasons" if covered == len(numbers) else (
        f"{covered} of {len(numbers)} seasons are on the tracker"
    )
    fetch = []
    for pick in picks:
        started = downloads.get(pick.id)
        fetch.append({"release_id": pick.id, "all": bool(
            started and started.state not in ("removed", "error")
        )})
    return {
        "kind": "series",
        "title": "Entire Series",
        "detail": detail,
        "size_gb": round(sum(p.size_bytes or 0 for p in picks) / 1024 ** 3, 1),
        "fetch": fetch,
    }


async def show_plan(session: Session, media: Media, profile_id: int | None,
                    downloads: dict[int, Download]) -> dict:
    seasons = [s for s in session.scalars(
        select(Season).where(Season.media_id == media.id, Season.number > 0)
        .order_by(Season.number)
    ) if s.episode_count]
    numbers = [s.number for s in seasons]

    progress: dict[int, EpisodeProgress] = {}
    if profile_id:
        progress = {
            row.episode_id: row for row in session.scalars(
                select(EpisodeProgress)
                .join(Episode, Episode.id == EpisodeProgress.episode_id)
                .where(EpisodeProgress.profile_id == profile_id,
                       Episode.media_id == media.id)
            )
        }

    def watched(episode: Episode) -> bool:
        own = progress.get(episode.id)
        return own is not None and own.finished_at is not None

    episodes = await _episodes(session, media, seasons, upto=numbers[0] if numbers else 0)
    furthest = max(
        (i for i, e in enumerate(episodes) if e.file_path or watched(e)), default=-1
    )
    if furthest >= 0 and furthest == len(episodes) - 1:
        last = episodes[furthest].season_number
        later = [n for n in numbers if n > last]
        if later:
            episodes = await _episodes(session, media, seasons, upto=later[0])

    held = [e for e in episodes if e.file_path]
    unwatched = next((e for e in held if not watched(e)), None)
    upcoming = next(
        (e for e in episodes[furthest + 1:] if not e.file_path and _aired(e)), None
    )
    target = upcoming if furthest >= 0 else next((e for e in episodes if _aired(e)), None)

    offers = []
    if target is not None:
        offers.append(await _episode_offer(session, media, target, first=furthest < 0))
        offers.append(_season_offer(media, target.season_number, downloads))
    offers.append(_series_offer(media, numbers, downloads))
    offers = [o for o in offers if o]

    def episode_ref(e: Episode) -> dict:
        return {"season": e.season_number, "number": e.number,
                "label": f"S{e.season_number}:E{e.number}", "name": e.name}

    primary: dict
    if unwatched is not None and unwatched.prepared_at is not None:
        own = progress.get(unwatched.id)
        kind = "resume" if own and own.resume_seconds > RESUME_MIN_SECONDS else "next"
        primary = {"action": "play", **describe(unwatched, kind, own)}
    elif unwatched is not None:
        primary = {"action": "preparing", **episode_ref(unwatched)}
    elif target is not None and (found := await _fetching(session, media, target, downloads)):
        primary = {"action": "downloading", **episode_ref(target),
                   "torrent_id": found.torrent_id, "download_id": found.id}
    elif not held:
        primary = {"action": "choose"}
    elif target is not None and offers and offers[0]["kind"] == "episode":
        primary = {"action": "download", **episode_ref(target), "offer": offers[0]}
    else:
        first = held[0]
        primary = (
            {"action": "rewatch", **describe(first, "start")} if first.prepared_at
            else {"action": "preparing", **episode_ref(first)}
        )

    return {"primary": primary, "offers": offers}
