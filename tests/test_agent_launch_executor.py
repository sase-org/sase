"""Tests for the shared agent launch executor."""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

from sase.agent.launch_executor import (
    LaunchExecutionContext,
    LaunchSpawnRequest,
    execute_launch_plan,
)
from sase.agent.launcher import AgentLaunchResult
from sase.axe.chop_agents import ENV_CHOP_LUMBERJACK, ENV_CHOP_NAME, ENV_CHOP_RUN_ID
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
            project_file="/project.gp",
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
        "project_file": "/project.gp",
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
    }


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
            "sase.running_field.get_first_available_axe_workspace",
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
                project_file="/project.gp",
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
    assert executed == ["260501_120000", "260501_120001"]


def test_execute_fanout_plan_tags_each_chop_prompt() -> None:
    plan = plan_fake_fanout("model", ["%model:a p", "%model:b p"])
    requests: list[LaunchSpawnRequest] = []

    with (
        patch(
            "sase.running_field.get_first_available_axe_workspace",
            side_effect=[10, 11],
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[("/workspace/10", None), ("/workspace/11", None)],
        ),
    ):
        execute_launch_plan(
            plan,
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.gp",
                project_name="project",
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            extra_env={
                ENV_CHOP_LUMBERJACK: "hooks",
                ENV_CHOP_NAME: "split",
                ENV_CHOP_RUN_ID: "run-1",
            },
        )

    assert [request.prompt for request in requests] == [
        "%tag:chop\n%model:a p",
        "%tag:chop\n%model:b p",
    ]


def test_execute_fanout_plan_preserves_explicit_tag_under_chop_env() -> None:
    plan = plan_fake_fanout("model", ["%tag:custom\n%model:a p"])
    requests: list[LaunchSpawnRequest] = []

    with (
        patch("sase.running_field.get_first_available_axe_workspace", return_value=10),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/workspace/10", None),
        ),
    ):
        execute_launch_plan(
            plan,
            LaunchExecutionContext(
                cl_name="change",
                project_file="/project.gp",
                project_name="project",
            ),
            spawn=lambda request: requests.append(request) or _result_for(request),
            extra_env={
                ENV_CHOP_LUMBERJACK: "hooks",
                ENV_CHOP_NAME: "split",
                ENV_CHOP_RUN_ID: "run-1",
            },
        )

    assert requests[0].prompt == "%tag:custom\n%model:a p"
