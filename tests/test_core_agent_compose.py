"""Golden tests for the agent compose reference wire contract."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_compose_facade import (
    build_agent_compose_input,
    compose_agent_list,
    compose_agent_list_reference,
    compose_python_agents_to_wire,
    log_compose_mismatch,
    with_options,
)
from sase.core.agent_compose_wire import (
    AGENT_COMPOSE_WIRE_SCHEMA_VERSION,
    AgentComposeInputWire,
    AgentComposeOptionsWire,
    AgentWire,
    DropReasonWire,
    MergeReasonWire,
    RunningClaimWire,
    agent_compose_input_from_dict,
    agent_compose_wire_to_json_dict,
    agent_from_wire,
    agent_to_wire,
    composed_agent_list_from_dict,
    composed_agent_list_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from .agent_compose_golden import build_golden_agents, fixture_summary


def test_schema_version_pinned() -> None:
    assert AGENT_COMPOSE_WIRE_SCHEMA_VERSION == 1


def test_fixture_summary_matches_contract_surface() -> None:
    assert fixture_summary() == {
        "count": 6,
        "statuses": ["DONE", "FAILED", "PLAN APPROVED", "QUESTION", "RUNNING"],
        "has_followup": True,
        "has_retry_chain": True,
        "has_workflow_child": True,
    }


def test_agent_wire_round_trips_contract_fields() -> None:
    agent = build_golden_agents()[0]
    record = agent_to_wire(agent)
    restored = agent_from_wire(record)

    assert record.agent_type == "workflow"
    assert record.identity == ("workflow", "demo_plan", "20260501090000")
    assert record.status == "PLAN APPROVED"
    assert record.plan_times == ["2026-05-01T09:04:00"]
    assert record.code_time == "2026-05-01T09:08:00"
    assert record.followup_identities == [("run", "demo_plan", "20260501090800")]
    assert restored.agent_type.value == agent.agent_type.value
    assert restored.status == agent.status
    assert restored.start_time == agent.start_time
    assert restored.step_output == agent.step_output


def test_composed_wire_json_shape_is_stable() -> None:
    result = compose_python_agents_to_wire(build_golden_agents())
    payload = composed_agent_list_to_json_dict(result)

    assert payload["schema_version"] == AGENT_COMPOSE_WIRE_SCHEMA_VERSION
    assert payload["dropped"] == []
    assert payload["merge_log"] == []
    assert [agent["status"] for agent in payload["agents"]] == [
        "PLAN APPROVED",
        "DONE",
        "RUNNING",
        "QUESTION",
        "FAILED",
        "RUNNING",
    ]
    assert payload["agents"][0]["followup_identities"] == [
        ("run", "demo_plan", "20260501090800")
    ]

    # The dict is JSON-safe for future Rust parity files.
    round_tripped = json.loads(json.dumps(payload))
    rebuilt = composed_agent_list_from_dict(round_tripped)
    assert [agent.status for agent in rebuilt.agents] == [
        "PLAN APPROVED",
        "DONE",
        "RUNNING",
        "QUESTION",
        "FAILED",
        "RUNNING",
    ]
    assert rebuilt.agents[4].retry_chain_sibling_identities == [
        ("run", "retry_case", "20260501110200")
    ]


def test_reference_facade_delegates_to_current_loader() -> None:
    agents = build_golden_agents()
    with patch(
        "sase.ace.tui.models.agent_loader.load_all_agents",
        return_value=agents,
    ) as loader:
        result = compose_agent_list_reference(AgentComposeInputWire())

    loader.assert_called_once_with(changespec_snapshot=None)
    assert [agent.identity for agent in result.agents] == [
        ("workflow", "demo_plan", "20260501090000"),
        ("workflow", "demo_plan", "20260501090100"),
        ("run", "demo_plan", "20260501090800"),
        ("run", "needs_answer", "20260501101000"),
        ("run", "retry_case", "20260501110000"),
        ("run", "retry_case", "20260501110200"),
    ]


def test_options_helper_preserves_dataclass_type() -> None:
    opts = with_options(AgentComposeOptionsWire(), include_workflow_steps=False)
    assert opts.include_workflow_steps is False
    assert opts.include_diagnostics is True


def test_contract_diagnostic_records_are_json_safe() -> None:
    running_claim = RunningClaimWire(
        project_file="/tmp/project.gp",
        project_name="demo",
        cl_name="demo_cl",
        pid=123,
    )
    dropped = DropReasonWire(
        stage="dead_pid_filter",
        identity=("run", "demo_cl", "20260501120000"),
        reason="dead_pid",
    )
    merged = MergeReasonWire(
        stage="dedup_by_pid",
        source_identity=("run", "demo_cl", "20260501120000"),
        target_identity=("workflow", "demo_cl", "20260501120000"),
        reason="prefer_workflow",
        fields=["workspace_num"],
    )

    assert running_claim.pid == 123
    assert dropped.identity[0] == "run"
    assert merged.fields == ["workspace_num"]


def test_input_from_dict_rejects_schema_mismatch() -> None:
    with pytest.raises(ValueError, match="Unsupported AgentComposeInputWire"):
        agent_compose_input_from_dict({"schema_version": 999})


def test_agent_wire_from_dict_uses_defaults_for_new_optional_fields() -> None:
    payload = {
        "schema_version": AGENT_COMPOSE_WIRE_SCHEMA_VERSION,
        "agents": [
            {
                "agent_type": "run",
                "cl_name": "minimal",
                "project_file": "/tmp/p.gp",
                "status": "RUNNING",
            }
        ],
    }

    result = composed_agent_list_from_dict(payload)
    assert result.agents == [
        AgentWire(
            agent_type="run",
            cl_name="minimal",
            project_file="/tmp/p.gp",
            status="RUNNING",
        )
    ]


def test_compose_wire_json_projection_matches_rust_tuple_shape() -> None:
    input_wire = build_agent_compose_input(
        running_claims=[
            RunningClaimWire(
                project_file="/tmp/projects/demo/demo.gp",
                project_name="demo",
                cl_name="feature_alpha",
                workflow="ace(run)",
                raw_suffix="20260429120000",
                pid=12345,
            )
        ],
        alive_pids=[12345],
        dismissed_identities=[("run", "feature_alpha", "20260429120000")],
    )

    payload = agent_compose_wire_to_json_dict(input_wire)

    assert payload["schema_version"] == AGENT_COMPOSE_WIRE_SCHEMA_VERSION
    assert payload["running_claims"][0]["pid"] == 12345
    assert payload["dismissed_identities"] == [
        ("run", "feature_alpha", "20260429120000")
    ]


def test_facade_marshals_input_and_rehydrates_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_compose(payload: dict) -> dict:
        calls.append(payload)
        return {
            "schema_version": AGENT_COMPOSE_WIRE_SCHEMA_VERSION,
            "agents": [
                {
                    "agent_type": "run",
                    "cl_name": "feature_alpha",
                    "project_file": "/tmp/projects/demo/demo.gp",
                    "status": "RUNNING",
                    "raw_suffix": "20260429120000",
                }
            ],
            "workflow_agent_steps": [],
            "dismissed_from_loader": [],
            "dropped": [],
            "merge_log": [],
        }

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.compose_agent_list = fake_compose  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    result = compose_agent_list(
        build_agent_compose_input(
            running_claims=[
                RunningClaimWire(
                    project_file="/tmp/projects/demo/demo.gp",
                    project_name="demo",
                    cl_name="feature_alpha",
                    workflow="ace(run)",
                    raw_suffix="20260429120000",
                    pid=12345,
                )
            ],
            alive_pids=[12345],
        )
    )

    assert calls[0]["running_claims"][0]["pid"] == 12345
    assert result.agents == [
        AgentWire(
            agent_type="run",
            cl_name="feature_alpha",
            project_file="/tmp/projects/demo/demo.gp",
            status="RUNNING",
            raw_suffix="20260429120000",
        )
    ]


def test_facade_missing_binding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    with pytest.raises(AttributeError, match="compose_agent_list"):
        compose_agent_list(AgentComposeInputWire())


def test_log_compose_mismatch_includes_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expected = composed_agent_list_from_dict(
        {
            "schema_version": AGENT_COMPOSE_WIRE_SCHEMA_VERSION,
            "agents": [],
            "workflow_agent_steps": [],
            "dismissed_from_loader": [],
            "dropped": [],
            "merge_log": [],
        }
    )
    actual = composed_agent_list_from_dict(
        {
            "schema_version": AGENT_COMPOSE_WIRE_SCHEMA_VERSION,
            "agents": [
                {
                    "agent_type": "run",
                    "cl_name": "feature_alpha",
                    "project_file": "/tmp/projects/demo/demo.gp",
                    "status": "RUNNING",
                }
            ],
            "workflow_agent_steps": [],
            "dismissed_from_loader": [],
            "dropped": [
                {
                    "stage": "dead_pid_filter",
                    "identity": ["run", "feature_alpha", None],
                    "reason": "dead_pid",
                    "detail": "999",
                }
            ],
            "merge_log": [],
        }
    )

    assert (
        log_compose_mismatch(label="fixture", expected=expected, actual=actual) is False
    )
    assert "dead_pid_filter" in caplog.text


def test_real_extension_composes_running_claim(tmp_path: Path) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "compose_agent_list"):
        pytest.skip("sase_core_rs is too old (no compose_agent_list).")

    project_file = tmp_path / "demo.gp"
    result = compose_agent_list(
        build_agent_compose_input(
            running_claims=[
                RunningClaimWire(
                    project_file=str(project_file),
                    project_name="demo",
                    cl_name="feature_alpha",
                    workspace_num=3,
                    workflow="ace(run)",
                    raw_suffix="20260429120000",
                    pid=12345,
                    model="gpt-test",
                )
            ],
            alive_pids=[12345],
        )
    )

    assert len(result.agents) == 1
    agent = result.agents[0]
    assert agent.agent_type == "run"
    assert agent.cl_name == "feature_alpha"
    assert agent.status == "RUNNING"
    assert agent.start_time == "2026-04-29T12:00:00"
    assert agent.workspace_num == 3
    assert agent.model == "gpt-test"
