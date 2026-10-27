"""What this server sends to a third party names the project at most: never who runs it."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream import user_agent  # noqa: E402
from vibestream.config import settings  # noqa: E402

PACKAGE = Path(__file__).resolve().parents[1] / "vibestream"

REPO = Path(__file__).resolve().parents[2]


def _private_words() -> list[str]:
    """Private names from PRIVACY_WORDS (comma separated), in the environment or .env."""
    raw = os.environ.get("PRIVACY_WORDS", "")
    env = REPO / ".env"
    if not raw and env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("PRIVACY_WORDS="):
                raw = line.split("=", 1)[1].strip().strip('"')
    return [re.escape(w.strip()) for w in raw.split(",") if w.strip()]


# Identifying a person or a purpose: an address, a runtime, a purpose, a private name.
# The browser string may not name the project either.
PERSONAL = re.compile(
    "|".join([r"@", r"python|httpx|curl|node", r"research|scraper|bot\b|contact",
              *_private_words()]),
    re.I,
)
FORBIDDEN = re.compile(PERSONAL.pattern + r"|vibestream|\+http", re.I)

# qBittorrent is on the LAN; everything else is somebody else's server.
LOCAL_CLIENTS = {"qbit.py", "user_agent.py"}


def test_the_browser_agent_is_a_plain_browser_string():
    agent = user_agent.BROWSER_AGENT
    assert agent.startswith("Mozilla/5.0 (")
    assert not FORBIDDEN.search(agent), agent


def test_the_project_agent_names_the_project_and_nothing_else():
    agent = user_agent.PROJECT_AGENT
    assert re.fullmatch(r"VibeStream/\d+\.\d+\.\d+", agent), agent
    assert not PERSONAL.search(agent), agent


def test_the_dashboard_choice_decides_what_is_sent(monkeypatch):
    monkeypatch.delenv("OUTBOUND_USER_AGENT", raising=False)
    saved = settings.outbound_identity
    try:
        object.__setattr__(settings, "outbound_identity", "vibestream")
        assert user_agent.outbound_client().headers["User-Agent"] == user_agent.PROJECT_AGENT
        object.__setattr__(settings, "outbound_identity", "browser")
        assert user_agent.outbound_client().headers["User-Agent"] == user_agent.BROWSER_AGENT
        monkeypatch.setenv("OUTBOUND_USER_AGENT", "Custom/1.0")
        assert user_agent.outbound_client().headers["User-Agent"] == "Custom/1.0"
    finally:
        object.__setattr__(settings, "outbound_identity", saved)


def test_every_third_party_client_is_built_by_the_policy_module():
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path.name not in LOCAL_CLIENTS
        and re.search(r"httpx\.(Async)?Client\(|httpx\.(get|post|request)\(|"
                      r"urllib\.request|aiohttp|requests\.(get|post)", path.read_text())
    ]
    assert offenders == []


def test_no_source_file_hardcodes_an_identifying_agent():
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            if re.search(r"user.agent", line, re.I) and PERSONAL.search(line.split("#")[0]):
                raise AssertionError(f"{path.name}: {line.strip()}")


def test_outbound_clients_send_it():
    client = user_agent.outbound_client(headers={"User-Agent": "Planted/1.0"})
    assert client.headers["User-Agent"] == user_agent.current()


def test_a_third_partys_address_is_logged_by_its_host_alone(caplog):
    import logging

    import httpx

    with caplog.at_level(logging.INFO, logger="httpx"):
        log = logging.getLogger("httpx")
        log.info('HTTP Request: %s %s "%s %d %s"', "GET",
                 httpx.URL("https://torrentio.strem.fun/realdebrid=SECRETKEY/stream/movie/tt1.json"),
                 "HTTP/1.1", 200, "OK")
        log.info('HTTP Request: %s %s "%s %d %s"', "GET",
                 httpx.URL("http://qbittorrent:8081/api/v2/torrents/info?hashes=abc"),
                 "HTTP/1.1", 200, "OK")
    text = caplog.text
    assert "SECRETKEY" not in text and "https://torrentio.strem.fun/..." in text
    assert "hashes=abc" in text
