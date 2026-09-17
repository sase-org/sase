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
    agent_armer_wire_for_artifacts,
    arm_agent_hold,
    _capture_pending_targets,
    current_armer_wire,
    find_agent_hold,
    format_pending_capture,
    _hold_scope_wire,
    _hold_selectors_wire,
    list_current_agent_holds,
    preview_pending_capture,
    rebind_agent_hold,
    release_agent_hold,
    resolve_hold_ttl_seconds,
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


def test_agent_armer_wire_for_artifacts_uses_pid_fallback_when_meta_has_no_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120002", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "worker.a--code"})
    )

    armer = agent_armer_wire_for_artifacts(str(artifacts_dir), pid_fallback=9999)

    assert armer["pid"] == 9999


def test_agent_armer_wire_for_artifacts_prefers_meta_pid_over_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120003", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 4242, "name": "worker.a--code"})
    )

    armer = agent_armer_wire_for_artifacts(str(artifacts_dir), pid_fallback=9999)

    assert armer["pid"] == 4242


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


def test_preview_pending_capture_host_scope_ignores_project() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
        SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ) as mock_entries:
        capture = preview_pending_capture("host", project="proj")

    mock_entries.assert_called_once_with(project=None)
    assert capture is not None
    assert capture.waiting_count == 1
    assert capture.queued_count == 1
    assert capture.skipped_running_count == 1


def test_preview_pending_capture_project_scope_passes_project() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=[],
    ) as mock_entries:
        preview_pending_capture("project", project="proj")

    mock_entries.assert_called_once_with(project="proj")


def test_preview_pending_capture_is_fail_soft() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        side_effect=RuntimeError("boom"),
    ):
        assert preview_pending_capture("project", project="proj") is None


def test_format_pending_capture_renders_counts() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=[
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w2"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w3"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w4"),
            SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
            SimpleNamespace(status="QUEUED", artifacts_dir="/a/q2"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r2"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r3"),
        ],
    ):
        capture = preview_pending_capture("project", project="proj")

    assert format_pending_capture(capture) == (
        "captures 4 waiting + 2 queued; skips 3 running"
    )


def test_format_pending_capture_none_returns_none() -> None:
    assert format_pending_capture(None) is None


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


def _launch_armer(
    *,
    key: str = "launch:req/u1",
    agent_name: str | None = "planner",
    **overrides: object,
) -> dict[str, object]:
    armer: dict[str, object] = {
        "kind": "launch",
        "key": key,
        "display": f"{agent_name or key} (launch req)",
        "project": "scratch",
        "agent_name": agent_name,
        "family": None,
        "clan": None,
        "pid": os.getpid(),
        "done_marker_path": "/tmp/does-not-exist/receipt.json",
    }
    armer.update(overrides)
    return armer


def test_arm_agent_hold_explicit_armer_overrides_current_armer_wire() -> None:
    armer = _launch_armer()

    result = arm_agent_hold(
        armer=armer, names=["someone-else"], scope="host", ttl_seconds=60.0
    )

    assert result.record["armer"]["kind"] == "launch"
    assert result.record["armer"]["key"] == "launch:req/u1"


def test_arm_agent_hold_explicit_selectors_ignore_name_tribe_hood_future_args() -> None:
    armer = _launch_armer()
    selectors = _hold_selectors_wire(names=["explicit-name"])

    result = arm_agent_hold(
        armer=armer,
        selectors=selectors,
        names=["ignored"],
        future=True,
        scope="host",
        ttl_seconds=60.0,
    )

    assert result.record["selectors"]["names"] == ["explicit-name"]
    assert result.record["selectors"]["future"] is False


def test_arm_agent_hold_explicit_armer_rejects_kin_selector() -> None:
    armer = _launch_armer(agent_name="planner")
    selectors = _hold_selectors_wire(names=["planner"])

    with pytest.raises(ValueError):
        arm_agent_hold(armer=armer, selectors=selectors, scope="host", ttl_seconds=60.0)


