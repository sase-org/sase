"""Tests for forced-reuse agent-name wipe semantics."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.names import (
    _wipe_execute,
    _wipe_scan,
    find_named_agent,
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    rebuild_name_registry,
    wipe_agent_names_for_reuse,
    wipe_agent_name_for_reuse,
)
from sase.agent.names._forced_reuse import (
    ForcedReuseCleanupError,
    wipe_force_reuse_owners,
)
from sase.core.process_identity import process_identity_token
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications


def _artifact(
    home: Path,
    suffix: str,
    name: str,
    *,
    project: str = "proj",
    done: bool = False,
    done_name: str | None = None,
    day_sharded: bool = False,
    meta: dict[str, object] | None = None,
) -> Path:
    workflow_dir = home / ".sase" / "projects" / project / "artifacts" / "ace-run"
    path = (
        workflow_dir / suffix[:6] / suffix[6:8] / suffix
        if day_sharded
        else workflow_dir / suffix
    )
    path.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "workflow_name": name, **(meta or {})}
    (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
    if done:
        (path / "done.json").write_text(
            json.dumps({"name": done_name or name, "outcome": "completed"}),
            encoding="utf-8",
        )
    return path


def _bundle(home: Path, suffix: str, name: str, **extra: object) -> Path:
    path = home / ".sase" / "dismissed_bundles" / "202605" / f"{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"raw_suffix": suffix, "agent_name": name, "workflow_name": name, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _notification(notification_id: str, **action_data: str) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-05-08T00:00:00-04:00",
        sender="test",
        action="JumpToAgent",
        action_data=action_data,
    )


def _start_agent_process(
    tmp_path: Path,
    *,
    mode: str,
) -> subprocess.Popen[str]:
    ready_path = tmp_path / f"{mode}.ready"
    script = """
import signal
import sys
import time
from pathlib import Path

ready_path = Path(sys.argv[1])
mode = sys.argv[2]

def handle_term(signum, frame):
    if mode == "delay":
        time.sleep(0.2)
        raise SystemExit(0)

if mode == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, handle_term)

ready_path.write_text("ready", encoding="utf-8")
while True:
    time.sleep(0.05)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ready_path), mode],
        text=True,
        preexec_fn=os.setsid,
    )
    deadline = time.monotonic() + 5.0
    while not ready_path.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"agent process exited early: {process.returncode}")
        time.sleep(0.01)  # sase-test-wait: child process writes readiness file
    if not ready_path.exists():
        raise AssertionError("agent process did not signal readiness")
    return process


def _cleanup_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def test_wipe_done_agent_clears_lookup_registry_and_notifications(
    tmp_path: Path,
) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", done=True)
    history_path = tmp_path / ".sase" / "prompt_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text('{"prompts":[{"text":"%wait:foo"}]}', encoding="utf-8")
    notifications_file = tmp_path / ".sase" / "notifications" / "notifications.jsonl"

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_file.parent)
        ),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)),
    ):
        append_notification(
            _notification("n1", raw_suffix="20260508120000", agent_name="foo")
        )
        rebuild_name_registry()

        result = wipe_agent_name_for_reuse("foo")

        assert result.found is True
        assert str(artifacts_dir) in result.artifact_dirs_removed
        assert "foo" not in get_reserved_agent_names()
        assert find_named_agent("foo") is None
        assert json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
        assert load_notifications(include_dismissed=True)[0].dismissed is True


def test_wipe_deletes_artifact_index_rows_for_removed_dirs(tmp_path: Path) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe_execute.delete_agent_artifact_index_artifacts"
        ) as mock_delete_index:
            result = wipe_agent_name_for_reuse("foo")

    assert result.artifact_dirs_removed == (str(artifacts_dir.resolve()),)
    mock_delete_index.assert_called_once()
    assert set(mock_delete_index.call_args.args[0]) == {artifacts_dir.resolve()}


def test_release_artifact_workspace_updates_index_after_running_marker_delete(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260508120000"
    )
    artifacts_dir.mkdir(parents=True)
    running_path = artifacts_dir / "running.json"
    running_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    with patch(
        "sase.agent.names._wipe_execute.update_agent_artifact_index_for_marker_mutation"
    ) as mock_update_index:
        _wipe_execute._release_artifact_workspace(artifacts_dir)

    assert not running_path.exists()
    mock_update_index.assert_called_once_with(artifacts_dir)


