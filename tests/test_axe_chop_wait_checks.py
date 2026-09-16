"""Core dependency-resolution tests for the wait_checks chop script."""

import json
from pathlib import Path
from typing import Any

import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from sase.notifications.store import load_notifications

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def test_failed_workflow_name_dependency_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="failed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_successful_workflow_name_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_shared_resolver_matches_wait_checks_workflow_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependency_resolution_status(index, ["wf"]).resolved

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_dependency_launched_after_waiter_eventually_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "late-dep")

    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()

    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "late-dep",
        done=True,
        outcome="completed",
    )
    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["late-dep"]}


def test_tribe_dependency_resolves_to_next_tribe_entity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(
        tmp_path,
        "@epic",
        suffix="20260718020000",
    )
    older = make_agent(
        tmp_path,
        "proj",
        "20260718010000",
        "old-epic",
        done=True,
        outcome="completed",
    )
    newer = make_agent(
        tmp_path,
        "proj",
        "20260718030000",
        "new-epic",
        done=True,
        outcome="completed",
    )
    for artifact in (older, newer):
        meta_path = artifact / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["tribe"] = "epic"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["@epic"]}


def test_concrete_indexed_wait_marker_resolves_without_template_marker(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "build-3")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "build-3",
        done=True,
        outcome="completed",
    )

    waiting = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["waiting_for"] == ["build-3"]
    assert all("-@" not in dep for dep in waiting["waiting_for"])

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["build-3"]}


def test_multiple_waiting_dependencies_scan_artifacts_once(
    tmp_path: Path, monkeypatch
) -> None:
    first_waiter = make_waiting_agent(tmp_path, "foo", "wf", suffix="waiter-1")
    second_waiter = make_waiting_agent(tmp_path, "foo", suffix="waiter-2")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "wf.child",
        workflow_name="wf",
        parent_timestamp="20260506010202",
        done=True,
        outcome="completed",
    )

    original_read_json_dict = wait_checks_module._read_json_dict
    agent_meta_reads = 0

    def counting_read_json_dict(path: Path) -> dict[str, Any] | None:
        nonlocal agent_meta_reads
        if path.name == "agent_meta.json":
            agent_meta_reads += 1
        return original_read_json_dict(path)

    monkeypatch.setattr(
        wait_checks_module,
        "_read_json_dict",
        counting_read_json_dict,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert (first_waiter / "ready.json").exists()
    assert (second_waiter / "ready.json").exists()
    assert agent_meta_reads == 5


def test_wait_checks_no_projects_dir_emits_noop_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_wait_checks(tmp_path, monkeypatch)

    assert capsys.readouterr().out == (
        "wait_checks: projects=0 artifacts=0 waiting=0 ready_written=0 "
        "reason=no_projects_dir\n"
    )


def test_wait_checks_unresolved_dependency_emits_noop_reason(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    make_waiting_agent(tmp_path, "missing-agent")

    run_wait_checks(tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "wait_checks: projects=1 artifacts=1 waiting=1 ready_written=0" in out
    assert "unresolved=1" in out
    assert "unknown_outcome=0" in out
    assert "reason=dependencies_not_ready" in out


def test_terminal_not_launchable_monitor_notification_names_resume_and_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SASE_HOME", raising=False)
    make_waiting_agent(tmp_path, "wf")
    blocker_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="failed",
        extra_meta={"monitor_id": "abc123def456"},
    )
    snapshot_path = blocker_dir / "diagnostics" / "worktree_recovery.diff"
    snapshot_path.parent.mkdir()
    snapshot_path.write_text(
        "diff --git a/tracked.txt b/tracked.txt\n", encoding="utf-8"
    )
    done_path = blocker_dir / "done.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done.update(
        {
            "monitor_followup_outcome": "not-launchable",
            "monitor_id": "abc123def456",
            "monitor_worktree_recovery_diff_path": str(snapshot_path),
        }
    )
    done_path.write_text(json.dumps(done), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    notes = "\n".join(notification.notes)
    assert "sase monitor resume abc123def456" in notes
    assert str(snapshot_path) in notes
    assert str(snapshot_path) in notification.files
    assert notification.action_data["monitor_resume_command"] == (
        "sase monitor resume abc123def456"
    )
    assert notification.action_data["worktree_recovery_diff_path"] == str(snapshot_path)
