from __future__ import annotations

import json

import logging
import os
import re
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Download, Episode, EpisodeProgress, Media, WatchProgress, utcnow
from ..services import hls, live, mediainfo, nextup, stills, streaming, subtitles, trickplay
from ..services.tmdb import logo_url
from .profiles import current_profile_id, resolve_profile

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/play", tags=["player"])

_info_cache: dict[tuple, mediainfo.MediaInfo] = {}

FINISHED_RATIO = 0.95
RESUME_MIN_SECONDS = 30


@dataclass
class Target:
    """A play id: `12` is a download, `e34` an episode inside one."""

    download: Download
    path: str
    episode: Episode | None = None

    @property
    def id(self) -> str:
        return f"e{self.episode.id}" if self.episode else str(self.download.id)

    @property
    def title(self) -> str:
        if self.episode:
            media = self.episode.media
            label = f"S{self.episode.season_number:02d}E{self.episode.number:02d}"
            name = self.episode.name or label
            return f"{media.title if media else ''} {label} {name}".strip()
        torrent = self.download.torrent
        return (torrent.parsed_title if torrent else None) or ""

    @property
    def media_id(self) -> int | None:
        if self.episode:
            return self.episode.media_id
        torrent = self.download.torrent
        return torrent.media_id if torrent else None

    @property
    def media(self) -> Media | None:
        if self.episode:
            return self.episode.media
        torrent = self.download.torrent
        return torrent.media if torrent else None

    def presentation(self) -> dict:
        media = self.media
        episode = self.episode
        overview = None
        if episode is not None and episode.overview:
            overview = episode.overview
        elif media is not None:
            overview = media.overview

        facts: dict = {}
        if media is not None and media.facts:
            try:
                facts = json.loads(media.facts) or {}
            except ValueError:
                facts = {}
        return {
            "title": (media.title if media else None) or self.title,
            "year": media.year if media else None,
            "certification": facts.get("certification"),
            "logo": logo_url(facts.get("logo")),
            "overview": overview,
            "episode": None if episode is None else {
                "season": episode.season_number,
                "number": episode.number,
                "name": episode.name,
            },
        }


def _load(session: Session, play_id: str) -> Target:
    if play_id.startswith("e"):
        episode = session.get(Episode, _int_or_404(play_id[1:]))
        if episode is None:
            raise HTTPException(404, "unknown episode")
        download = session.get(Download, episode.download_id) if episode.download_id else None
        if download is None:
            raise HTTPException(409, "that episode has no download")
        path = streaming.canonical_path(download, episode)
        if not path or not (os.path.exists(path) or episode.source_removed_at):
            raise HTTPException(409, "that episode is not downloaded")
        return Target(download=download, path=path, episode=episode)

    download = session.get(Download, _int_or_404(play_id))
    if download is None:
        raise HTTPException(404, "unknown download")
    path = streaming.canonical_path(download)
    if not path or not (os.path.exists(path) or download.source_removed_at):
        raise HTTPException(409, "no playable file on disk yet")
    return Target(download=download, path=path)


def next_episode(session: Session, episode: Episode | None) -> dict | None:
    if episode is None:
        return None
    following = nextup.following_episode(session, episode)
    if following is None or following.prepared_at is None:
        return None
    return {
        "play_id": f"e{following.id}",
        "season": following.season_number,
        "number": following.number,
        "name": following.name or f"Episode {following.number}",
        "overview": following.overview,
        "still": stills.episode_still(following),
    }