def test_release_artifact_workspace_ignores_index_refresh_failure(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260508120000"
    )
    artifacts_dir.mkdir(parents=True)
    running_path = artifacts_dir / "running.json"
    running_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    with patch(
        "sase.agent.names._wipe_execute.update_agent_artifact_index_for_marker_mutation",
        side_effect=RuntimeError("index unavailable"),
    ):
        _wipe_execute._release_artifact_workspace(artifacts_dir)

    assert not running_path.exists()


def test_wipe_live_agent_terminates_and_releases_workspace(
    tmp_path: Path,
) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", meta={"pid": 1234})
    kill_result = SimpleNamespace(status="killed", error=None)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch(
                "sase.agent.names._wipe_execute.is_process_alive",
                side_effect=[True, False, False],
            ),
            patch(
                "sase.agent.names._wipe_execute.request_user_kill",
                return_value=kill_result,
            ) as request_kill,
            patch(
                "sase.agent.names._wipe_execute._release_artifact_workspace"
            ) as release,
        ):
            result = wipe_agent_name_for_reuse("foo")

    request_kill.assert_called_once()
    assert request_kill.call_args.kwargs["wait"] is False
    release.assert_called_once_with(artifacts_dir)
    assert result.killed_processes == 1
    assert not artifacts_dir.exists()


def test_wipe_live_agent_keeps_artifact_when_stop_is_unverified(
    tmp_path: Path,
) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", meta={"pid": 1234})
    kill_result = SimpleNamespace(status="killed", error=None)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch("sase.agent.names._wipe_execute.is_process_alive", return_value=True),
            patch(
                "sase.agent.names._wipe_execute.request_user_kill",
                return_value=kill_result,
            ),
            patch("sase.agent.names._wipe_execute._FORCE_REUSE_STOP_GRACE_SECONDS", 0),
            patch(
                "sase.agent.names._wipe_execute._FORCE_REUSE_SIGKILL_CONFIRM_SECONDS",
                0,
            ),
            patch("sase.agent.names._wipe_execute.time.sleep", return_value=None),
            patch(
                "sase.agent.names._wipe_execute._release_artifact_workspace"
            ) as release,
        ):
            result = wipe_agent_name_for_reuse("foo")

    assert result.artifact_dirs_removed == ()
    assert result.errors
    assert "still live after stop attempt" in result.errors[0]
    assert artifacts_dir.exists()
    release.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        pytest.param("delay", "killed", id="graceful"),
        pytest.param("ignore", "force_killed", id="escalated"),
    ],
)
def test_wipe_live_agent_waits_for_real_process_exit_before_removal(
    tmp_path: Path,
    mode: str,
    expected_status: str,
) -> None:
    process = _start_agent_process(tmp_path, mode=mode)
    artifacts_dir = _artifact(
        tmp_path,
        f"20260508120000-{mode}",
        f"foo-{mode}",
        meta={
            "pid": process.pid,
            "process_identity": process_identity_token(process.pid),
        },
    )

    try:
        with patch.object(Path, "home", return_value=tmp_path):
            rebuild_name_registry()
            result = wipe_agent_name_for_reuse(f"foo-{mode}")

        process.wait(timeout=5)
    finally:
        _cleanup_process_group(process)

    assert result.errors == ()
    assert result.killed_processes == 1
    assert str(artifacts_dir.resolve()) in result.artifact_dirs_removed
    assert not artifacts_dir.exists()
    marker = artifacts_dir / ".sase_user_kill_pending"
    assert not marker.exists()
    assert process.returncode is not None
    if expected_status == "force_killed":
        assert process.returncode < 0


