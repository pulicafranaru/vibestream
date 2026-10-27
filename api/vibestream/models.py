from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; values come back as aware UTC so comparisons do not raise."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class MediaType(str, enum.Enum):
    movie = "movie"
    tv = "tv"


class EnrichStatus(str, enum.Enum):
    pending = "pending"
    ok = "ok"
    notfound = "notfound"
    error = "error"


class DownloadState(str, enum.Enum):
    requested = "requested"
    adding = "adding"
    downloading = "downloading"
    paused = "paused"
    completed = "completed"
    seeding = "seeding"
    linked = "linked"
    error = "error"
    removed = "removed"


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint("tmdb_id", "media_type", name="uq_media_tmdb"),
        Index("ix_media_imdb", "imdb_id"),
        Index("ix_media_sort", "media_type", "release_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_type: Mapped[str] = mapped_column(String(8), default=MediaType.movie.value)

    title: Mapped[str] = mapped_column(String(512), default="")
    original_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagline: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)  # json array of names
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    popularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Shows only: share of aired episodes the tracker has, 0 to 1.
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    # TMDB details as JSON. NULL means not fetched yet, which the backfill looks for.
    facts: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrich_status: Mapped[str] = mapped_column(
        String(16), default=EnrichStatus.pending.value, index=True
    )
    enrich_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    torrents: Mapped[list["Torrent"]] = relationship(back_populates="media")


