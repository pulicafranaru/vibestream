from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _int(key: str, default: int) -> int:
    raw = _str(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    raw = _str(key)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = _str(key).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _int_list(key: str, default: str) -> list[int]:
    raw = _str(key) or default
    out: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return out


# Leaves out providers whose releases are mostly dubbed, and camcorder copies.
TORRENTIO_DEFAULT_URL = (
    "https://torrentio.strem.fun/providers=yts,eztv,rarbg,1337x,thepiratebay,"
    "kickasstorrents,torrentgalaxy,magnetdl|qualityfilter=scr,cam"
)


@dataclass(frozen=True)
class Settings:
    filelist_username: str = field(default_factory=lambda: _str("FILELIST_USERNAME"))
    filelist_passkey: str = field(default_factory=lambda: _str("FILELIST_PASSKEY"))
    filelist_categories: list[int] = field(
        default_factory=lambda: _int_list("FILELIST_CATEGORIES", "5,10,13")
    )
    filelist_sweep_cron: str = field(
        default_factory=lambda: _str("FILELIST_SWEEP_CRON", "17 * * * *")
    )
    filelist_min_seeders: int = field(default_factory=lambda: _int("FILELIST_MIN_SEEDERS", 1))

    # Stremio addon URLs, separated by spaces or newlines (the URLs contain commas).
    addons_enabled: bool = field(
        default_factory=lambda: _bool("ADDONS_ENABLED", _bool("TORRENTIO_ENABLED", False))
    )
    addon_urls: list[str] = field(
        default_factory=lambda: _str("ADDON_URLS").split()
        or [_str("TORRENTIO_URL") or TORRENTIO_DEFAULT_URL]
    )

    # "vibestream" names the project in outbound requests, "browser" sends a plain browser's string.
    outbound_identity: str = field(default_factory=lambda: _str("OUTBOUND_IDENTITY", "vibestream"))
    # Addon releases are fetched through TorBox; filelist ones never are.
    torbox_api_key: str = field(default_factory=lambda: _str("TORBOX_API_KEY"))

    tmdb_api_key: str = field(default_factory=lambda: _str("TMDB_API_KEY"))
    tmdb_language: str = field(default_factory=lambda: _str("TMDB_LANGUAGE", "en-US"))
    tmdb_image_base: str = field(
        default_factory=lambda: _str("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p")
    )

    qbit_url: str = field(default_factory=lambda: _str("QBIT_URL", "http://qbittorrent:8080"))
    qbit_username: str = field(default_factory=lambda: _str("QBIT_USERNAME", "admin"))
    qbit_password: str = field(default_factory=lambda: _str("QBIT_PASSWORD"))
    qbit_download_dir: str = field(
        default_factory=lambda: _str("QBIT_DOWNLOAD_DIR", "/data/downloads")
    )

    opensubtitles_api_key: str = field(
        default_factory=lambda: _str("OPENSUBTITLES_API_KEY")
    )
    subtitle_languages: list[str] = field(
        default_factory=lambda: [
            code.strip().lower()
            for code in (_str("SUBTITLE_LANGUAGES", "en").split(","))
            if code.strip()
        ]
    )
    rating_regions: list[str] = field(
        default_factory=lambda: [
            code.strip().upper()
            for code in (_str("RATING_REGIONS", "US,GB").split(","))
            if code.strip()
        ]
    )

    # In GB. Larger releases (remuxes) are kept as alternatives, never primary.
    quality_max_gb: int = field(default_factory=lambda: _int("QUALITY_MAX_GB", 30))

    movies_dir: str = field(default_factory=lambda: _str("LIBRARY_MOVIES_DIR", "/data/vibestream/library/Movies"))
    shows_dir: str = field(default_factory=lambda: _str("LIBRARY_SHOWS_DIR", "/data/vibestream/library/Shows"))

    reaper_enabled: bool = field(default_factory=lambda: _bool("REAPER_ENABLED", False))
    reaper_grace_days: int = field(default_factory=lambda: _int("REAPER_GRACE_DAYS", 7))
    reaper_min_seed_hours: int = field(default_factory=lambda: _int("REAPER_MIN_SEED_HOURS", 48))
    reaper_min_seed_ratio: float = field(
        default_factory=lambda: _float("REAPER_MIN_SEED_RATIO", 1.0)
    )
    reaper_min_free_gb: int = field(default_factory=lambda: _int("REAPER_MIN_FREE_GB", 100))
    sources_auto_remove: bool = field(
        default_factory=lambda: _bool("SOURCES_AUTO_REMOVE", True)
    )

    stream_min_buffer_ratio: float = field(
        default_factory=lambda: _float("STREAM_MIN_BUFFER_RATIO", 0.02)
    )
    stream_min_buffer_bytes: int = field(
        default_factory=lambda: _int("STREAM_MIN_BUFFER_BYTES", 32 * 1024 * 1024)
    )
    stream_wait_timeout_s: int = field(default_factory=lambda: _int("STREAM_WAIT_TIMEOUT_S", 90))

    # "renditions": HLS built after download (services/hls.py). "live": made
    # while watching (services/live.py), which never deletes the source.
    playback_engine: str = field(
        default_factory=lambda: _str("PLAYBACK_ENGINE", "renditions").lower()
    )
    live_trial: list[str] = field(
        default_factory=lambda: [p.strip() for p in _str("LIVE_TRIAL").split(",") if p.strip()]
    )

    db_path: str = field(default_factory=lambda: _str("VIBESTREAM_DB_PATH", "/app/data/vibestream.db"))
    log_level: str = field(default_factory=lambda: _str("VIBESTREAM_LOG_LEVEL", "INFO").upper())

    @property
    def filelist_configured(self) -> bool:
        return bool(self.filelist_username and self.filelist_passkey)

    @property
    def addons_configured(self) -> bool:
        return bool(self.addons_enabled and self.addon_urls)

    @property
    def torbox_configured(self) -> bool:
        return bool(self.torbox_api_key)

    @property
    def has_source(self) -> bool:
        return self.filelist_configured or self.addons_configured

    @property
    def tmdb_configured(self) -> bool:
        return bool(self.tmdb_api_key)

    @property
    def qbit_configured(self) -> bool:
        return bool(self.qbit_url and self.qbit_password)

    def missing(self) -> list[str]:
        gaps = []
        if not self.has_source:
            gaps.append("filelist")
        if not self.tmdb_configured:
            gaps.append("tmdb")
        if not self.qbit_configured:
            gaps.append("qbittorrent")
        return gaps


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