def test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index(
    tmp_path: Path,
) -> None:
    bundle_path = _bundle(tmp_path, "20260508120000", "foo")
    dismissed_index = tmp_path / ".sase" / "dismissed_agents.json"
    dismissed_index.write_text(
        json.dumps([["run", "foo", "20260508120000"], ["run", "bar", "bar-ts"]]),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe_execute.sync_dismissed_agent_artifact_index"
        ) as sync_index:
            result = wipe_agent_name_for_reuse("foo")

        assert str(bundle_path) in result.bundle_paths_removed
        assert result.dismissed_index_entries_removed == 1
        assert not bundle_path.exists()
        assert json.loads(dismissed_index.read_text(encoding="utf-8")) == [
            ["run", "bar", "bar-ts"]
        ]
        assert "foo" not in get_reserved_agent_names()
        sync_index.assert_called_once_with(force=True)


def test_wipe_workflow_parent_removes_children_and_followups(
    tmp_path: Path,
) -> None:
    parent = _artifact(tmp_path, "parent-ts", "foo")
    child = _artifact(
        tmp_path,
        "child-ts",
        "foo.child",
        meta={"parent_timestamp": "parent-ts"},
    )
    followup = _artifact(
        tmp_path,
        "followup-ts",
        "foo.code",
        meta={"parent_timestamp": "parent-ts", "role_suffix": ".code"},
    )
    unrelated = _artifact(tmp_path, "other-ts", "bar")

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse("foo")

        removed = set(result.artifact_dirs_removed)
        assert {str(parent), str(child), str(followup)} <= removed
        assert unrelated.exists()
        assert {"foo", "foo.child", "foo.code"}.isdisjoint(get_reserved_agent_names())
        assert "bar" in get_reserved_agent_names()


def test_wipe_retry_chain_and_bundle_descendants(tmp_path: Path) -> None:
    root = _artifact(
        tmp_path,
        "root-ts",
        "foo",
        done=True,
        meta={"retried_as_timestamp": "retry-ts"},
    )
    retry = _artifact(
        tmp_path,
        "retry-ts",
        "foo.retry",
        meta={"retry_of_timestamp": "root-ts", "retry_chain_root_timestamp": "root-ts"},
    )
    bundle_path = _bundle(
        tmp_path,
        "bundle-child-ts",
        "foo.bundle",
        parent_timestamp="retry-ts",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse("foo")

        assert {str(root), str(retry)} <= set(result.artifact_dirs_removed)
        assert str(bundle_path) in result.bundle_paths_removed
        assert {"foo", "foo.retry", "foo.bundle"}.isdisjoint(get_reserved_agent_names())


def test_wipe_agent_session_member_finds_day_sharded_handoff_and_bundle(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }
    plan = _artifact(
        tmp_path,
        "20260722120000",
        plan_name,
        done=True,
        day_sharded=True,
        meta=agent_session_meta,
    )
    code = _artifact(
        tmp_path,
        "20260722120100",
        code_name,
        day_sharded=True,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
    )
    bundle_path = _bundle(
        tmp_path,
        "20260722120200",
        f"{agent_session_name}--review",
        parent_timestamp=code.name,
        **agent_session_meta,
    )
    unrelated = _artifact(
        tmp_path,
        "20260722120300",
        "unrelated",
        day_sharded=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert {agent_session_name, plan_name, code_name} <= get_reserved_agent_names()
        with patch(
            "sase.agent.names._wipe_execute._release_artifact_workspace"
        ) as release_workspace:
            result = wipe_agent_name_for_reuse(plan_name)

        assert {str(plan), str(code)} <= set(result.artifact_dirs_removed)
        assert str(bundle_path) in result.bundle_paths_removed
        assert {call.args[0] for call in release_workspace.call_args_list} == {
            plan,
            code,
        }
        assert unrelated.exists()
        assert agent_session_name not in get_reserved_agent_names()
        assert plan_name not in get_reserved_agent_names()
        assert code_name not in get_reserved_agent_names()
        assert "unrelated" in get_reserved_agent_names()


def _agent_session_meta(agent_session_name: str, role: str) -> dict[str, object]:
    """Meta a real agent-session member stores: ``workflow_name`` is the session."""
    return {
        "workflow_name": agent_session_name,
        "agent_session": agent_session_name,
        "agent_session_role": role,
        "agent_session_parallel": False,
    }


def test_wipe_code_member_preserves_plan_member_and_agent_session_container(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    plan = _artifact(
        tmp_path,
        "20260723120000",
        plan_name,
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "root"),
            "plan_chain_root": True,
        },
    )
    code = _artifact(
        tmp_path,
        "20260723120100",
        code_name,
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "code"),
            "parent_timestamp": plan.name,
        },
    )
    descendant = _bundle(
        tmp_path,
        "20260723120200",
        f"{agent_session_name}--code-review",
        parent_timestamp=code.name,
        **_agent_session_meta(agent_session_name, "feedback"),
    )
    sibling = _artifact(
        tmp_path,
        "20260723120300",
        f"{agent_session_name}--reviewer",
        done=True,
        meta=_agent_session_meta(agent_session_name, "feedback"),
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse(code_name)

        assert set(result.artifact_dirs_removed) == {str(code)}
        assert str(descendant) in result.bundle_paths_removed
        assert plan.exists()
        assert sibling.exists()
        assert {agent_session_name, plan_name, f"{agent_session_name}--reviewer"} <= (
            get_reserved_agent_names()
        )
        assert code_name not in get_reserved_agent_names()


def _auto_agent_session(tmp_path: Path, agent_session_name: str) -> dict[str, Path]:
    """A ``%auto`` plan chain: the root's ``done.json`` names the code member."""
    root = _artifact(
        tmp_path,
        "20260725120000",
        f"{agent_session_name}--plan",
        done=True,
        done_name=f"{agent_session_name}--code",
        meta={
            **_agent_session_meta(agent_session_name, "root"),
            "plan_chain_root": True,
        },
    )
    gate = _artifact(
        tmp_path,
        "20260725120050",
        f"{agent_session_name}--gate",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "gate"),
            "parent_timestamp": root.name,
        },
    )
    code = _artifact(
        tmp_path,
        "20260725120100",
        f"{agent_session_name}--code",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "code"),
            "parent_timestamp": root.name,
        },
    )
    monitor = _artifact(
        tmp_path,
        "20260725120200",
        f"{agent_session_name}--mon",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "monitor"),
            "parent_timestamp": code.name,
        },
    )
    return {"root": root, "gate": gate, "code": code, "monitor": monitor}


