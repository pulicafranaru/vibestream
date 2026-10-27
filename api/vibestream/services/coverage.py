"""Coverage: the share of a show's aired episodes some release holds, which weighs popularity."""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..models import Media, Torrent

FLOOR = 0.02
UNMEASURED = 0.09
WATCHABLE = 0.6


def aired_episodes(facts: dict) -> dict[int, int]:
    per_season = {
        int(number): int(count or 0)
        for number, count in (facts.get("season_episodes") or {}).items()
        if int(number) > 0
    }
    if not per_season:
        seasons, episodes = facts.get("seasons") or 0, facts.get("episodes") or 0
        if not seasons or not episodes:
            return {}
        per_season = {n: round(episodes / seasons) for n in range(1, seasons + 1)}

    last = facts.get("last_aired")
    if last:
        last_season, last_episode = int(last[0]), int(last[1])
        per_season = {
            n: (count if n < last_season else min(count, last_episode) if n == last_season else 0)
            for n, count in per_season.items()
        }
    return {n: c for n, c in per_season.items() if c > 0}


def coverage(facts: dict, releases: list[tuple[int | None, int | None, int | None]]) -> float | None:
    """Releases are (season, season_end, episode) as parsed from their names."""
    aired = aired_episodes(facts)
    total = sum(aired.values())
    if not total:
        return None

    whole: set[int] = set()
    singles: dict[int, set[int]] = defaultdict(set)
    for season, season_end, episode in releases:
        if season is None:
            if episode is None:
                return 1.0
            continue
        if episode is None:
            whole.update(range(season, (season_end or season) + 1))
        else:
            singles[season].add(episode)

    held = 0
    for number, count in aired.items():
        if number in whole:
            held += count
        else:
            held += len([e for e in singles.get(number, ()) if 1 <= e <= count])
    return min(1.0, held / total)


def refresh(session: Session) -> int:
    shows = {
        media_id: raw
        for media_id, raw in session.execute(
            select(Media.id, Media.facts).where(Media.media_type == "tv")
        )
    }
    releases: dict[int, list] = defaultdict(list)
    for media_id, season, season_end, episode in session.execute(
        select(Torrent.media_id, Torrent.season, Torrent.season_end, Torrent.episode)
        .join(Media, Media.id == Torrent.media_id)
        .where(Media.media_type == "tv")
    ):
        releases[media_id].append((season, season_end, episode))

    changed = 0
    for media in session.scalars(select(Media).where(Media.id.in_(shows))):
        try:
            facts = json.loads(shows[media.id] or "{}")
        except ValueError:
            facts = {}
        value = coverage(facts, releases.get(media.id, []))
        value = None if value is None else round(value, 4)
        if media.coverage != value:
            media.coverage = value
            changed += 1
    session.commit()
    return changed


def watchable():
    """A film, a show not yet measured, or a show the tracker has most of."""
    from sqlalchemy import or_

    return or_(Media.media_type != "tv", Media.coverage.is_(None),
               Media.coverage >= WATCHABLE)


def weight():
    """1 for a film, coverage squared for a show."""
    covered = Media.coverage * Media.coverage
    return case(
        (Media.media_type != "tv", 1.0),
        (Media.coverage.is_(None), UNMEASURED),
        (covered < FLOOR, FLOOR),
        else_=covered,
    )


def title_weight(media: Media) -> float:
    if media.media_type != "tv":
        return 1.0
    if media.coverage is None:
        return UNMEASURED
    return max(media.coverage * media.coverage, FLOOR)


def ranked_popularity():
    from sqlalchemy import func

    return func.coalesce(Media.popularity, 0.0) * weight()
