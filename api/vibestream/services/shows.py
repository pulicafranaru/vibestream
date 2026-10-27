"""Shows: TMDB's seasons and episodes, and which of them have files on disk."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Download, Episode, Media, Season, Torrent, utcnow
from .tmdb import TMDBClient, TMDBError

log = logging.getLogger(__name__)

# Re-fetch a season this long after the last sync: metadata changes late and
# running shows gain episodes.
SEASON_TTL = timedelta(days=2)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".mov"}

# S01E02, 1x02, S01.E02. Scene names only, not a general-purpose parser.
_EPISODE_PATTERNS = (
    re.compile(r"[Ss](?P<season>\d{1,2})[\s._-]*[Ee](?P<episode>\d{1,3})"),
    re.compile(r"(?<![\d])(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?![\d])"),
)


def parse_slot(name: str) -> tuple[int, int] | None:
    for pattern in _EPISODE_PATTERNS:
        found = pattern.search(name)
        if found:
            return int(found.group("season")), int(found.group("episode"))
    return None


# <show>.SxxEyy.<title>.<quality>.<source>.<codec>-<group>: the title ends at
# the resolution, the first technical token.
_RESOLUTION_RE = re.compile(r"^\d{3,4}[pi]$", re.IGNORECASE)

_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "in", "to", "is", "it", "this", "s", "on"}
)

# Share of the filename's title that must appear in the episode's name.
# Releases abbreviate and misspell, so half.
_TITLE_MATCH_MIN = 0.5


def file_title(name: str) -> str | None:
    for pattern in _EPISODE_PATTERNS:
        found = pattern.search(name)
        if not found:
            continue
        words: list[str] = []
        for token in re.split(r"[.\s_]+", name[found.end():]):
            if not token:
                continue
            if _RESOLUTION_RE.match(token):
                break
            words.append(token)
        return " ".join(words) or None
    return None


def _tokens(text: str) -> set[str]:
    # Apostrophes are dropped, not split on, so curly and straight ones match.
    plain = text.lower().replace("’", "").replace("'", "")
    return {t for t in re.split(r"[^a-z0-9]+", plain) if t and t not in _STOPWORDS}


def title_score(file_name: str, episode_name: str) -> float:
    from_file = _tokens(file_name)
    if not from_file:
        return 0.0
    return len(from_file & _tokens(episode_name)) / len(from_file)


def realign_by_title(
    numbered: dict[int, str], names: dict[int, str]
) -> dict[int, str]:
    """Re-key a season's files by the episode their titles say they are.

    Only when every name and title is present and every match is clear, unique and different; otherwise `numbered` stands.
    """
    if not numbered or not names or any(not name for name in names.values()):
        return numbered

    titles: dict[int, str] = {}
    for number, path in numbered.items():
        title = file_title(os.path.basename(path))
        if not title:
            return numbered
        titles[number] = title

    chosen: dict[int, int] = {}
    for number, title in titles.items():
        ranked = sorted(
            ((title_score(title, name), episode) for episode, name in names.items()),
            reverse=True,
        )
        best_score, best_episode = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < _TITLE_MATCH_MIN or best_score <= runner_up:
            return numbered
        chosen[number] = best_episode

    if len(set(chosen.values())) != len(chosen):
        return numbered
    if all(number == episode for number, episode in chosen.items()):
        return numbered

    for number, episode in sorted(chosen.items()):
        if number != episode:
            log.warning(
                "file numbered E%02d (%r) is episode E%02d (%r), by title",
                number, titles[number], episode, names[episode],
            )
    return {chosen[number]: path for number, path in numbered.items()}


async def sync_seasons(session: Session, media: Media) -> int:
    if media.media_type != "tv" or not media.tmdb_id:
        return 0

    client = TMDBClient()
    details = await client.tv_details(media.tmdb_id)
    known = {s.number: s for s in session.scalars(
        select(Season).where(Season.media_id == media.id)
    )}

    count = 0
    for payload in details.get("seasons") or []:
        number = payload.get("season_number")
        if number is None:
            continue
        season = known.get(number) or Season(media_id=media.id, number=number)
        season.name = payload.get("name") or f"Season {number}"
        season.overview = payload.get("overview") or None
        season.air_date = payload.get("air_date") or None
        season.poster_path = payload.get("poster_path") or None
        season.episode_count = int(payload.get("episode_count") or 0)
        if season.id is None:
            session.add(season)
        count += 1
    session.commit()
    return count


_WRITING = {"Writer", "Screenplay", "Teleplay", "Story", "Written By"}
GUEST_LIMIT = 15


def episode_facts(item: dict) -> dict:
    crew = item.get("crew") or []
    person_ids: dict[str, int] = {}

    def names(people) -> list[str]:
        out: list[str] = []
        for person in people:
            name = person.get("name")
            if not name or name in out:
                continue
            out.append(name)
            if person.get("id"):
                person_ids[name] = person["id"]
        return out

    guests = sorted(item.get("guest_stars") or [], key=lambda p: p.get("order") or 0)[:GUEST_LIMIT]
    return {
        "directors": names(p for p in crew if p.get("job") == "Director"),
        "writers": names(p for p in crew if p.get("job") in _WRITING),
        "guest_stars": [
            {"name": name, "character": next(
                (p.get("character") or None for p in guests if p.get("name") == name), None)}
            for name in names(guests)
        ],
        "person_ids": person_ids,
    }


async def sync_episodes(session: Session, media: Media, number: int,
                        force: bool = False) -> Season | None:
    season = session.scalar(
        select(Season).where(Season.media_id == media.id, Season.number == number)
    )
    if season is None:
        await sync_seasons(session, media)
        season = session.scalar(
            select(Season).where(Season.media_id == media.id, Season.number == number)
        )
    if season is None or not media.tmdb_id:
        return None

    fresh = season.synced_at and (utcnow() - season.synced_at) < SEASON_TTL
    if fresh and season.episodes and not force:
        return season

    try:
        payload = await TMDBClient().tv_season(media.tmdb_id, number)
    except TMDBError as exc:
        log.warning("could not fetch %s season %s: %s", media.title, number, exc)
        return season

    known = {e.number: e for e in season.episodes}
    for item in payload.get("episodes") or []:
        slot = item.get("episode_number")
        if slot is None:
            continue
        episode = known.get(slot) or Episode(
            media_id=media.id, season_id=season.id,
            season_number=number, number=slot,
        )
        episode.tmdb_id = item.get("id")
        episode.name = item.get("name") or None
        episode.overview = item.get("overview") or None
        episode.air_date = item.get("air_date") or None
        episode.runtime = item.get("runtime")
        episode.still_path = item.get("still_path") or None
        episode.vote_average = item.get("vote_average")
        episode.facts = json.dumps(episode_facts(item))
        if episode.id is None:
            session.add(episode)

    season.synced_at = utcnow()
    session.commit()
    # The new episodes are not in the list read above; expire it so it is re-read.
    session.expire(season, ["episodes"])
    return season


async def sync_show(session: Session, media: Media, seasons_limit: int = 0) -> None:
    await sync_seasons(session, media)

    wanted = {
        row.season_number
        for row in session.scalars(
            select(Episode).where(Episode.media_id == media.id,
                                  Episode.file_path.is_not(None))
        )
    }
    for torrent in media.torrents:
        if torrent.download and torrent.season is not None:
            wanted.add(torrent.season)

    for number in sorted(wanted)[: seasons_limit or len(wanted)]:
        await sync_episodes(session, media, number)


def covers(torrent: Torrent, season: int, episode: int) -> bool:
    """Does this release hold that episode? S02E05, S02 or S01-S05; no season covers nothing."""
    if torrent.season is None:
        return False
    last = torrent.season_end or torrent.season
    if not (torrent.season <= season <= last):
        return False
    return torrent.episode is None or torrent.episode == episode


def releases_for(
    session: Session, media: Media, season: int, episode: int, limit: int = 4
) -> list[Torrent]:
    from .offered import offered
    from .ranking import rank

    candidates = [
        torrent for torrent in offered(media.torrents) if covers(torrent, season, episode)
    ]
    if not candidates:
        return []
    ordered = [scored.torrent for scored in rank(candidates)]
    # Single episodes before season packs. Quality order comes from a snapshot:
    # reading positions out of the list being sorted raises.
    position = {torrent.id: index for index, torrent in enumerate(ordered)}
    ordered.sort(key=lambda t: (t.episode is None, position[t.id]))
    return ordered[:limit]


def _video_files(root: str) -> list[str]:
    if os.path.isfile(root):
        return [root] if os.path.splitext(root)[1].lower() in VIDEO_EXTENSIONS else []
    found = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS:
                found.append(os.path.join(dirpath, name))
    return sorted(found)


async def slot_files(
    session: Session, media: Media, torrent: Torrent | None, paths: list[str],
    sync: bool = True,
) -> dict[tuple[int, int], str]:
    """{(season, episode): path} for these files, shared by download and playback so both agree."""
    slots: dict[tuple[int, int], str] = {}
    for path in paths:
        slot = parse_slot(os.path.basename(path))
        if slot is None and torrent is not None and torrent.season is not None \
                and torrent.episode is not None:
            slot = (torrent.season, torrent.episode)
        if slot is not None:
            slots[slot] = path
    if not slots:
        return {}

    if sync:
        for number in sorted({season for season, _ in slots}):
            await sync_episodes(session, media, number)

    corrected: dict[tuple[int, int], str] = {}
    for season_number in sorted({season for season, _ in slots}):
        numbered = {
            episode: path
            for (season, episode), path in slots.items()
            if season == season_number
        }
        names = {
            episode.number: episode.name or ""
            for episode in session.scalars(
                select(Episode).where(
                    Episode.media_id == media.id,
                    Episode.season_number == season_number,
                )
            )
        }
        for episode, path in realign_by_title(numbered, names).items():
            corrected[(season_number, episode)] = path
    return corrected


VIDEO_SUFFIXES = tuple(VIDEO_EXTENSIONS)


def pack_video_paths(meta_files) -> list[str]:
    return [
        f.path for f in meta_files
        if os.path.splitext(f.path)[1].lower() in VIDEO_EXTENSIONS
        and "sample" not in os.path.basename(f.path).lower()
    ]


async def attach_files(session: Session, download: Download) -> int:
    """Point each episode at its file, by the published (hardlinked, stable) library path."""
    torrent = download.torrent
    media = torrent.media if torrent else None
    if not media or media.media_type != "tv":
        return 0

    root = download.library_path or download.content_path or download.save_path
    if not root or not os.path.exists(root):
        return 0

    files = _video_files(root)
    if not files:
        return 0

    slots = await slot_files(session, media, torrent, files)
    # Only this download's own files: several downloads of a season share one folder.
    if torrent.episode is not None and torrent.season is not None:
        slots = {k: v for k, v in slots.items() if k == (torrent.season, torrent.episode)}
    else:
        from .downloads import cached_meta

        meta = cached_meta(torrent.id)
        if meta is not None:
            names = {os.path.basename(f.path) for f in meta.files}
            slots = {k: v for k, v in slots.items() if os.path.basename(v) in names}
    if not slots:
        return 0

    attached = 0
    for (season_number, episode_number), path in sorted(slots.items()):
        episode = session.scalar(
            select(Episode).where(
                Episode.media_id == media.id,
                Episode.season_number == season_number,
                Episode.number == episode_number,
            )
        )
        if episode is None:
            # A file TMDB does not know is skipped, not shown as a nonexistent episode.
            log.info(
                "%s S%02dE%02d is on disk but not in TMDB, skipping",
                media.title, season_number, episode_number,
            )
            continue
        # A slot that changes hands is not prepared any more: prepared_at describes the
        # file, and the rendition is keyed by path.
        if episode.file_path != path:
            episode.prepared_at = None
            episode.prepare_error = None
        episode.download_id = download.id
        episode.file_path = path
        try:
            episode.file_size = os.path.getsize(path)
        except OSError:
            episode.file_size = None
        attached += 1

    session.commit()
    log.info("attached %s file(s) to episodes of %s", attached, media.title)
    return attached


def detach_files(session: Session, download_id: int) -> int:
    rows = list(session.scalars(
        select(Episode).where(Episode.download_id == download_id)
    ))
    for episode in rows:
        episode.download_id = None
        episode.file_path = None
        episode.file_size = None
        episode.prepared_at = None
        episode.prepare_error = None
        episode.source_removed_at = None
    if rows:
        session.commit()
    return len(rows)


async def backfill(session: Session) -> int:
    linked = session.scalars(
        select(Download).where(
            Download.library_path.is_not(None),
            Download.reaped_at.is_(None),
            Download.state.in_(["completed", "seeding", "linked"]),
        )
    )
    done = 0
    for download in linked:
        torrent = download.torrent
        media = torrent.media if torrent else None
        if not media or media.media_type != "tv":
            continue
        already = session.scalar(
            select(Episode.id).where(Episode.download_id == download.id).limit(1)
        )
        if already:
            continue
        if await attach_files(session, download):
            await sync_show(session, media)
            done += 1
    return done
