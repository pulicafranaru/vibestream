"""Settings changed in the admin dashboard: kept in the database, applied over .env."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select

from ..config import settings
from ..db import session_scope
from ..models import SettingOverride, utcnow

log = logging.getLogger(__name__)


class Invalid(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    kind: str  # text, secret, int, float, bool, choice, categories, languages, cron, path, urls
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    apply: Callable[[Any], None] | None = field(default=None, compare=False)


def _reschedule_sweep(cron: str) -> None:
    from apscheduler.triggers.cron import CronTrigger

    from ..scheduler import scheduler

    if scheduler.running and scheduler.get_job("sweep"):
        scheduler.reschedule_job("sweep", trigger=CronTrigger.from_crontab(cron))
        log.info("filelist sweep rescheduled: %s", cron)


def _forget_answers(_value: Any) -> None:
    from .addons import forget

    forget()


TMDB_LANGUAGES = ("en-US", "en-GB", "de-DE", "ro-RO", "fr-FR", "es-ES", "it-IT", "nl-NL",
                  "pt-PT", "pt-BR", "pl-PL", "hu-HU", "sv-SE", "da-DK", "fi-FI", "nb-NO",
                  "cs-CZ", "el-GR", "tr-TR", "ja-JP", "ko-KR", "zh-CN")

FIELDS: dict[str, Field] = {f.key: f for f in [
    Field("filelist_username", "text"),
    Field("filelist_passkey", "secret"),
    Field("filelist_categories", "categories"),
    Field("filelist_sweep_cron", "cron", apply=_reschedule_sweep),
    Field("filelist_min_seeders", "int", 0, 1000),
    Field("addons_enabled", "bool", apply=_forget_answers),
    Field("addon_urls", "urls", apply=_forget_answers),
    Field("torbox_api_key", "secret"),
    Field("outbound_identity", "choice", choices=("vibestream", "browser")),
    Field("update_check", "bool"),
    Field("parental_controls", "bool"),
    Field("tmdb_api_key", "secret"),
    Field("tmdb_language", "choice", choices=TMDB_LANGUAGES),
    Field("movies_dir", "path"),
    Field("shows_dir", "path"),
    Field("playback_engine", "choice", choices=("live", "renditions")),
    Field("quality_max_gb", "int", 2, 500),
    Field("subtitle_languages", "languages"),
    Field("opensubtitles_api_key", "secret"),
    Field("reaper_enabled", "bool"),
    Field("reaper_grace_days", "int", 0, 3650),
    Field("reaper_min_free_gb", "int", 0, 100_000),
    Field("reaper_min_seed_hours", "int", 0, 100_000),
    Field("reaper_min_seed_ratio", "float", 0, 100),
    Field("sources_auto_remove", "bool"),
]}

# What .env (or the built in default) said, before any override.
_FROM_ENV: dict[str, Any] = {key: getattr(settings, key) for key in FIELDS}


def clean(key: str, value: Any) -> Any:
    spec = FIELDS.get(key)
    if spec is None:
        raise Invalid("not a setting the dashboard can change")
    kind = spec.kind
    if kind in ("text", "secret"):
        if not isinstance(value, str):
            raise Invalid("expected text")
        value = value.strip()
        if len(value) > 200:
            raise Invalid("too long")
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise Invalid("expected a number")
        if kind == "int" and isinstance(value, float) and not value.is_integer():
            raise Invalid("expected a whole number")
        value = int(value) if kind == "int" else float(value)
        if spec.minimum is not None and value < spec.minimum:
            raise Invalid(f"at least {spec.minimum:g}")
        if spec.maximum is not None and value > spec.maximum:
            raise Invalid(f"at most {spec.maximum:g}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise Invalid("expected on or off")
        return value
    if kind == "choice":
        if value not in spec.choices:
            raise Invalid("not one of the choices")
        return value
    if kind == "categories":
        from .filelist import VIDEO_CATEGORIES

        if not isinstance(value, list) or not value:
            raise Invalid("choose at least one category")
        ids = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item not in VIDEO_CATEGORIES:
                raise Invalid(f"{item!r} is not a film or TV category")
            if item not in ids:
                ids.append(item)
        return sorted(ids)
    if kind == "languages":
        if not isinstance(value, list):
            raise Invalid("expected a list of languages")
        codes = []
        for item in value:
            code = str(item).strip().lower()
            if not re.fullmatch(r"[a-z]{2,3}", code):
                raise Invalid(f"{item!r} is not a language code like en or ro")
            if code not in codes:
                codes.append(code)
        return codes
    if kind == "cron":
        from apscheduler.triggers.cron import CronTrigger

        if not isinstance(value, str):
            raise Invalid("expected a schedule")
        value = " ".join(value.split())
        try:
            CronTrigger.from_crontab(value)
        except ValueError as exc:
            raise Invalid(f"not a schedule: {exc}") from None
        return value
    if kind == "urls":
        import httpx

        from .addons import MOST_ADDONS, base_url

        if isinstance(value, str):
            value = value.split()
        if not isinstance(value, list):
            raise Invalid("expected a list of addresses")
        known = {mask(u): u for u in [*getattr(settings, key), *_FROM_ENV.get(key, [])]}
        urls = []
        for number, item in enumerate(value, start=1):
            if not isinstance(item, str) or not item.strip():
                continue
            item = item.strip()
            if MASKED in item:
                if item not in known:
                    raise Invalid(f"Address {number} was hidden and is not one saved before. "
                                  "Paste it again.")
                url = known[item]
            else:
                url = base_url(item)
            # Never the address itself in the message: it can hold a key.
            wrong = Invalid(f"Address {number} is not an address like https://torrentio.strem.fun")
            if not re.fullmatch(r"https?://[^\s/]+(/\S*)?", url) or len(url) > 1000:
                raise wrong
            try:
                port = httpx.URL(url).port
            except (httpx.InvalidURL, ValueError):
                raise wrong from None
            if port is not None and not 0 < port < 65536:
                raise wrong
            if url not in urls:
                urls.append(url)
        if not urls:
            raise Invalid("Keep at least one address. To stop using addons, switch them off.")
        if len(urls) > MOST_ADDONS:
            raise Invalid(f"at most {MOST_ADDONS} addons")
        return urls
    if kind == "path":
        if not isinstance(value, str) or not value.startswith("/"):
            raise Invalid("expected a full path, starting with /")
        value = os.path.normpath(value.strip())
        if not os.path.isdir(value):
            raise Invalid("no such folder on the server")
        if not os.access(value, os.W_OK):
            raise Invalid("the server cannot write there")
        return value
    raise Invalid("unknown kind")


def _put(key: str, value: Any) -> None:
    object.__setattr__(settings, key, value)
    spec = FIELDS[key]
    if spec.apply:
        try:
            spec.apply(value)
        except Exception:
            log.exception("applying %s failed", key)


_RENAMED: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "torrentio_enabled": ("addons_enabled", lambda v: v),
    "torrentio_url": ("addon_urls", lambda v: [v]),
}


def load() -> None:
    """Apply saved dashboard values at startup. One that no longer validates is skipped."""
    with session_scope() as s:
        for old, (new, convert) in _RENAMED.items():
            row = s.get(SettingOverride, old)
            if row is None:
                continue
            if s.get(SettingOverride, new) is None:
                s.add(SettingOverride(key=new, value=json.dumps(convert(json.loads(row.value)))))
            s.delete(row)
        s.flush()
        rows = list(s.scalars(select(SettingOverride)))
    for row in rows:
        if row.key not in FIELDS:
            continue
        try:
            object.__setattr__(settings, row.key, clean(row.key, json.loads(row.value)))
        except (Invalid, ValueError) as exc:
            log.warning("ignoring saved %s: %s", row.key, exc)


def save(changes: dict[str, Any]) -> None:
    """Check every change first, then apply them all, or none."""
    cleaned = {}
    problems = {}
    for key, value in changes.items():
        try:
            cleaned[key] = clean(key, value)
        except Invalid as exc:
            problems[key] = str(exc)
    if problems:
        raise Invalid(json.dumps(problems))
    with session_scope() as s:
        for key, value in cleaned.items():
            row = s.get(SettingOverride, key)
            if row is None:
                s.add(SettingOverride(key=key, value=json.dumps(value)))
            else:
                row.value = json.dumps(value)
                row.updated_at = utcnow()
    for key, value in cleaned.items():
        _put(key, value)


def reset(key: str) -> None:
    if key not in FIELDS:
        raise Invalid("not a setting the dashboard can change")
    with session_scope() as s:
        row = s.get(SettingOverride, key)
        if row is not None:
            s.delete(row)
    _put(key, _FROM_ENV[key])


MASKED = "\u2026"


def mask(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    rest = url[len(f"{parts.scheme}://{parts.netloc}"):]
    if rest in ("", "/"):
        return url
    return f"{parts.scheme}://{parts.netloc}/{MASKED}{url[-4:]}"


def _shown(spec: Field, value: Any) -> Any:
    if spec.kind == "urls":
        return [mask(u) for u in value or []]
    if spec.kind != "secret":
        return value
    return {"set": bool(value), "ends": value[-4:] if value and len(value) > 8 else ""}


def describe() -> dict[str, dict]:
    with session_scope() as s:
        changed = {row.key: row.updated_at.isoformat() for row in s.scalars(select(SettingOverride))}
    out = {}
    for key, spec in FIELDS.items():
        out[key] = {
            "kind": spec.kind,
            "value": _shown(spec, getattr(settings, key)),
            "env": _shown(spec, _FROM_ENV[key]),
            "changed_at": changed.get(key),
            "min": spec.minimum,
            "max": spec.maximum,
            "choices": list(spec.choices),
        }
    return out