class Torrent(Base):
    __tablename__ = "torrents"
    __table_args__ = (
        Index("ix_torrents_upload_date", "upload_date"),
        Index("ix_torrents_media", "media_id"),
        Index("ix_torrents_parsed", "parsed_title", "parsed_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    imdb_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    seeders: Mapped[int] = mapped_column(Integer, default=0)
    leechers: Mapped[int] = mapped_column(Integer, default=0)
    times_completed: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=1)

    freeleech: Mapped[bool] = mapped_column(Boolean, default=False)
    doubleup: Mapped[bool] = mapped_column(Boolean, default=False)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    moderated: Mapped[bool] = mapped_column(Boolean, default=False)

    upload_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    small_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    parsed_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parsed_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hdr: Mapped[str | None] = mapped_column(String(32), nullable=True)
    release_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    media: Mapped["Media | None"] = relationship(back_populates="torrents")

    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # The tracker API never reports deletions: set when the .torrent is gone.
    gone_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    origin: Mapped[str] = mapped_column(String(16), default="filelist")
    info_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    announce: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    linkable: Mapped[bool] = mapped_column(Boolean, default=False)
    held: Mapped[bool] = mapped_column(Boolean, default=False)

    download: Mapped["Download | None"] = relationship(
        back_populates="torrent", uselist=False
    )


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("media_id", "number", name="uq_season_media_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    episode_count: Mapped[int] = mapped_column(Integer, default=0)

    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    media: Mapped["Media"] = relationship()
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="season_row", cascade="all, delete-orphan"
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("media_id", "season_number", "number", name="uq_episode_slot"),
        Index("ix_episode_download", "download_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    season_number: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)

    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    air_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    still_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    facts: Mapped[str | None] = mapped_column(Text, nullable=True)

    download_id: Mapped[int | None] = mapped_column(
        ForeignKey("downloads.id"), nullable=True
    )
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    prepared_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    prepare_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # file_path still names the removed source: renditions are keyed by it.
    source_removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    season_row: Mapped["Season"] = relationship(back_populates="episodes")
    media: Mapped["Media"] = relationship()
    download: Mapped["Download | None"] = relationship()


class Download(Base):
    __tablename__ = "downloads"
    __table_args__ = (
        UniqueConstraint("torrent_id", name="uq_download_torrent"),
        Index("ix_downloads_state", "state"),
        Index("ix_downloads_hash", "info_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    torrent_id: Mapped[int] = mapped_column(ForeignKey("torrents.id"))
    torrent: Mapped["Torrent"] = relationship(back_populates="download")

    info_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default=DownloadState.requested.value)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    dl_speed: Mapped[int] = mapped_column(Integer, default=0)
    up_speed: Mapped[int] = mapped_column(Integer, default=0)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    ratio: Mapped[float] = mapped_column(Float, default=0.0)
    seeding_seconds: Mapped[int] = mapped_column(Integer, default=0)

    save_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    primary_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    primary_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_file_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    library_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    prepared_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    prepare_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON list of paths relative to the torrent root. NULL means all files.
    wanted_files: Mapped[str | None] = mapped_column(Text, nullable=True)
    # linked_at older than this means a newly wanted file still needs publishing.
    wanted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    added_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    resume_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    resume_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    source_removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    play_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    reap_after: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reaped_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    keep: Mapped[bool] = mapped_column(Boolean, default=False)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (Index("ix_download_jobs_download", "download_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    download_id: Mapped[int] = mapped_column(ForeignKey("downloads.id"))
    download: Mapped["Download"] = relationship()
    kind: Mapped[str] = mapped_column(String(16))
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"), nullable=True)
    episode: Mapped["Episode | None"] = relationship()
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    avatar: Mapped[str] = mapped_column(String(32), default="crimson-smile")
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # "salt$pbkdf2 hash". NULL means no PIN.
    pin_hash: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    progress: Mapped[list["WatchProgress"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    my_list: Mapped[list["MyListItem"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    continue_hidden: Mapped[list["ContinueHidden"]] = relationship(
        cascade="all, delete-orphan"
    )


class EpisodeProgress(Base):
    __tablename__ = "episode_progress"
    __table_args__ = (
        UniqueConstraint("profile_id", "episode_id", name="uq_ep_progress"),
        Index("ix_ep_progress_recent", "profile_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))

    resume_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    profile: Mapped["Profile"] = relationship()
    episode: Mapped["Episode"] = relationship()


class WatchProgress(Base):
    __tablename__ = "watch_progress"
    __table_args__ = (
        UniqueConstraint("profile_id", "download_id", name="uq_progress_profile_dl"),
        Index("ix_progress_recent", "profile_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    download_id: Mapped[int] = mapped_column(ForeignKey("downloads.id"))

    resume_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    profile: Mapped["Profile"] = relationship(back_populates="progress")
    download: Mapped["Download"] = relationship()


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("profile_id", "media_id", name="uq_rating_profile_media"),
        Index("ix_ratings_media", "media_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"))
    # -1 not for me, 1 like it
    value: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    profile: Mapped["Profile"] = relationship(back_populates="ratings")
    media: Mapped["Media"] = relationship()


class MyListItem(Base):
    __tablename__ = "my_list"
    __table_args__ = (
        UniqueConstraint("profile_id", "media_id", name="uq_my_list_profile_media"),
        Index("ix_my_list_recent", "profile_id", "added_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    profile: Mapped["Profile"] = relationship(back_populates="my_list")
    media: Mapped["Media"] = relationship()


class ContinueHidden(Base):
    __tablename__ = "continue_hidden"
    __table_args__ = (
        UniqueConstraint("profile_id", "media_id", name="uq_continue_hidden"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"))
    hidden_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (Index("ix_clips_recent", "profile_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    play_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512), default="")
    subtitle: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    end_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    media: Mapped["Media | None"] = relationship()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String(8), default="info")
    source: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class KV(Base):
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeviceName(Base):
    __tablename__ = "device_names"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), default="")
    # NULL means shared.
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="")
    own_name: Mapped[str] = mapped_column(String(60), default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeviceToken(Base):
    """Only the token's SHA-256 is stored."""

    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AdminAccount(Base):
    """Only the scrypt hash of the password is stored."""

    __tablename__ = "admin_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AdminSession(Base):
    """Only the token's SHA-256 is stored, so a database copy signs nobody in."""

    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class SettingOverride(Base):
    __tablename__ = "setting_overrides"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


def _server_defaults() -> None:
    """Mirrors constant Python defaults in SQL, so rows inserted by plain SQL satisfy NOT NULL."""
    from sqlalchemy import DefaultClause, text

    for table in Base.metadata.tables.values():
        for column in table.columns:
            default = column.default
            if column.server_default is not None or default is None or not default.is_scalar:
                continue
            value = default.arg
            if isinstance(value, enum.Enum):
                value = value.value
            if isinstance(value, bool):
                literal = "1" if value else "0"
            elif isinstance(value, (int, float)):
                literal = repr(value)
            elif isinstance(value, str):
                literal = "'" + value.replace("'", "''") + "'"
            else:
                continue
            DefaultClause(text(literal))._set_parent_with_dispatch(column)


_server_defaults()