def test_wipe_auto_code_member_keeps_root_whose_done_marker_names_it(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        owner = lookup_registered_name(f"{agent_session_name}--code")
        assert owner is not None
        assert Path(owner["artifacts_dir"]) == dirs["code"]

        result = wipe_agent_name_for_reuse(f"{agent_session_name}--code")

        assert result.errors == ()
        assert set(result.artifact_dirs_removed) == {
            str(dirs["code"]),
            str(dirs["monitor"]),
        }
        assert dirs["root"].exists()
        assert dirs["gate"].exists()
        assert {
            agent_session_name,
            f"{agent_session_name}--plan",
            f"{agent_session_name}--gate",
        } <= get_reserved_agent_names()
        assert f"{agent_session_name}--code" not in get_reserved_agent_names()


def test_wipe_whole_agent_session_batch_still_removes_root_and_members(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)
    members = tuple(
        f"{agent_session_name}--{suffix}" for suffix in ("plan", "gate", "code", "mon")
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        results = wipe_agent_names_for_reuse(members)

        assert all(result.errors == () for result in results)
        assert not any(path.exists() for path in dirs.values())
        assert agent_session_name not in get_reserved_agent_names()


def _leak_root_into_plan(root: Path):  # type: ignore[no-untyped-def]
    """Patch ``build_wipe_plan`` so every closure also holds *root*."""
    from sase.agent.names._wipe_plan import build_wipe_plan

    def leaky(owner, target_name, *, catalog=None):  # type: ignore[no-untyped-def]
        plan = build_wipe_plan(owner, target_name, catalog=catalog)
        plan.artifact_dirs.add(root.resolve())
        return plan

    return patch("sase.agent.names._wipe.build_wipe_plan", side_effect=leaky)


def test_wipe_refuses_member_closure_that_reaches_session_root(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)
    code_name = f"{agent_session_name}--code"

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        before = load_name_registry()
        with _leak_root_into_plan(dirs["root"]):
            result = wipe_agent_name_for_reuse(code_name)

        assert result.found is True
        assert result.artifact_dirs_removed == ()
        assert len(result.errors) == 1
        assert f"forced reuse of '{code_name}'" in result.errors[0]
        assert f"agent-session root '{agent_session_name}--plan'" in result.errors[0]
        assert str(dirs["root"]) in result.errors[0]
        assert all(path.exists() for path in dirs.values())
        assert load_name_registry() == before


def test_forced_reuse_owners_raise_and_delete_nothing_on_session_root_leak(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            _leak_root_into_plan(dirs["root"]),
            pytest.raises(ForcedReuseCleanupError, match="refusing to wipe"),
        ):
            wipe_force_reuse_owners(
                (f"{agent_session_name}--code",), allow_container_skip=False
            )

        assert all(path.exists() for path in dirs.values())


def test_batch_wipe_shares_catalog_and_registry_rebuild(tmp_path: Path) -> None:
    foo = _artifact(tmp_path, "20260724120000", "foo", done=True)
    bar = _artifact(tmp_path, "20260724120100", "bar", done=True)
    bundle_path = _bundle(
        tmp_path,
        "20260724120200",
        "foo.review",
        parent_timestamp=foo.name,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch(
                "sase.agent.names._wipe_scan._scan_artifacts",
                wraps=_wipe_scan._scan_artifacts,
            ) as scan_artifacts,
            patch(
                "sase.agent.names._wipe_scan._scan_bundles",
                wraps=_wipe_scan._scan_bundles,
            ) as scan_bundles,
            patch(
                "sase.agent.names._wipe_execute.rebuild_name_registry",
                wraps=_wipe_execute.rebuild_name_registry,
            ) as rebuild,
        ):
            results = wipe_agent_names_for_reuse(("foo", "bar"))

    assert scan_artifacts.call_count == 1
    assert scan_bundles.call_count == 1
    assert rebuild.call_count == 1
    assert {result.target_name for result in results} == {"foo", "bar"}
    assert {str(foo), str(bar)} <= {
        path for result in results for path in result.artifact_dirs_removed
    }
    assert str(bundle_path) in {
        path for result in results for path in result.bundle_paths_removed
    }
    assert not foo.exists()
    assert not bar.exists()
    assert not bundle_path.exists()


@pytest.mark.parametrize(
    ("container_kind", "container_name", "member_names", "container_meta"),
    [
        pytest.param(
            "clan",
            "research",
            ("research.worker", "research.finished"),
            {"agent_clan": "research", "agent_clan_generation": "clan-gen"},
            id="clan",
        ),
        pytest.param(
            "session",
            "review",
            ("review--0", "review--code"),
            {"agent_session": "review", "agent_session_parallel": False},
            id="session",
        ),
        # legacy agent-family spelling: pre-rename meta and bundles still
        # resolve to a session container.
        pytest.param(
            "session",
            "review",
            ("review--0", "review--code"),
            {"agent_family": "review", "agent_family_parallel": False},
            id="legacy-family-keys",
        ),
    ],
)
def test_wipe_container_name_preserves_member_artifacts_and_registry(
    tmp_path: Path,
    container_kind: str,
    container_name: str,
    member_names: tuple[str, str],
    container_meta: dict[str, object],
) -> None:
    artifacts_dir = _artifact(
        tmp_path,
        "member-ts",
        member_names[0],
        done=True,
        meta=container_meta,
    )
    bundle_path = _bundle(
        tmp_path,
        "bundle-ts",
        member_names[1],
        **container_meta,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        before = rebuild_name_registry()
        owner = lookup_registered_name(container_name)
        assert owner is not None
        assert owner["container_kind"] == container_kind

        # Exercise both accepted owner forms across the two container kinds.
        wipe_target = container_name if container_kind == "clan" else owner
        result = wipe_agent_name_for_reuse(wipe_target)

        assert result.found is True
        assert result.skipped_container_kind == container_kind
        assert result.artifact_dirs_removed == ()
        assert result.bundle_paths_removed == ()
        assert artifacts_dir.exists()
        assert bundle_path.exists()
        assert load_name_registry() == before
        assert {container_name, *member_names} <= get_reserved_agent_names()
