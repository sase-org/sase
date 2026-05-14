"""Tests for the shared agent launch executor."""

from __future__ import annotations

import dataclasses
import os
from unittest.mock import patch

import pytest

from sase.agent.launch_executor import (
    LaunchExecutionContext,
    LaunchSpawnRequest,
    execute_launch_plan,
)
from sase.agent.launcher import AgentLaunchResult
from sase.core.agent_launch_facade import plan_fake_fanout


def _result_for(request: LaunchSpawnRequest) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=123,
        workspace_num=request.workspace_num,
        workspace_dir=request.workspace_dir,
        output_path="/tmp/out",
        project_file=request.project_file,
        project_name=request.project_name,
        workflow_name=request.workflow_name,
        cl_name=request.cl_name,
        timestamp=request.timestamp,
    )


def test_execute_single_launch_plan_uses_preallocated_context_and_timestamp() -> None:
    requests: list[LaunchSpawnRequest] = []

    execution = execute_launch_plan(
        plan_fake_fanout("single", ["do work"]),
        LaunchExecutionContext(
            cl_name="change",
            project_file="/project.sase",
            project_name="project",
            update_target="p4head",
            history_sort_key="change",
            workspace_num=7,
            workspace_dir="/workspace/7",
            use_preallocated_workspace=True,
        ),
        spawn=lambda request: requests.append(request) or _result_for(request),
        base_timestamp="ts",
    )

    assert execution.launched_count == 1
    assert execution.results[0].timestamp == "ts"
    assert requests[0].as_spawn_kwargs() == {
        "cl_name": "change",
        "project_file": "/project.sase",
        "workspace_dir": "/workspace/7",
        "workspace_num": 7,
        "workflow_name": "ace(run)-ts",
        "prompt": "do work",
        "timestamp": "ts",
        "update_target": "p4head",
        "project_name": "project",
        "history_sort_key": "change",
        "is_home_mode": False,
        "vcs_ref": None,
        "deferred_workspace": False,
        "local_xprompts_file": None,
        "extra_env": None,
        "retry_transfer_from_pid": None,
    }


def test_execute_launch_plan_daemon_mode_submits_scheduler_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_SCHEDULER_LAUNCH_MODE", "daemon")
    requests: list[LaunchSpawnRequest] = []
    executed: list[str] = []
    response = {
        "handle": {
            "batch_id": "batch-a",
            "queue_id": "agents",
            "status": "queued",
        },
        "status": {
            "slots": [
                {
                    "slot_index": 0,
                    "slot_id": "slot-a",
                    "status": "queued",
                }
            ]
        },
    }

    with patch(
        "sase.daemon.scheduler.submit_scheduler_batch", return_value=response
    ) as submit:
        execution = execute_launch_plan(
            plan_fake_fanout("single", ["do work"]),
            LaunchExecutionContext(
                cl_name="home",
                project_file="/home.sase",
                project_name="home",
                is_home_mode=True,
                workspace_num=0,
                workspace_dir="/home/user",
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            base_timestamp="ts",
            on_slot_executed=lambda record: executed.append(
                record.result.scheduler_batch_id if record.result else ""
            ),
        )

    assert requests == []
    assert execution.launched_count == 1
    assert execution.results[0].pid == 0
    assert execution.results[0].scheduler_batch_id == "batch-a"
    assert execution.results[0].scheduler_slot_id == "slot-a"
    assert executed == ["batch-a"]
    submitted = submit.call_args.args[1].to_wire()
    assert submitted["project_id"] == "home"
    assert submitted["queue_id"] == "agents"
    assert submitted["launch_specs"][0]["prompt"] == "do work"
    assert submitted["launch_specs"][0]["cwd"] == "/home/user"
    assert submitted["launch_specs"][0]["metadata"]["timestamp"] == "ts"


def test_execute_launch_plan_shadow_mode_submits_then_launches_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_SCHEDULER_LAUNCH_MODE", "shadow")
    requests: list[LaunchSpawnRequest] = []

    with patch("sase.daemon.scheduler.submit_scheduler_batch", return_value={}):
        execution = execute_launch_plan(
            plan_fake_fanout("single", ["do work"]),
            LaunchExecutionContext(
                cl_name="home",
                project_file="/home.sase",
                project_name="home",
                is_home_mode=True,
                workspace_num=0,
                workspace_dir="/home/user",
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            base_timestamp="ts",
        )

    assert len(requests) == 1
    assert execution.results[0].pid == 123
    assert execution.results[0].scheduler_batch_id is None


def test_execute_launch_plan_daemon_mode_falls_back_for_unsupported_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_SCHEDULER_LAUNCH_MODE", "daemon")
    requests: list[LaunchSpawnRequest] = []

    with patch("sase.daemon.scheduler.submit_scheduler_batch") as submit:
        execution = execute_launch_plan(
            plan_fake_fanout("single", ["do work"]),
            LaunchExecutionContext(
                cl_name="home",
                project_file="/home.sase",
                project_name="home",
                is_home_mode=True,
                workspace_num=0,
                workspace_dir="/home/user",
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            extra_env={"SASE_REPEAT_NAME": "repeat.1"},
            base_timestamp="ts",
        )

    submit.assert_not_called()
    assert len(requests) == 1
    assert execution.results[0].pid == 123


def test_execute_fanout_plan_allocates_workspace_per_slot_and_merges_env() -> None:
    plan = plan_fake_fanout("model", ["%model:a p", "%model:b p"])
    plan = dataclasses.replace(
        plan,
        slots=[
            dataclasses.replace(plan.slots[0], timestamp="260501_120000"),
            dataclasses.replace(plan.slots[1], timestamp="260501_120001"),
        ],
    )
    requests: list[LaunchSpawnRequest] = []
    executed: list[str] = []

    with (
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=[10, 11],
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[("/workspace/10", None), ("/workspace/11", None)],
        ),
    ):
        execution = execute_launch_plan(
            plan,
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.sase",
                project_name="project",
                vcs_ref=("git", "change"),
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            extra_env={"BASE": "1"},
            slot_extra_env=lambda slot: {"SLOT": str(slot.slot_index)},
            on_slot_executed=lambda record: executed.append(record.request.timestamp),
        )

    assert execution.launched_count == 2
    assert [request.workspace_num for request in requests] == [10, 11]
    assert [request.workspace_dir for request in requests] == [
        "/workspace/10",
        "/workspace/11",
    ]
    assert [request.extra_env for request in requests] == [
        {"BASE": "1", "SLOT": "0"},
        {"BASE": "1", "SLOT": "1"},
    ]
    # Pre-claimed slot is transferred to the spawned child via the
    # transfer_from_pid mechanism; ensure both slots carry it.
    parent_pid = os.getpid()
    assert [request.transfer_from_pid for request in requests] == [
        parent_pid,
        parent_pid,
    ]
    assert executed == ["260501_120000", "260501_120001"]


def test_workspace_claim_failure_retries_with_new_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.running_field import WorkspaceClaimError

    plan = plan_fake_fanout("single", ["do work"])
    requests: list[LaunchSpawnRequest] = []
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "2")

    def _spawn(request: LaunchSpawnRequest) -> AgentLaunchResult:
        requests.append(request)
        if len(requests) == 1:
            raise WorkspaceClaimError(
                "Failed to claim workspace #100: workspace #100 is already claimed",
                workspace_num=100,
            )
        return _result_for(request)

    released: list[tuple[int, str | None]] = []
    with (
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=[100, 101],
        ) as first_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[("/workspace/100", None), ("/workspace/101", None)],
        ) as ws_dir,
        patch(
            "sase.running_field.release_workspace",
            side_effect=lambda pf, n, wf, cl: released.append((n, cl)),
        ) as release,
    ):
        execution = execute_launch_plan(
            plan,
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.sase",
                project_name="project",
            ),
            spawn=_spawn,
            base_timestamp="ts",
        )

    assert execution.results[0].workspace_num == 101
    assert [request.workspace_num for request in requests] == [100, 101]
    assert first_ws.call_count == 2
    assert ws_dir.call_count == 2
    # Workspace #100 must be released after the failed spawn attempt so the
    # slot doesn't leak across the retry boundary.
    assert release.call_count == 1
    assert released == [(100, "change")]


