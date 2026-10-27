"""What to watch next in a show, for one profile."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import Episode, EpisodeProgress

# Below this an episode counts as barely started and restarts from the top.
RESUME_MIN_SECONDS = 30


def following_episode(session: Session, episode: Episode) -> Episode | None:
    """The episode straight after this one, in season order, specials left out."""
    query = select(Episode).where(
        Episode.media_id == episode.media_id,
        or_(
            Episode.season_number > episode.season_number,
            and_(Episode.season_number == episode.season_number,
                 Episode.number > episode.number),
        ),
    )
    if episode.season_number > 0:
        query = query.where(Episode.season_number > 0)
    return session.scalar(query.order_by(Episode.season_number, Episode.number).limit(1))


def describe(episode: Episode, kind: str, progress: EpisodeProgress | None = None) -> dict:
    resume = progress.resume_seconds if (progress and kind == "resume") else 0.0
    runtime = (progress.runtime_seconds if progress else 0.0) or (episode.runtime or 0) * 60
    return {
        "kind": kind,                       # resume | next | start
        "play_id": f"e{episode.id}",
        "season": episode.season_number,
        "number": episode.number,
        "name": episode.name or f"Episode {episode.number}",
        "label": f"S{episode.season_number}:E{episode.number}",
        "resume_seconds": round(resume),
        "resume_percent": round(min(100.0, resume / runtime * 100), 1) if runtime else 0.0,
    }


def _progress_for(session: Session, profile_id: int, episode_id: int) -> EpisodeProgress | None:
    return session.scalar(select(EpisodeProgress).where(
        EpisodeProgress.profile_id == profile_id,
        EpisodeProgress.episode_id == episode_id,
    ))


def after(session: Session, profile_id: int, episode: Episode,
          progress: EpisodeProgress) -> dict | None:
    if progress.finished_at is None:
        if episode.prepared_at is None:
            return None
        kind = "resume" if progress.resume_seconds > RESUME_MIN_SECONDS else "start"
        return describe(episode, kind, progress)

    following = following_episode(session, episode)
    if following is None or following.prepared_at is None:
        return None
    own = _progress_for(session, profile_id, following.id)
    if own is not None and own.finished_at is not None:
        return None
    if own is not None and own.resume_seconds > RESUME_MIN_SECONDS:
        return describe(following, "resume", own)
    return describe(following, "next")


def next_up(session: Session, media_id: int, profile_id: int | None) -> dict | None:
    if profile_id:
        latest = session.execute(
            select(EpisodeProgress, Episode)
            .join(Episode, Episode.id == EpisodeProgress.episode_id)
            .where(EpisodeProgress.profile_id == profile_id, Episode.media_id == media_id)
            .order_by(EpisodeProgress.updated_at.desc())
            .limit(1)
        ).first()
        if latest is not None:
            progress, episode = latest
            offer = after(session, profile_id, episode, progress)
            if offer is not None:
                return offer

    first = session.scalar(
        select(Episode)
        .where(Episode.media_id == media_id, Episode.prepared_at.is_not(None))
        .order_by((Episode.season_number == 0), Episode.season_number, Episode.number)
        .limit(1)
    )
    return describe(first, "start") if first is not None else None
