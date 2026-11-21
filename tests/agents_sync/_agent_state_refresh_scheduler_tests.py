from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import StateRepairReport
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._agent_state_refresh_test_support import (
    inventory_run,
    owner_identity,
    repair_with,
    setup_refresh_repo,
    targets_for,
)


def _stored_cursor(state_dir: Path, key: str) -> object:
    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    return payload["projects"][key]["cursor"]


def test_corrupt_and_unsupported_state_reset_safely(tmp_path: Path) -> None:
    _remote, sync_target = setup_refresh_repo(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    state_dir = tmp_path / "state"
    (state_dir / "agent_state_refresh.json").parent.mkdir(parents=True, exist_ok=True)
    (state_dir / "agent_state_refresh.json").write_text("{not json", encoding="utf-8")
    summary = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_with([inventory_run("run-1", "foo.job", "completed")]),
    )
    assert summary.errors == 0
    assert summary.changed == 1

    (state_dir / "agent_state_refresh.json").write_text(
        json.dumps({"schema_version": 999, "projects": {}}), encoding="utf-8"
    )
    followup = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_with([inventory_run("run-1", "foo.job", "completed")]),
    )
    assert followup.errors == 0


def test_no_enabled_projects_reports_cleanly(tmp_path: Path) -> None:
    summary = run_agent_state_refresh(
        state_dir=tmp_path,
        list_targets=lambda: ([], []),
        require_owner=owner_identity,
    )
    assert summary.projects == 0
    assert summary.reason == "no_enabled_projects"


def test_missing_owner_identity_is_check_error(tmp_path: Path) -> None:
    def no_owner():
        raise RuntimeError("no owner configured")

    summary = run_agent_state_refresh(
        state_dir=tmp_path,
        list_targets=lambda: ([], []),
        require_owner=no_owner,
    )
    assert summary.errors == 1
    assert summary.reason == "no_owner_identity"


def test_fair_rotation_and_backoff_across_projects(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    remote_a, base_a = setup_refresh_repo(
        dir_a, runs=[("foo", "foo.job", "run-1", "active")]
    )
    remote_b, base_b = setup_refresh_repo(
        dir_b, runs=[("foo", "foo.job", "run-1", "active")]
    )
    _ = (remote_a, remote_b)
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    calls: list[str] = []

    def failing(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        calls.append(target.project_key)
        return StateRepairReport(
            target.project_key, target.project, "apply", error="boom"
        )

    targets = [target_a, target_b]
    summary = run_agent_state_refresh(
        state_dir=tmp_path / "state",
        now_ms=1_000,
        list_targets=targets_for(targets),
        require_owner=owner_identity,
        repair_one=failing,
    )
    assert summary.selected_project == targets[0].project_key
    assert summary.reason == "project_failed"

    # Failed project backs off; the next tick selects the other project.
    selected: list[str] = []

    def ok(target: ProjectTarget, owner: AgentOwnerIdentity, **kwargs):
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=tmp_path / "state",
        now_ms=2_000,
        list_targets=targets_for(targets),
        require_owner=owner_identity,
        repair_one=ok,
    )
    assert second.selected_project != targets[0].project_key
    assert selected == [second.selected_project]


def test_success_advances_cursor_and_end_of_pass_resets(tmp_path: Path) -> None:
    _remote, sync_target = setup_refresh_repo(
        tmp_path,
        runs=[
            ("aaa", "aaa.job", "run-aaa", "active"),
            ("mmm", "mmm.job", "run-mmm", "active"),
        ],
    )
    evidence = [
        inventory_run("run-aaa", "aaa.job", "completed"),
        inventory_run("run-mmm", "mmm.job", "completed"),
    ]
    state_dir = tmp_path / "state"
    key = f"{sync_target.project_key}:alice@athena"
    first = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=1_000,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_with(evidence),
        state_limit=1,
    )
    assert first.changed == 1
    assert first.pass_complete is False
    assert first.next_cursor is not None
    assert _stored_cursor(state_dir, key) == first.next_cursor

    # Scheduler restart reloads the same cursor from disk.
    assert _stored_cursor(state_dir, key) == first.next_cursor

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=targets_for([sync_target]),
        require_owner=owner_identity,
        repair_one=repair_with(evidence),
        state_limit=1,
    )
    assert second.changed == 1
    assert second.pass_complete is True
    assert _stored_cursor(state_dir, key) is None


def test_killed_tick_backs_off_and_rotates(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _remote_a, base_a = setup_refresh_repo(
        dir_a, runs=[("foo", "foo.job", "run-1", "active")]
    )
    _remote_b, base_b = setup_refresh_repo(
        dir_b, runs=[("foo", "foo.job", "run-1", "active")]
    )
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    targets = [target_a, target_b]
    state_dir = tmp_path / "state"

    def killing(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        raise _KilledTick("sigkill")

    with pytest.raises(_KilledTick):
        run_agent_state_refresh(
            state_dir=state_dir,
            now_ms=1_000,
            list_targets=targets_for(targets),
            require_owner=owner_identity,
            repair_one=killing,  # type: ignore[arg-type]
        )

    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    key = f"{targets[0].project_key}:alice@athena"
    assert payload["projects"][key]["failure_count"] == 1
    assert payload["projects"][key]["retry_after_ms"] > 1_000
    assert payload["projects"][key]["cursor"] is None
    assert payload["last_selected"]["project"] == targets[0].project_key

    selected: list[str] = []

    def ok(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=targets_for(targets),
        require_owner=owner_identity,
        repair_one=ok,  # type: ignore[arg-type]
    )
    assert second.selected_project != targets[0].project_key
    assert selected == [second.selected_project]


def test_frozen_window_retries_with_backoff(tmp_path: Path) -> None:
    import dataclasses

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _remote_a, base_a = setup_refresh_repo(
        dir_a, runs=[("foo", "foo.job", "run-1", "active")]
    )
    _remote_b, base_b = setup_refresh_repo(
        dir_b, runs=[("foo", "foo.job", "run-1", "active")]
    )
    target_a = dataclasses.replace(base_a, project_key="proj-a", project="Project A")
    target_b = dataclasses.replace(base_b, project_key="proj-b", project="Project B")
    targets = [target_a, target_b]
    state_dir = tmp_path / "state"

    def frozen(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            next_cursor=None,
            pass_complete=False,
        )

    first = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=1_000,
        list_targets=targets_for(targets),
        require_owner=owner_identity,
        repair_one=frozen,  # type: ignore[arg-type]
    )
    assert first.reason == "window_not_advanced"
    assert first.errors == 0
    assert any("did not advance" in item for item in first.diagnostics)

    payload = json.loads(
        (state_dir / "agent_state_refresh.json").read_text(encoding="utf-8")
    )
    key = f"{first.selected_project}:alice@athena"
    assert payload["projects"][key]["failure_count"] == 1
    assert payload["projects"][key]["retry_after_ms"] > 1_000
    assert payload["projects"][key]["cursor"] is None

    selected: list[str] = []

    def ok(target: object, owner: object, **kwargs: object) -> StateRepairReport:
        selected.append(target.project_key)
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            examined=1,
            already_current=1,
            next_cursor="cursor-1",
            pass_complete=True,
        )

    second = run_agent_state_refresh(
        state_dir=state_dir,
        now_ms=2_000,
        list_targets=targets_for(targets),
        require_owner=owner_identity,
        repair_one=ok,  # type: ignore[arg-type]
    )
    assert second.selected_project != first.selected_project
    assert selected == [second.selected_project]


class _KilledTick(BaseException):
    pass