def test_workspace_claim_retry_exhaustion_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.running_field import WorkspaceClaimError

    monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "1")

    with (
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=[100, 101],
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[("/workspace/100", None), ("/workspace/101", None)],
        ),
        patch("sase.running_field.release_workspace"),
    ):
        with pytest.raises(
            WorkspaceClaimError,
            match=(
                r"Failed to claim an available workspace for project/change "
                r"after 2 attempts"
            ),
        ):
            execute_launch_plan(
                plan_fake_fanout("single", ["do work"]),
                LaunchExecutionContext(
                    cl_name="change",
                    project_file="/project.sase",
                    project_name="project",
                ),
                spawn=lambda _request: (_ for _ in ()).throw(
                    WorkspaceClaimError(
                        "Failed to claim workspace #100: race lost",
                        workspace_num=100,
                    )
                ),
                base_timestamp="ts",
            )


@pytest.mark.parametrize(
    ("context", "expected_workspace_num", "expected_workspace_dir"),
    [
        (
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.sase",
                project_name="project",
                workspace_num=7,
                workspace_dir="/workspace/7",
                use_preallocated_workspace=True,
            ),
            7,
            "/workspace/7",
        ),
        (
            LaunchExecutionContext(
                cl_name="home",
                project_file="/home.sase",
                project_name="home",
                is_home_mode=True,
                workspace_num=0,
                workspace_dir="/home/user",
            ),
            0,
            "/home/user",
        ),
        (
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.sase",
                project_name="project",
                deferred_workspace=True,
            ),
            0,
            "/workspace/main",
        ),
    ],
)
def test_fixed_workspace_modes_do_not_retry_claim_failures(
    context: LaunchExecutionContext,
    expected_workspace_num: int,
    expected_workspace_dir: str,
) -> None:
    requests: list[LaunchSpawnRequest] = []

    def _spawn(request: LaunchSpawnRequest) -> AgentLaunchResult:
        requests.append(request)
        raise RuntimeError(f"Failed to claim workspace #{request.workspace_num}")

    with (
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value="/workspace/main",
        ),
    ):
        with pytest.raises(RuntimeError, match="Failed to claim workspace #"):
            execute_launch_plan(
                plan_fake_fanout("single", ["do work"]),
                context,
                spawn=_spawn,
                base_timestamp="ts",
            )

    assert len(requests) == 1
    assert requests[0].workspace_num == expected_workspace_num
    assert requests[0].workspace_dir == expected_workspace_dir
    first_ws.assert_not_called()
