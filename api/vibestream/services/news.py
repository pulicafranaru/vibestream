"""What is new: the release notes in docs/releases, and the version run before.

Items under "## In the apps" are for the people watching; <!-- android --> limits one to that app.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from .. import VERSION
from ..db import kv_get, kv_set
from .updates import parse

log = logging.getLogger(__name__)

RUNNING = "version.running"
UPDATED_FROM = "version.updated_from"
SEEN = "version.news_seen"

# The release each database schema shipped in, for a server that never noted its version.
SCHEMA_RELEASE = {3: "1.0.0", 4: "1.1.0"}

_ITEM = re.compile(r"^-\s+(?:\*\*(?P<title>.+?)\*\*\s*)?(?P<text>.*?)\s*(?:<!--(?P<only>[^>]*)-->)?\s*$")


def releases_dir() -> Path:
    found = os.environ.get("VIBESTREAM_RELEASES_DIR")
    return Path(found) if found else Path(__file__).resolve().parents[3] / "docs" / "releases"


def read(version: str) -> dict | None:
    """One release's notes as {version, intro, server, apps}, or None without a file."""
    path = releases_dir() / f"{version}.md"
    if not path.is_file():
        return None
    intro, server, apps = [], [], []
    items = server
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            items = apps if "app" in line.lower() else server
            continue
        found = _ITEM.match(line)
        if line.startswith("- ") and found:
            only = [p.strip().lower() for p in (found["only"] or "").split(",") if p.strip()]
            # The bold words, then the rest of their sentence.
            title, text = (found["title"] or "").strip(), found["text"].strip()
            if title and text and text[0] not in ",.;:":
                text = " " + text
            items.append({"title": title, "text": text, "only": only})
        elif not server and not apps:
            intro.append(line)
    return {"version": version, "intro": " ".join(intro), "server": server, "apps": apps}


def since(version: str | None, app: str | None = None) -> list[dict]:
    """Every release after `version` up to this one, newest first. For an
    app, only the items for it."""
    floor = parse(version or "") or (0, 0, 0)
    top = parse(VERSION) or (0, 0, 0)
    found = []
    for path in releases_dir().glob("*.md"):
        number = parse(path.stem)
        if not number or not floor < number <= top:
            continue
        notes = read(path.stem)
        if notes is None:
            continue
        if app:
            notes["apps"] = [i for i in notes["apps"] if not i["only"] or app in i["only"]]
        found.append((number, notes))
    return [notes for _, notes in sorted(found, key=lambda pair: pair[0], reverse=True)]


def note_start(s: Session, fresh: bool, schema_before: int) -> None:
    """At start: the version this server ran before, when it was not this one."""
    before = kv_get(s, RUNNING) or None
    if before is None and not fresh:
        before = SCHEMA_RELEASE.get(schema_before)
    if before and before != VERSION:
        kv_set(s, UPDATED_FROM, before)
        log.info("updated from %s to %s", before, VERSION)
    kv_set(s, RUNNING, VERSION)


def for_dashboard(s: Session) -> dict:
    updated_from = kv_get(s, UPDATED_FROM) or None
    shown = bool(updated_from) and kv_get(s, SEEN) != VERSION
    return {"version": VERSION, "updated_from": updated_from, "show": shown,
            "releases": since(updated_from) if shown else []}


def dismiss(s: Session) -> None:
    kv_set(s, SEEN, VERSION)
