"""Monitor-start and fallback-proc coverage for approved-epic launch."""

from __future__ import annotations

import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor
from sase.dev_update.code_swap_lock import (
    guarded_exec_argv,
    logical_argv_from_guarded_exec,
)

from .epic_launch_test_helpers import fake_lease, start_epic_launch_monitor_request


def test_start_epic_launch_monitor_starts_literal_monitor_command(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    monitor = SimpleNamespace(monitor_id="m7k2xyz")
    lease = fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ) as acquire,
        patch("sase.workspace_provider.lease.release_operational_lease") as release,
        patch(
            "sase.monitor.start.start_monitor",
            return_value=monitor,
        ) as start_monitor,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "planner"},
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            origin="telegram",
        )

    assert submitted is monitor
    acquire.assert_called_once_with(
        "sase",
        workflow="epic-launch",
        holder="planner",
        cl_name="demo",
    )
    release.assert_not_called()
    request = start_monitor.call_args.args[0]
    logical = build_epic_launch_argv(
        plan,
        artifacts_dir=tmp_path / "artifacts",
        cl_name="demo",
    )
    assert request.command == shlex.join(logical)
    assert list(request.execution_argv) == guarded_exec_argv(logical)
    assert logical_argv_from_guarded_exec(list(request.execution_argv)) == logical
    assert request.cwd == str(lease.checkout_dir)
    assert request.project_name == "sase"
    assert request.lane == "planner"
    assert request.label == "Epic launch · auth rewrite"
    assert request.reason == "Launch the approved epic from auth rewrite.md"
    assert request.next_action is None
    assert request.start_status == "EPIC APPROVED"
    assert request.stop_status == "EPIC CREATED"
    assert request.timeout_seconds == 4 * 60 * 60
    assert request.inherit_lane_workspace_claim is False
    assert request.transfer_claim_from_pid == lease.claim_pid


def test_start_epic_launch_monitor_uses_clan_member_name_as_lane(
    tmp_path: Path,
) -> None:
    request = start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "sase-m6.6", "agent_clan": "sase-m6"},
    )

    assert request.lane == "sase-m6.6"


def test_start_epic_launch_monitor_treats_legacy_parallel_family_as_clan(
    tmp_path: Path,
) -> None:
    request = start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={
            "name": "sase-m6.6",
            "agent_family": "sase-m6",
            "agent_family_parallel": True,
        },
    )

    assert request.lane == "sase-m6.6"


def test_start_epic_launch_monitor_uses_explicit_family_lane(
    tmp_path: Path,
) -> None:
    request = start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "auth--plan", "agent_family": "auth"},
    )

    assert request.lane == "auth"


def test_start_epic_launch_monitor_parses_name_when_group_metadata_is_absent(
    tmp_path: Path,
) -> None:
    request = start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "sase-m6.6"},
    )

    assert request.lane == "sase-m6"


def test_start_epic_launch_monitor_falls_back_to_leased_proc_when_lane_missing(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    task = SimpleNamespace(
        task_id="k7m2xyz",
        kind="command",
        session_id=None,
    )
    lease = fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ) as acquire,
        patch("sase.workspace_provider.lease.release_operational_lease") as release,
        patch(
            "sase.workspace_provider.lease.submit_via_lease",
            return_value=task,
        ) as submit_via_lease,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            origin="telegram",
        )

    assert submitted is task
    release.assert_not_called()
    acquire.assert_called_once_with(
        "sase",
        workflow="epic-launch",
        holder="epic-launch",
        cl_name="demo",
    )
    request = submit_via_lease.call_args.args[0]
    logical = build_epic_launch_argv(
        plan,
        artifacts_dir=tmp_path / "artifacts",
        cl_name="demo",
    )
    assert list(request.command) == logical
    assert list(request.argv) == guarded_exec_argv(logical)
    assert logical_argv_from_guarded_exec(list(request.argv)) == logical
    assert request.label == "Epic launch · auth rewrite"
    assert request.cwd == str(lease.checkout_dir)
    assert request.origin == "telegram"
    assert request.project == "sase"
    assert request.cl_name == "demo"
    assert request.session_id is None
    assert sorted(request.tags) == ["epic", "launch"]
    assert submit_via_lease.call_args.args[1] is lease


def test_start_epic_launch_monitor_fallback_deduplicates_active_resolved_plan(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    existing = SimpleNamespace(
        task_id="existing",
        command=["sase", "bead", "work", "plans/epic.md", "--yes-to-all"],
        cwd=str(tmp_path),
        tags=["epic", "launch"],
    )
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[existing]) as read_tasks,
        patch("sase.workspace_provider.lease.acquire_operational_lease") as acquire,
    ):
        submitted = start_epic_launch_monitor(plan, project="sase")

    assert submitted is existing
    read_tasks.assert_called_once()
    assert read_tasks.call_args.kwargs["status"] == frozenset(
        {"pending", "running", "settling"}
    )
    assert read_tasks.call_args.kwargs["kind"] == {"command", "detached"}
    acquire.assert_not_called()


def test_start_epic_launch_monitor_fallback_deduplicates_guarded_argv(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    existing = SimpleNamespace(
        task_id="existing",
        command=guarded_exec_argv(
            ["sase", "bead", "work", "plans/epic.md", "--yes-to-all"]
        ),
        cwd=str(tmp_path),
        tags=["epic", "launch"],
    )
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[existing]),
        patch("sase.workspace_provider.lease.acquire_operational_lease") as acquire,
    ):
        submitted = start_epic_launch_monitor(plan, project="sase")

    assert submitted is existing
    acquire.assert_not_called()
