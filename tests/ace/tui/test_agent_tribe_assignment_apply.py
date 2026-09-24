"""Tests for applying agent tribe changes (persist, prompts, bulk, cache)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.modals.agent_tribe_modal import (
    AgentTribeModal,
    AgentTribeModalResult,
)
from sase.ace.tui.models.agent import AgentType
from tests.ace.tui._agent_tribe_assignment_helpers import _FakeApp, _make_agent


def test_apply_set_persists_and_updates_agent(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="release-blockers"))
    assert agent.tribe == "release-blockers"
    persisted = json.loads(tribe_file.read_text())
    assert persisted == [
        {"id": ["run", "fix-bug", "20240101120000"], "tribe": "release-blockers"}
    ]
    assert app.refresh_calls == 1


def test_standalone_tribe_assignment_does_not_create_agent_tribes_directory(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    monkeypatch.chdir(tmp_path)
    agent = _make_agent()
    app = _FakeApp([agent])

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [agent],
        )

    assert agent.tribe == "release-blockers"
    assert json.loads(tribe_file.read_text()) == [
        {"id": ["run", "fix-bug", "20240101120000"], "tribe": "release-blockers"}
    ]
    assert not (tmp_path / "agent-tribes").exists()
    assert not (
        tmp_path / "agent-tribes" / ".agent_directive_persistence.lock"
    ).exists()


def test_tribe_modal_round_trip_rewrites_id_tribe_keyword(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt_path = artifacts_dir / "raw_xprompt.md"
    prompt_path.write_text("%id:worker\nDo work", encoding="utf-8")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "worker"}),
        encoding="utf-8",
    )
    agent = _make_agent(
        artifacts_dir=str(artifacts_dir),
        agent_name="worker",
    )
    app = _FakeApp([agent])

    with (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="review"),
            [agent],
        )
        assert prompt_path.read_text(encoding="utf-8") == (
            "%id(worker, tribe=review)\nDo work"
        )

        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [agent],
        )

    assert prompt_path.read_text(encoding="utf-8") == "%id:worker\nDo work"


def test_apply_set_replaces_existing_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "old"}])
    )
    agent = _make_agent()
    agent.tribe = "old"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="new"))
    assert agent.tribe == "new"
    persisted = json.loads(tribe_file.read_text())
    assert persisted == [{"id": ["run", "fix-bug", "20240101120000"], "tribe": "new"}]


def test_apply_unset_drops_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "foo"}])
    )
    agent = _make_agent()
    agent.tribe = "foo"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="unset", tribe=None))
    assert agent.tribe is None
    persisted = json.loads(tribe_file.read_text())
    assert persisted == []


def test_apply_unset_strips_legacy_meta_tag(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "20240101120000"
    artifacts_dir.mkdir(parents=True)
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps({"name": "foo.bar", "tag": "foo", "model": "test-model"}),
        encoding="utf-8",
    )
    agent = _make_agent(artifacts_dir=str(artifacts_dir), agent_name="foo.bar")
    agent.tribe = "foo"
    app = _FakeApp([agent])

    with (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [agent],
        )

    assert agent.tribe is None
    assert not tribe_file.exists()
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "name": "foo.bar",
        "model": "test-model",
    }
    assert app.refresh_calls == 1


def test_marked_bulk_path_targets_marked_agents(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        modal = app.pushed_modals[0]
        assert isinstance(modal, AgentTribeModal)
        assert modal._target_label == "2 marked agent(s)"
        assert modal._current_tribe is None  # bulk doesn't show per-agent tribe
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="release-blockers"))
    assert a1.tribe == "release-blockers"
    assert a2.tribe is None  # not marked → not changed
    assert a3.tribe == "release-blockers"
    persisted = {
        tuple(row["id"]): row["tribe"] for row in json.loads(tribe_file.read_text())
    }
    assert persisted == {
        ("run", "fix-bug", "t1"): "release-blockers",
        ("run", "fix-bug", "t3"): "release-blockers",
    }


def test_marked_bulk_success_clears_affected_marks(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    unrelated_identity = (AgentType.RUNNING, "other", "t4")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity, unrelated_identity}

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [a1, a3],
        )

    assert app._marked_agents == {unrelated_identity}


def test_successful_tribe_change_invalidates_panel_cache_before_refresh(
    tmp_path: Path,
) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [agent],
        )

    assert app._agent_panel_index_cache is None
    assert app._panel_keys_cache is None
    assert app._nav_stops_cache is None
    assert app.events == ["invalidate", "refresh:True"]


def test_modal_dismiss_with_none_is_noop(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(None)
    assert agent.tribe is None
    assert not tribe_file.exists()
    assert app.refresh_calls == 0


def test_apply_set_no_change_does_not_rewrite_file(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "already"}])
    )
    mtime_before = tribe_file.stat().st_mtime_ns
    agent = _make_agent()
    agent.tribe = "already"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="already"))
    # Tribe was already present — no write occurred.
    assert tribe_file.stat().st_mtime_ns == mtime_before
