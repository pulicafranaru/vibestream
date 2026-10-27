"""Turning a spoken search into a search term: filler words off, then snapped to
a close title when there is one.
"""

from __future__ import annotations

import re
import time
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Media, Torrent

# How close a reading must be to a title, spaces ignored, to be taken as it.
SNAP = 0.84
SURE = 0.93
POOL_SECONDS = 600

_LEAD = re.compile(
    r"^(?:(?:hey|ok|okay|um|uh|so)\s+)*"
    r"(?:(?:can|could|would)\s+you\s+|please\s+)?"
    r"(?:search(?:\s+for)?|find(?:\s+me)?|look\s+(?:for|up)|show\s+me|play|watch|put\s+on|start|"
    r"i\s+(?:want|wanna|would\s+like)\s+(?:to\s+)?(?:watch|see)|let'?s\s+watch)(?:\s+|$)"
)
_KIND = re.compile(r"^(?:the\s+)?(?:movie|film|show|series|tv\s+show|documentary)\s+(?:called\s+)?")
_TAIL = re.compile(
    r"\s+(?:please|"
    r"(?:the\s+)?(?:movies?|films?|shows?|series|tv\s+shows?)|"
    r"season\s+\w+(?:\s+episode\s+\w+)?|episode\s+\w+)$"
)

_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
_DIGITS = {v: k for k, v in _NUMBERS.items()}

_pool: list[tuple[str, str, str]] = []  # (title, words, compact)
_pool_at = 0.0


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def clean(reading: str) -> str:
    text = normalise(reading)
    while True:
        before = text
        text = _LEAD.sub("", text)
        text = _KIND.sub("", text)
        text = _TAIL.sub("", text)
        if text == before:
            return text


def _variants(text: str) -> list[str]:
    words = text.split()
    out = [text]
    for table in (_NUMBERS, _DIGITS):
        swapped = " ".join(table.get(w, w) for w in words)
        if swapped not in out:
            out.append(swapped)
    return out


def _load_pool(session: Session) -> list[tuple[str, str, str]]:
    global _pool, _pool_at
    if _pool and time.monotonic() - _pool_at < POOL_SECONDS:
        return _pool
    titles: set[str] = set()
    for title, original in session.execute(
        select(Media.title, Media.original_title).join(Torrent, Torrent.media_id == Media.id).distinct()
    ):
        titles.update(t for t in (title, original) if t)
    for (parsed,) in session.execute(
        select(Torrent.parsed_title).where(Torrent.media_id.is_(None), Torrent.parsed_title.is_not(None)).distinct()
    ):
        titles.add(parsed)
    pool = []
    for title in titles:
        words = normalise(title)
        if words:
            pool.append((title, words, words.replace(" ", "")))
    _pool, _pool_at = pool, time.monotonic()
    return pool


def forget_pool() -> None:
    global _pool, _pool_at
    _pool, _pool_at = [], 0.0


def _contained(text: str, pool) -> bool:
    padded = f" {text} "
    return any(padded in f" {words} " for _title, words, _compact in pool)


def _closest(text: str, pool) -> tuple[float, str | None]:
    compact = text.replace(" ", "")
    best, found = 0.0, None
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(compact)
    for title, _words, candidate in pool:
        if abs(len(candidate) - len(compact)) > max(3, len(compact) // 3):
            continue
        matcher.set_seq1(candidate)
        if matcher.real_quick_ratio() < best or matcher.quick_ratio() < best:
            continue
        score = matcher.ratio()
        if score > best:
            best, found = score, title
    return best, found


def meant(session: Session, readings: list[str]) -> dict:
    cleaned: list[str] = []
    for reading in readings[:6]:
        text = clean(reading)
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return {"term": "", "title": None}
    pool = _load_pool(session)

    best, title = 0.0, None
    for text in cleaned:
        for variant in _variants(text):
            score, found = _closest(variant, pool)
            if score > best:
                best, title = score, found
    if title and best >= SURE:
        return {"term": title, "title": title}

    for text in cleaned:
        for variant in _variants(text):
            if _contained(variant, pool):
                return {"term": variant, "title": None}

    if title and best >= SNAP:
        return {"term": title, "title": title}
    return {"term": cleaned[0], "title": None}
