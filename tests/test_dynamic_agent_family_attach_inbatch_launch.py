from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.family_attach import FAMILY_ATTACH_ENV
from sase.agent.launch_executor import (
    LaunchExecutionContext,
    LaunchSpawnRequest,
    execute_launch_plan,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.core.agent_launch_facade import plan_fake_fanout


def _patch_empty_attach_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.agent.family_attach.agent_family_snapshot",
        lambda _project_name: SimpleNamespace(records=[]),
    )
    monkeypatch.setattr("sase.agent.family_attach.dismissed_identity_dicts", list)
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", set)


def test_execute_launch_plan_attaches_to_prior_in_batch_named_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_empty_attach_snapshot(monkeypatch)
    plan = plan_fake_fanout(
        "multi",
        [
            "%auto %i:foo\nPlan the change.",
            "%i(foo, reviewer)\nReview foo's plan.",
            "%i(foo, land)\nLand after review.",
        ],
    )
    plan = replace(
        plan,
        slots=[
            replace(plan.slots[0], timestamp="260701_010101"),
            replace(plan.slots[1], timestamp="260701_010102"),
            replace(plan.slots[2], timestamp="260701_010103"),
        ],
    )
    requests: list[LaunchSpawnRequest] = []

    def spawn(request: LaunchSpawnRequest) -> AgentLaunchResult:
        requests.append(request)
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

    with (
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch("sase.running_field.claim_next_axe_workspace", return_value=100),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/workspace/100", None),
        ),
    ):
        execution = execute_launch_plan(
            plan,
            LaunchExecutionContext(
                cl_name="feature",
                project_file="/tmp/sase.sase",
                project_name="sase",
            ),
            spawn=spawn,
        )

    assert execution.launched_count == 3
    assert [request.workspace_num for request in requests] == [100, 0, 0]
    assert requests[1].workspace_dir == "/workspace/100"
    assert requests[1].deferred_workspace is True
    assert requests[1].extra_env is not None
    assert requests[1].extra_env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM"] == "100"
    payload = json.loads(requests[1].extra_env[FAMILY_ATTACH_ENV])
    assert payload["agent_name"] == "foo--reviewer"
    assert payload["parent_name"] == "foo"
    assert payload["parent_timestamp"] == "20260701010101"
    assert payload["parent_workspace_dir"] == "/workspace/100"
    assert payload["parent_workspace_num"] == 100
    assert payload["parent_is_running"] is True
    assert payload["parent_family_role_suffix"] == "--plan"
    assert requests[2].extra_env is not None
    chained_payload = json.loads(requests[2].extra_env[FAMILY_ATTACH_ENV])
    assert chained_payload["agent_name"] == "foo--land"
    assert chained_payload["parent_name"] == "foo--reviewer"
    assert chained_payload["parent_timestamp"] == "20260701010102"
    assert chained_payload["parent_is_running"] is True


def test_multi_prompt_family_attach_can_reference_earlier_named_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_empty_attach_snapshot(monkeypatch)
    spawn_calls: list[dict[str, object]] = []

    def spawn_agent(**kwargs: object) -> AgentLaunchResult:
        spawn_calls.append(kwargs)
        return AgentLaunchResult(
            pid=len(spawn_calls),
            workspace_num=int(kwargs["workspace_num"]),
            workspace_dir=str(kwargs["workspace_dir"]),
            output_path="/tmp/out",
            project_file=str(kwargs["project_file"]),
            project_name=str(kwargs["project_name"]),
            workflow_name=str(kwargs["workflow_name"]),
            cl_name=str(kwargs["cl_name"]),
            timestamp=str(kwargs["timestamp"]),
        )

    with (
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch("sase.core.time.generate_timestamp", return_value="260701_010101"),
        patch("sase.running_field.claim_next_axe_workspace", return_value=100),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/workspace/100", None),
        ),
        patch("sase.agent.launcher.spawn_agent_subprocess", side_effect=spawn_agent),
    ):
        results = launch_multi_prompt_agents(
            segments=[
                "%i:foo\nPlan the change.",
                "%i(foo, reviewer)\nReview foo's plan.",
            ],
            local_xprompts={},
            cl_name="feature",
            project_file="/tmp/sase.sase",
            project_name="sase",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert len(results) == 2
    assert len(spawn_calls) == 2
    assert spawn_calls[1]["workspace_num"] == 0
    assert spawn_calls[1]["workspace_dir"] == "/workspace/100"
    assert spawn_calls[1]["deferred_workspace"] is True
    extra_env = spawn_calls[1]["extra_env"]
    assert isinstance(extra_env, dict)
    assert extra_env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM"] == "100"
    payload = json.loads(str(extra_env[FAMILY_ATTACH_ENV]))
    assert payload["agent_name"] == "foo--reviewer"
    assert payload["parent_name"] == "foo"
    assert payload["parent_timestamp"] == "20260701010101"
    assert payload["parent_workspace_dir"] == "/workspace/100"
    assert payload["parent_workspace_num"] == 100
    assert payload["parent_is_running"] is True
    assert payload["parent_family_role_suffix"] == "--0"
