"""The dashboard's update notice: a newer release, asked of GitHub only when allowed."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream.config import settings  # noqa: E402
from vibestream.services import updates  # noqa: E402


@pytest.fixture
def github(monkeypatch):
    asked = []
    answer = {"status": 200, "tag": "v1.0.0"}

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if answer["status"] != 200:
            return httpx.Response(answer["status"], json={})
        return httpx.Response(200, json={"tag_name": answer["tag"], "html_url": "https://example.test/r",
                                         "published_at": "2026-10-27T00:00:00Z"})

    monkeypatch.setattr(updates, "outbound_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(updates, "VERSION", "1.0.0")
    updates._cache.update(at=0.0, ttl=0.0, release=None)
    saved = settings.update_check
    yield asked, answer
    object.__setattr__(settings, "update_check", saved)
    updates._cache.update(at=0.0, ttl=0.0, release=None)


def test_a_newer_release_is_offered(github):
    _, answer = github
    answer["tag"] = "v1.2.0"
    status = asyncio.run(updates.status())
    assert status["available"] and status["latest"]["version"] == "1.2.0"
    assert status["command"].endswith("| sudo bash")


def test_the_same_or_an_older_release_is_not(github):
    _, answer = github
    for tag in ("v1.0.0", "v0.9.9"):
        updates._cache.update(at=0.0, ttl=0.0)
        answer["tag"] = tag
        assert not asyncio.run(updates.status())["available"]


def test_github_is_asked_once_in_a_while_not_on_every_visit(github):
    asked, _ = github
    for _ in range(5):
        asyncio.run(updates.status())
    assert len(asked) == 1


def test_switched_off_github_is_never_asked(github):
    asked, _ = github
    object.__setattr__(settings, "update_check", False)
    status = asyncio.run(updates.status())
    assert asked == [] and not status["available"] and status["latest"] is None


def test_github_failing_means_no_notice(github):
    _, answer = github
    answer["status"] = 500
    assert not asyncio.run(updates.status())["available"]


def test_versions_compare_as_numbers():
    assert updates.parse("v1.10.0") > updates.parse("1.9.3")
    assert updates.parse("1.0.0+edge.abc") is None