def test_arm_agent_hold_pending_merges_into_explicit_selectors_and_drops_own_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    own_dir = make_artifact(tmp_path, "20260910140000", os.getpid())
    (own_dir / "agent_meta.json").write_text(
        json.dumps({"pid": os.getpid(), "name": "planner--code"})
    )
    armer = agent_armer_wire_for_artifacts(str(own_dir))
    selectors = _hold_selectors_wire(future=True, artifact_dirs=["/pre-existing"])

    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir=str(own_dir)),
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ):
        result = arm_agent_hold(
            armer=armer,
            selectors=selectors,
            pending=True,
            scope="host",
            ttl_seconds=60.0,
        )

    artifact_dirs = result.record["selectors"]["artifact_dirs"]
    assert set(artifact_dirs) == {"/pre-existing", "/a/w1"}
    assert str(own_dir) not in artifact_dirs


def test_resolve_hold_ttl_seconds_returns_default_when_none() -> None:
    from sase.config.core import get_agent_hold_default_ttl_seconds

    assert resolve_hold_ttl_seconds(None) == get_agent_hold_default_ttl_seconds()


def test_resolve_hold_ttl_seconds_allows_up_to_the_cap() -> None:
    from sase.config.core import get_agent_hold_max_ttl_seconds

    max_seconds = get_agent_hold_max_ttl_seconds()
    assert resolve_hold_ttl_seconds(max_seconds) == max_seconds


def test_resolve_hold_ttl_seconds_raises_over_cap() -> None:
    from sase.config.core import get_agent_hold_max_ttl_seconds

    max_seconds = get_agent_hold_max_ttl_seconds()
    with pytest.raises(ValueError, match="exceeds the configured maximum"):
        resolve_hold_ttl_seconds(max_seconds + 1)


def test_rebind_agent_hold_round_trips_and_keeps_created_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    result = arm_agent_hold(names=["a.b--code"], scope="host", ttl_seconds=60.0)
    old_key = result.record["armer"]["key"]
    created_at = result.record["created_at"]

    new_armer = dict(result.record["armer"])
    new_armer["pid"] = os.getpid()
    rebound = rebind_agent_hold(old_key, new_armer)

    assert rebound is not None
    assert rebound["created_at"] == created_at
    assert rebound["armer"]["pid"] == os.getpid()
    assert list_current_agent_holds()[0]["armer"]["key"] == old_key


def test_rebind_agent_hold_returns_none_for_missing_key() -> None:
    assert rebind_agent_hold("agent:does-not-exist", _launch_armer()) is None


def test_arm_agent_hold_accepts_launch_kind_record(tmp_path: Path) -> None:
    armer = _launch_armer(done_marker_path=str(tmp_path / "receipt.json"))

    result = arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)

    assert result.record["armer"]["kind"] == "launch"
    holds = list_current_agent_holds()
    assert len(holds) == 1
    assert holds[0]["armer"]["kind"] == "launch"


def test_launch_hold_liveness_survives_while_pid_alive_and_receipt_incomplete(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"complete": False}))
    armer = _launch_armer(pid=os.getpid(), done_marker_path=str(receipt))

    arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)

    assert len(active_agent_hold_records()) == 1


def test_launch_hold_liveness_prunes_once_receipt_completes(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"complete": False}))
    armer = _launch_armer(pid=os.getpid(), done_marker_path=str(receipt))

    arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)
    assert len(active_agent_hold_records()) == 1

    receipt.write_text(json.dumps({"complete": True}))
    assert active_agent_hold_records() == []


def test_launch_hold_liveness_falls_back_to_started_json_pid(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"complete": False}))
    (tmp_path / "started.json").write_text(json.dumps({"pid": os.getpid()}))
    dead_pid = 999_999_999
    armer = _launch_armer(pid=dead_pid, done_marker_path=str(receipt))

    arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)

    assert len(active_agent_hold_records()) == 1


def test_launch_hold_liveness_prunes_when_pid_and_started_json_both_dead(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"complete": False}))
    dead_pid = 999_999_999
    (tmp_path / "started.json").write_text(json.dumps({"pid": dead_pid}))
    armer = _launch_armer(pid=dead_pid, done_marker_path=str(receipt))

    arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)

    assert active_agent_hold_records() == []


def test_launch_hold_liveness_prunes_once_done_json_present(tmp_path: Path) -> None:
    done_marker = tmp_path / "done.json"
    armer = _launch_armer(pid=os.getpid(), done_marker_path=str(done_marker))

    arm_agent_hold(armer=armer, future=True, scope="host", ttl_seconds=60.0)
    assert len(active_agent_hold_records()) == 1

    done_marker.write_text("{}")
    assert active_agent_hold_records() == []
