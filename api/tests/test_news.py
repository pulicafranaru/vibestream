"""What is new: release notes read from files, per app, and the version updated from."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream import db  # noqa: E402
from vibestream.services import news  # noqa: E402


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBESTREAM_RELEASES_DIR", str(tmp_path))
    monkeypatch.setattr(news, "VERSION", "1.2.0")
    (tmp_path / "1.0.0.md").write_text("First.\n\n- **Old.** Before.\n")
    (tmp_path / "1.1.0.md").write_text(
        "Kids and Android.\n\n- **Parental controls.** For the admin.\n\n## In the apps\n\n"
        "- **Play in the page.** Turn sideways. <!-- android -->\n- **Kids profiles** have limits.\n")
    (tmp_path / "1.2.0.md").write_text("Notes.\n\n- **Dashboard.** Says so.\n\n## In the apps\n\n- **What is new.** Once.\n")
    (tmp_path / "1.3.0.md").write_text("Not out yet.\n\n## In the apps\n\n- **Future.** No.\n")
    return tmp_path


def test_a_release_reads_as_intro_server_and_app_items(notes):
    release = news.read("1.1.0")
    assert release["intro"] == "Kids and Android."
    assert release["server"] == [{"title": "Parental controls.", "text": " For the admin.", "only": []}]
    assert [i["title"] for i in release["apps"]] == ["Play in the page.", "Kids profiles"]
    assert release["apps"][0]["only"] == ["android"]
    assert release["apps"][0]["text"] == " Turn sideways."
    assert release["apps"][1]["text"] == " have limits."


def test_since_runs_newest_first_up_to_this_version_and_filters_by_app(notes):
    assert [r["version"] for r in news.since("1.0.0")] == ["1.2.0", "1.1.0"]
    ios = {r["version"]: [i["title"] for i in r["apps"]] for r in news.since("1.0.0", "ios")}
    assert ios == {"1.2.0": ["What is new."], "1.1.0": ["Kids profiles"]}
    assert [r["version"] for r in news.since("1.2.0")] == []


def test_the_version_updated_from_is_remembered_or_worked_out_from_the_schema(notes):
    db.init_db()
    with db.session_scope() as s:
        for key in (news.RUNNING, news.UPDATED_FROM, news.SEEN):
            db.kv_set(s, key, "")
        # Nothing noted yet: the schema the database had says 1.1.0.
        news.note_start(s, fresh=False, schema_before=4)
        assert db.kv_get(s, news.UPDATED_FROM) == "1.1.0"
        assert db.kv_get(s, news.RUNNING) == "1.2.0"
        shown = news.for_dashboard(s)
        assert shown["show"] and [r["version"] for r in shown["releases"]] == ["1.2.0"]
        news.dismiss(s)
        assert news.for_dashboard(s)["show"] is False


def test_a_new_server_has_nothing_to_announce(notes):
    db.init_db()
    with db.session_scope() as s:
        for key in (news.RUNNING, news.UPDATED_FROM, news.SEEN):
            db.kv_set(s, key, "")
        news.note_start(s, fresh=True, schema_before=0)
        assert db.kv_get(s, news.UPDATED_FROM) == ""
        assert news.for_dashboard(s)["show"] is False
