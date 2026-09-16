"""Tests for the CLI/directive-facing agent-hold service in agent_hold_facade."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.agent_hold_facade import (
    _AgentHoldServiceError,
    active_agent_hold_records,
    arm_agent_hold,
    _capture_pending_targets,
    current_armer_wire,
    find_agent_hold,
    _hold_scope_wire,
    _hold_selectors_wire,
    list_current_agent_holds,
    release_agent_hold,
)
from sase.notifications.store import load_notifications

from tests._runner_slot_fixtures import artifact as make_artifact


def test_hold_scope_wire_project_and_host() -> None:
    assert _hold_scope_wire("project", project="proj") == {
        "kind": "project",
        "project": "proj",
    }
    assert _hold_scope_wire("host", project="proj") == {"kind": "host"}


def test_hold_selectors_wire_normalizes_tribes_and_defaults() -> None:
    selectors = _hold_selectors_wire(
        names=["a.b--code"],
        tribes=["@ops", "infra"],
        hoods=["fi"],
        future=True,
        artifact_dirs=["/a/w1"],
    )
    assert selectors == {
        "artifact_dirs": ["/a/w1"],
        "names": ["a.b--code"],
        "hoods": ["fi"],
        "tribes": ["ops", "infra"],
        "future": True,
    }


def test_hold_selectors_wire_defaults_are_empty() -> None:
    assert _hold_selectors_wire() == {
        "artifact_dirs": [],
        "names": [],
        "hoods": [],
        "tribes": [],
        "future": False,
    }


def test_current_armer_wire_uses_agent_metadata_when_artifacts_dir_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120000", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 4242,
                "name": "worker.a--code",
                "agent_family": "worker.a",
                "agent_clan": "builders",
            }
        )
    )

    armer = current_armer_wire(env={"SASE_ARTIFACTS_DIR": str(artifacts_dir)})

    assert armer["kind"] == "agent"
    assert armer["key"] == "agent:worker.a--code"
    assert armer["display"] == "worker.a--code"
    assert armer["project"] == "proj"
    assert armer["agent_name"] == "worker.a--code"
    assert armer["family"] == "worker.a"
    assert armer["clan"] == "builders"
    assert armer["pid"] == 4242
    assert armer["done_marker_path"] == str(artifacts_dir / "done.json")


def test_current_armer_wire_raises_when_agent_meta_has_no_name(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_artifact(tmp_path, "20260910120001", 4242)
    (artifacts_dir / "agent_meta.json").write_text(json.dumps({"pid": 4242}))

    with pytest.raises(_AgentHoldServiceError):
        current_armer_wire(env={"SASE_ARTIFACTS_DIR": str(artifacts_dir)})


def test_current_armer_wire_falls_back_to_cli_kind_without_artifacts_dir() -> None:
    with patch("sase.core.agent_hold_facade._project_for_cwd", return_value="scratch"):
        armer = current_armer_wire(env={}, pid_override=4321)

    assert armer["kind"] == "cli"
    assert armer["pid"] == 4321
    assert armer["key"].endswith(":4321")
    assert armer["project"] == "scratch"


def test_current_armer_wire_cli_kind_defaults_pid_to_parent_process() -> None:
    with patch("sase.core.agent_hold_facade._project_for_cwd", return_value="scratch"):
        armer = current_armer_wire(env={})

    assert armer["pid"] == os.getppid()


def test_project_for_cwd_raises_when_unresolvable() -> None:
    with patch("sase.bead.project_name.infer_project_name_from_cwd", return_value=None):
        with pytest.raises(_AgentHoldServiceError):
            current_armer_wire(env={})


def test_capture_pending_targets_buckets_waiting_queued_and_running() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w2"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
        SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
        SimpleNamespace(status="STARTING", artifacts_dir="/a/s1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ) as mock_entries:
        capture = _capture_pending_targets(project="proj")

    mock_entries.assert_called_once_with(project="proj")
    assert capture.waiting_count == 2
    assert capture.queued_count == 1
    assert capture.skipped_running_count == 2
    assert set(capture.artifact_dirs) == {"/a/w1", "/a/w2", "/a/q1"}


def test_arm_agent_hold_requires_at_least_one_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    with pytest.raises(ValueError):
        arm_agent_hold(ttl_seconds=60.0)


def test_arm_agent_hold_arms_lists_shows_and_upserts_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )

    result = arm_agent_hold(names=["a.b--code"], scope="host", ttl_seconds=60.0)

    armer_key = result.record["armer"]["key"]
    assert result.record["selectors"]["names"] == ["a.b--code"]
    assert result.capture is None

    holds = list_current_agent_holds()
    assert [h["armer"]["key"] for h in holds] == [armer_key]

    found = find_agent_hold(armer_key)
    assert found is not None
    assert find_agent_hold("does-not-exist") is None

    notifications = load_notifications()
    armed = [n for n in notifications if n.dedup_key == f"agent_hold:armed:{armer_key}"]
    assert len(armed) == 1
    assert armed[0].sender == "agent_hold"


def test_arm_agent_hold_with_pending_captures_and_summarizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
        SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ):
        result = arm_agent_hold(pending=True, scope="host", ttl_seconds=60.0)

    assert result.capture is not None
    assert set(result.record["selectors"]["artifact_dirs"]) == {"/a/w1", "/a/q1"}

    armer_key = result.record["armer"]["key"]
    notifications = load_notifications()
    armed = next(
        n for n in notifications if n.dedup_key == f"agent_hold:armed:{armer_key}"
    )
    assert "Captured 2 pending (1 waiting, 1 queued); skipped 1 running" in armed.notes


def test_release_agent_hold_removes_and_upserts_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    result = arm_agent_hold(future=True, scope="host", ttl_seconds=60.0)
    armer_key = result.record["armer"]["key"]

    assert release_agent_hold(armer_key) is True
    assert list_current_agent_holds() == []

    notifications = load_notifications()
    released = [
        n for n in notifications if n.dedup_key == f"agent_hold:released:{armer_key}"
    ]
    assert len(released) == 1
    assert released[0].notes[-1] == "Released explicitly"


def test_release_agent_hold_returns_false_for_unknown_key() -> None:
    assert release_agent_hold("agent:does-not-exist") is False
    assert load_notifications() == []


def test_active_agent_hold_records_notifies_on_liveness_drop(
    tmp_path: Path,
) -> None:
    dead_pid = 999_999_999
    armer_dir = make_artifact(tmp_path, "20260910130000", dead_pid)
    (armer_dir / "agent_meta.json").write_text(
        json.dumps({"pid": dead_pid, "name": "ghost--code"})
    )

    with patch.dict(
        "os.environ",
        {
            "SASE_HOME": str(tmp_path / ".sase"),
            "SASE_ARTIFACTS_DIR": str(armer_dir),
        },
        clear=False,
    ):
        result = arm_agent_hold(future=True, scope="host", ttl_seconds=60.0)
        armer_key = result.record["armer"]["key"]

        holds = active_agent_hold_records()
        assert holds == []

        notifications = load_notifications()

    released = [
        n for n in notifications if n.dedup_key == f"agent_hold:released:{armer_key}"
    ]
    assert len(released) == 1
    assert "no longer alive" in released[0].notes[-1]
