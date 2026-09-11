"""Tests for the Rust-backed agent-launch wire contract."""

from __future__ import annotations

import json

import pytest

from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentUnitWire,
    LaunchPlanWire,
    ProcUnitWire,
    WaitTargetWire,
    WorkspaceClaimRequestWire,
    agent_launch_prepared_from_dict,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.feature_flags import override_flags
from sase.xprompt.directives import DirectiveError


def test_agent_launch_schema_version_pinned() -> None:
    assert AGENT_LAUNCH_WIRE_SCHEMA_VERSION == 1


def test_typed_launch_plan_from_dict_rehydrates_proc_payload() -> None:
    payload = {
        "schema_version": 1,
        "launch_kind": "multi_prompt",
        "selected_project": "sase",
        "content_digest": "a" * 64,
        "approval_preview": ["LaunchPlan v1"],
        "units": [
            {
                "logical_id": "unit-1",
                "source_order": 0,
                "waits": [],
                "payload": {
                    "kind": "proc",
                    "code": {
                        "schema_version": 1,
                        "source": "just check",
                        "language": "bash",
                        "digest": "b" * 64,
                        "preview": "just check",
                    },
                    "shell_name": "check",
                    "workspace": True,
                    "workspace_explicit": False,
                    "selected_project": "sase",
                },
            },
            {
                "logical_id": "unit-2",
                "source_order": 1,
                "waits": [
                    {
                        "kind": "logical",
                        "logical_id": "unit-1",
                        "source": "%wait",
                    }
                ],
                "payload": {"kind": "agent", "prompt": "Review"},
            },
        ],
        "diagnostics": [],
    }

    plan = launch_plan_from_dict(payload)

    assert isinstance(plan, LaunchPlanWire)
    assert isinstance(plan.units[0].payload, ProcUnitWire)
    assert plan.units[0].payload.code.source == "just check"
    assert plan.units[1].waits == [
        WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")
    ]
    assert (
        agent_launch_wire_to_json_dict(plan)["units"][0]["payload"]["code"]["preview"]
        == "just check"
    )


def test_plan_typed_launch_units_feature_off_rejects_proc() -> None:
    with pytest.raises(DirectiveError, match="typed_launch_units"):
        plan_typed_launch_units('%proc("just check")', selected_project="sase")


def test_agent_unit_queue_weight_round_trips_json_shape() -> None:
    unit = AgentUnitWire(
        prompt="Do work",
        wait_runners=2,
        queue_weight=0.25,
        queue_weight_explicit=True,
    )

    payload = agent_launch_wire_to_json_dict(unit)

    assert payload["queue_weight"] == 0.25
    assert payload["queue_weight_explicit"] is True
    plan = launch_plan_from_dict(
        {
            "schema_version": 1,
            "launch_kind": "single",
            "selected_project": "sase",
            "content_digest": "a" * 64,
            "units": [
                {
                    "logical_id": "unit-1",
                    "source_order": 0,
                    "waits": [],
                    "payload": payload,
                }
            ],
        }
    )
    restored = plan.units[0].payload
    assert isinstance(restored, AgentUnitWire)
    assert restored.queue_weight == 0.25
    assert restored.queue_weight_explicit is True


def test_agent_unit_omits_default_queue_weight_provenance_from_json() -> None:
    payload = agent_launch_wire_to_json_dict(
        AgentUnitWire(prompt="Do work", queue_weight=1.0)
    )

    assert payload["queue_weight"] == 1.0
    assert "queue_weight_explicit" not in payload


def test_plan_typed_launch_units_rust_mixed_graph() -> None:
    pytest.importorskip("sase_core_rs")

    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            '%proc("just check")\n---\n%wait\n%id:reviewer\nReview',
            launch_kind="multi_prompt",
            selected_project="sase",
        )

    assert plan.launch_kind == "multi_prompt"
    assert isinstance(plan.units[0].payload, ProcUnitWire)
    assert plan.units[0].payload.workspace is True
    assert plan.units[0].payload.code.digest
    assert plan.units[1].waits[0].kind == "logical"
    assert plan.units[1].waits[0].logical_id == "unit-1"


def test_workspace_claim_request_round_trips_json_shape() -> None:
    request = WorkspaceClaimRequestWire(
        project_file="/tmp/project.sase",
        workspace_num=2,
        workflow_name="ace(run)-260501_120000",
        pid=123,
        cl_name="feature",
        artifacts_timestamp="20260501120000",
        transfer_from_pid=99,
    )

    payload = agent_launch_wire_to_json_dict(request)
    assert json.loads(json.dumps(payload)) == {
        "project_file": "/tmp/project.sase",
        "workspace_num": 2,
        "workflow_name": "ace(run)-260501_120000",
        "pid": 123,
        "cl_name": "feature",
        "artifacts_timestamp": "20260501120000",
        "transfer_from_pid": 99,
        "pinned": False,
    }
    prepared_payload = {
        "schema_version": AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        "prompt_file": "/tmp/prompt.md",
        "output_path": "/tmp/agent.log",
        "safe_name": "agent",
        "argv": ["python", "runner.py"],
        "cwd": "/tmp",
        "claim_request": payload,
    }
    assert agent_launch_prepared_from_dict(prepared_payload).claim_request == request