def _int_or_404(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(404, "unknown id") from None


def _identity(path: str) -> tuple:
    try:
        st = os.stat(path)
    except OSError:
        return (path, None, None)
    return (path, st.st_size, st.st_mtime_ns)


async def _info(path: str) -> mediainfo.MediaInfo:
    key = _identity(path)
    cached = _info_cache.get(key)
    if cached:
        return cached
    try:
        info = await mediainfo.probe(path)
    except mediainfo.ProbeError as exc:
        raise HTTPException(500, f"could not probe the file: {exc}") from exc
    if len(_info_cache) >= 256:
        _info_cache.clear()
    _info_cache[key] = info
    return info


def _audio(info: mediainfo.MediaInfo, audio: int | None) -> int | None:
    if audio is not None and audio not in {a.index for a in info.audio}:
        raise HTTPException(404, "this title has no such audio track")
    return audio


async def _session(info: mediainfo.MediaInfo, audio: int | None) -> hls.Session:
    try:
        return await hls.ensure_session(info, audio)
    except hls.SourceGone as exc:
        raise HTTPException(410, str(exc)) from exc


def _no_cache(body: str, media_type: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"},
    )


def _plays_live(target: Target) -> bool:
    return live.enabled(target.id) and os.path.exists(target.path)


def _live_progress(info: mediainfo.MediaInfo, path: str) -> dict:
    ready = live.has_index(path)
    return {
        "ready": ready,
        "running": not ready and live.indexing(path),
        "percent": 100.0 if ready else 0.0,
        "seconds_ready": round(info.duration) if ready else 0,
        "duration": round(info.duration),
        "eta_seconds": None,
        "error": None if ready else live.index_error(path),
    }


def _rendition_ready(info: mediainfo.MediaInfo, audio: int | None) -> hls.Session | None:
    existing = hls.peek_session(info, audio)
    return existing if existing is not None and existing.complete else None


def _resume_for(session: Session, target: Target, profile_id: int | None) -> dict:
    profile = resolve_profile(session, profile_id)
    if target.episode is not None:
        progress = session.scalar(
            select(EpisodeProgress).where(
                EpisodeProgress.profile_id == profile.id,
                EpisodeProgress.episode_id == target.episode.id,
            )
        )
    else:
        progress = session.scalar(
            select(WatchProgress).where(
                WatchProgress.profile_id == profile.id,
                WatchProgress.download_id == target.download.id,
            )
        )
    if progress is None:
        return {"seconds": 0, "runtime": 0, "finished": False}
    return {
        "seconds": progress.resume_seconds,
        "runtime": progress.runtime_seconds,
        "finished": progress.finished_at is not None,
    }


@router.get("/{play_id}/info")
async def play_info(
    play_id: str,
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    target = _load(session, play_id)
    path = target.path
    info = await _info(path)

    subs = subtitles.embedded_tracks(info, settings_languages())
    default_audio = info.default_audio()

    # Must not start an ffmpeg run: /info only populates the UI.
    existing = hls.peek_session(info, None)
    preparation = existing.progress() if existing else {
        "ready": False, "running": False, "percent": 0.0,
        "duration": round(info.duration), "eta_seconds": None, "error": None,
    }
    if _plays_live(target) and (live.has_index(path) or existing is None or not existing.complete):
        preparation = _live_progress(info, path)

    return {
        "play_id": play_id,
        "title": target.title,
        "media_id": target.media_id,
        "presentation": target.presentation(),
        "next": next_episode(session, target.episode),
        "media": mediainfo.summarise(info),
        "resume": _resume_for(session, target, profile_id),
        "preparation": preparation,
        "playback": {
            "mode": "transcode" if info.needs_video_transcode else "remux",
            "video_passthrough": not info.needs_video_transcode,
            "audio_transcoded": bool(
                default_audio and default_audio.codec not in mediainfo.WEBOS_AUDIO
            ),
            "hls": f"/api/play/{play_id}/master.m3u8",
            "engine": "live" if _plays_live(target) else "renditions",
        },
        "file": {
            "name": os.path.basename(path),
            "size_bytes": os.path.getsize(path) if os.path.exists(path) else None,
        },
        "subtitles": [
            {
                "id": t.id, "label": t.label, "language": t.language,
                "source": t.source, "forced": t.forced, "sdh": t.sdh,
                "default": t.default,
            }
            for t in subs.tracks
        ],
        "subtitles_unavailable": subs.unavailable,
        "audio": [
            {
                "index": a.index, "label": a.label, "language": a.language,
                "codec": a.codec, "channels": a.channels, "default": a.is_default,
            }
            for a in info.audio
            if os.path.exists(path) or a.index in hls.kept_audio(info)
        ],
    }


def settings_languages() -> list[str]:
    from ..config import settings

    return settings.subtitle_languages


@router.get("/{play_id}/master.m3u8")
async def master(
    play_id: str,
    audio: int | None = Query(None, description="audio stream index"),
    session: Session = Depends(get_session),
):
    path = _load(session, play_id).path
    info = await _info(path)
    audio = _audio(info, audio)

    subs = subtitles.embedded_tracks(info, settings_languages())
    tracks = [
        {
            "id": t.id, "label": t.label, "language": t.language,
            "default": t.default, "forced": t.forced,
        }
        for t in subs.tracks
    ]
    return _no_cache(
        hls.master_playlist(info, f"/api/play/{play_id}", tracks,
                            f"?audio={audio}" if audio is not None else ""),
        "application/vnd.apple.mpegurl",
    )


@router.get("/{play_id}/about")
async def about(play_id: str, session: Session = Depends(get_session)):
    target = _load(session, play_id)
    if target.episode is None:
        return {}
    return await episode_about(session, target.episode)


async def episode_about(session: Session, episode: Episode) -> dict:
    from ..services import shows

    media = episode.media
    if episode.facts is None and media is not None and media.tmdb_id:
        await shows.sync_episodes(session, media, episode.season_number, force=True)
        session.refresh(episode)
    try:
        facts = json.loads(episode.facts) if episode.facts else {}
    except ValueError:
        facts = {}
    return {
        "season": episode.season_number,
        "number": episode.number,
        "name": episode.name,
        "overview": episode.overview,
        "air_date": episode.air_date,
        "runtime": episode.runtime,
        "vote_average": episode.vote_average,
        "still": stills.episode_still(episode),
        "directors": facts.get("directors") or [],
        "writers": facts.get("writers") or [],
        "guest_stars": facts.get("guest_stars") or [],
        "person_ids": facts.get("person_ids") or {},
    }


class StartTrace(BaseModel):
    reason: str = Field(max_length=40)
    lines: list[str] = Field(default_factory=list, max_length=600)


@router.post("/{play_id}/trace")
def start_trace(play_id: str, trace: StartTrace, session: Session = Depends(get_session)):
    from ..db import record_event

    level = "info" if trace.reason == "ok" else "warn"
    detail = "\n".join(line[:400] for line in trace.lines)
    record_event(session, "player", f"start {trace.reason}: {play_id}", detail, level=level)
    session.commit()
    return {"ok": True}


@router.post("/{play_id}/progress")
def report_progress(
    play_id: str,
    position: float = Query(..., ge=0),
    duration: float = Query(0, ge=0),
    profile_id: int | None = Depends(current_profile_id),
    session: Session = Depends(get_session),
):
    target = _load(session, play_id)
    profile = resolve_profile(session, profile_id)

    if target.episode is not None:
        progress = session.scalar(
            select(EpisodeProgress).where(
                EpisodeProgress.profile_id == profile.id,
                EpisodeProgress.episode_id == target.episode.id,
            )
        )
        if progress is None:
            progress = EpisodeProgress(
                profile_id=profile.id, episode_id=target.episode.id
            )
            session.add(progress)
    else:
        progress = session.scalar(
            select(WatchProgress).where(
                WatchProgress.profile_id == profile.id,
                WatchProgress.download_id == target.download.id,
            )
        )
        if progress is None:
            progress = WatchProgress(
                profile_id=profile.id, download_id=target.download.id
            )
            session.add(progress)

    total = duration or progress.runtime_seconds or 0
    progress.resume_seconds = position
    if duration:
        progress.runtime_seconds = duration
    progress.updated_at = utcnow()

    if total and position >= total * FINISHED_RATIO:
        progress.finished_at = utcnow()
        progress.resume_seconds = 0.0
    elif position > RESUME_MIN_SECONDS:
        progress.finished_at = None

    session.commit()
    return {
        "ok": True,
        "profile_id": profile.id,
        "resume_seconds": progress.resume_seconds,
        "finished": progress.finished_at is not None,
    }


@router.get("/{play_id}/prepare")
async def prepare(
    play_id: str,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    """Start or report the rendition build. Served only once complete: players
    join a growing HLS playlist at the live edge."""
    target = _load(session, play_id)
    path = target.path
    info = await _info(path)
    audio = _audio(info, audio)
    if _plays_live(target):
        if live.has_index(path):
            return _live_progress(info, path)
        live.start_index(path)
        made = _rendition_ready(info, audio)
        return made.progress() if made else _live_progress(info, path)
    play = await _session(info, audio)
    return play.progress()


@router.get("/{play_id}/index.m3u8")
async def media_playlist(
    play_id: str,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    """Serve ffmpeg's own VOD playlist, which has the true segment durations. Only once complete."""
    target = _load(session, play_id)
    path = target.path
    info = await _info(path)
    audio = _audio(info, audio)
    if _plays_live(target):
        index = live.load_index(path)
        if index is not None:
            base = f"/api/play/{play_id}/live/{live.new_token()}"
            query = f"?audio={audio}" if audio is not None else ""
            return _no_cache(live.media_playlist(index, base, query),
                             "application/vnd.apple.mpegurl")
        live.start_index(path)
        if _rendition_ready(info, audio) is None:
            raise HTTPException(
                503, detail={"status": "preparing", "percent": 0.0, "eta_seconds": None},
                headers={"Retry-After": "5"},
            )
    play = await _session(info, audio)

    if not play.complete:
        if play.error:
            raise HTTPException(500, play.error)
        progress = play.progress()
        raise HTTPException(
            503,
            detail={
                "status": "preparing",
                "percent": progress["percent"],
                "eta_seconds": progress["eta_seconds"],
            },
            headers={"Retry-After": "5"},
        )

    with open(play.playlist_path, "r", encoding="utf-8") as fh:
        body = fh.read()

    # ffmpeg writes bare filenames; point them at this download's endpoints.
    base = f"/api/play/{play_id}"
    suffix = f"?audio={audio}" if audio is not None else ""
    body = re.sub(r"^(seg\d+\.m4s)$", rf"{base}/\1{suffix}", body, flags=re.MULTILINE)
    body = body.replace('URI="init.mp4"', f'URI="{base}/init.mp4{suffix}"')
    return _no_cache(body, "application/vnd.apple.mpegurl")


async def _serve_session_file(
    session: Session, play_id: str, audio: int | None, name: str, media_type: str
) -> FileResponse:
    path = _load(session, play_id).path
    info = await _info(path)
    play = await _session(info, _audio(info, audio))

    target = os.path.join(play.dir, name)
    if not os.path.exists(target):
        if play.error:
            raise HTTPException(500, play.error)
        raise HTTPException(404, f"{name} is not part of this rendition")

    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{play_id}/init.mp4")
async def init_segment(
    play_id: str,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return await _serve_session_file(
        session, play_id, audio, "init.mp4", "video/mp4"
    )


@router.get("/{play_id}/seg{index}.m4s")
async def segment(
    play_id: str,
    index: str,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    if not index.isdigit():
        raise HTTPException(404, "bad segment index")
    return await _serve_session_file(
        session, play_id, audio, f"seg{index}.m4s", "video/iso.segment"
    )


async def _live_stream(session: Session, play_id: str, token: str, audio: int | None):
    target = _load(session, play_id)
    if not os.path.exists(target.path):
        raise HTTPException(410, "the source of this title is gone")
    index = live.load_index(target.path)
    if index is None:
        raise HTTPException(404, "this title has no keyframe index")
    audio = _audio(await _info(target.path), audio)
    return await live.stream_for(target.path, audio, token, index)


@router.get("/{play_id}/live/{token}/init.mp4")
async def live_init(
    play_id: str,
    token: str,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    stream = await _live_stream(session, play_id, token, audio)
    try:
        path = await live.init_file(stream.path, stream.audio)
    except live.LiveError as exc:
        raise HTTPException(500, str(exc)) from exc
    return FileResponse(path, media_type="video/mp4",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{play_id}/live/{token}/{name}")
async def live_segment(
    play_id: str,
    token: str,
    name: str,
    request: Request,
    audio: int | None = Query(None),
    session: Session = Depends(get_session),
):
    number = name.removesuffix(".m4s")
    if not name.endswith(".m4s") or not number.isdigit():
        raise HTTPException(404, "no such segment")
    stream = await _live_stream(session, play_id, token, audio)
    if int(number) >= len(stream.segments):
        raise HTTPException(404, "no such segment")
    try:
        pieces = await live.segment_files(stream, int(number), request.is_disconnected)
    except live.Superseded as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "1"}) from exc
    except live.LiveError as exc:
        log.error("live segment %s of %s failed: %s", number, play_id, exc)
        raise HTTPException(500, str(exc)) from exc
    size, parts = live.joined(pieces)
    return StreamingResponse(
        live.read_joined(parts, pieces.adjust),
        media_type="video/iso.segment",
        headers={"Content-Length": str(size), "Cache-Control": "private, max-age=3600"},
    )


@router.get("/{play_id}/thumbs.json")
async def trickplay_manifest(
    play_id: str, session: Session = Depends(get_session)
):
    path = _load(session, play_id).path
    info = await _info(path)
    job = await trickplay.ensure(info)

    manifest = job.manifest()
    if manifest:
        manifest["url"] = f"/api/play/{play_id}/thumbs"
        return manifest
    return job.progress()


@router.get("/{play_id}/thumbs/{index}.jpg")
async def trickplay_sheet(
    play_id: str, index: int, session: Session = Depends(get_session)
):
    path = _load(session, play_id).path
    info = await _info(path)
    job = trickplay.peek(info)
    if job is None:
        raise HTTPException(404, "no thumbnails for this title")

    target = job.sheet_path(index)
    if not os.path.exists(target):
        raise HTTPException(404, "no such sheet")

    return FileResponse(
        target,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@router.get("/{play_id}/subs/{track_id}.m3u8")
async def subtitle_playlist(
    play_id: str, track_id: str, session: Session = Depends(get_session)
):
    path = _load(session, play_id).path
    info = await _info(path)
    return _no_cache(
        subtitles.vtt_playlist(f"/api/play/{play_id}", track_id, info.duration),
        "application/vnd.apple.mpegurl",
    )


@router.get("/{play_id}/subs/{track_id}.vtt")
async def subtitle_vtt(
    play_id: str, track_id: str, session: Session = Depends(get_session)
):
    path = _load(session, play_id).path

    if track_id.startswith("emb"):
        try:
            stream_index = int(track_id[3:])
        except ValueError:
            raise HTTPException(400, "bad track id") from None
        try:
            vtt_path = await subtitles.extract_embedded(path, stream_index)
        except subtitles.SubtitleError as exc:
            raise HTTPException(500, str(exc)) from exc
    elif track_id.startswith("os"):
        try:
            file_id = int(track_id[2:])
        except ValueError:
            raise HTTPException(400, "bad track id") from None
        try:
            client = subtitles.OpenSubtitlesClient()
            vtt_path = await client.fetch_vtt(file_id)
        except subtitles.SubtitleError as exc:
            raise HTTPException(502, str(exc)) from exc
    else:
        raise HTTPException(404, "unknown subtitle track")

    return FileResponse(
        vtt_path,
        media_type="text/vtt",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/{play_id}/subs/search")
async def search_subtitles(
    play_id: str,
    language: str | None = Query(None),
    session: Session = Depends(get_session),
):
    target = _load(session, play_id)
    torrent = target.download.torrent
    if torrent is None:
        raise HTTPException(404, "release metadata missing")

    languages = [language] if language else settings_languages()
    try:
        client = subtitles.OpenSubtitlesClient()
        results = await client.search(
            imdb_id=torrent.imdb_id,
            query=torrent.parsed_title,
            languages=languages,
            season=torrent.season,
            episode=torrent.episode,
        )
    except subtitles.SubtitleError as exc:
        raise HTTPException(502, str(exc)) from exc

    return [
        {
            "id": f"os{r['file_id']}",
            "label": (
                f"{subtitles.language_name(r['language'])}"
                f"{' (SDH)' if r['hearing_impaired'] else ''}"
            ),
            "language": r["language"],
            "source": "opensubtitles",
            "release": r["release"],
            "downloads": r["downloads"],
        }
        for r in results[:20]
    ]
