"""Gate row projection tests for TUI loaders."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._loaders._done_loaders import (
    _load_done_agent_for_dir,
    load_done_agents_from_snapshot,
)
from sase.ace.tui.models._loaders._meta_enrichment_filesystem import (
    enrich_agent_from_meta,
)
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.status_buckets import agent_status_bucket
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)


def _base_agent(*, status: str = "STARTING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gate-row",
        project_file="/tmp/gate.sase",
        status=status,
        start_time=datetime(2026, 8, 12, 9, 0, 0),
        raw_suffix="20260812090000",
    )


def test_settling_gate_meta_projects_start_label_and_bucket() -> None:
    agent = _base_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--gate",
            gate_id="g123",
            gate_kind="approval",
            gate_state="settling",
            gate_start_status="APPROVE",
            gate_stop_status="APPROVED",
            gate_accent="#0BCDEC",
            gate_label="Approve deploy",
            gate_reason="Release needs confirmation",
            gate_timeout_seconds=120.0,
            run_started_at="2026-08-12T13:00:00Z",
            agent_family="alpha",
            agent_family_role="gate",
            role_suffix="--gate",
        ),
        waiting=None,
    )

    assert agent.is_gate is True
    assert agent.status == "APPROVE"
    assert agent.status_bucket == "Running"
    assert agent.gate_kind == "approval"
    assert agent.gate_label == "Approve deploy"
    assert agent.gate_reason == "Release needs confirmation"
    assert agent.gate_timeout_seconds == 120.0


def test_gate_starter_keeps_reference_without_gate_row_semantics() -> None:
    agent = _base_agent(status="DONE")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--0",
            gate_id="g123",
            gate_kind="approval",
            gate_state="pending",
            gate_start_status="APPROVE",
            gate_stop_status="APPROVED",
            agent_family="alpha",
            agent_family_role="root",
            role_suffix="--0",
            stopped_at="2026-08-12T13:03:00Z",
        ),
        waiting=None,
    )

    assert agent.gate_id == "g123"
    assert agent.is_gate is False
    assert agent.status == "DONE"
    assert agent.status_bucket != "Running"
    assert agent_status_bucket(agent) == "Done"


def test_filesystem_gate_meta_projects_detail_fields(tmp_path: Path) -> None:
    output = tmp_path / "gate.log"
    output.write_text("gate output\n", encoding="utf-8")
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "alpha--gate",
                "gate_id": "g123",
                "gate_kind": "approval",
                "gate_state": "pending",
                "gate_start_status": "APPROVE",
                "gate_stop_status": "APPROVED",
                "gate_output_path": str(output),
                "gate_output_truncated": True,
                "gate_creator_agent": "alpha--0",
                "gate_next_action": "Continue after approval.",
                "gate_next_fork": "family",
                "gate_next_output": "results,tail",
                "gate_next_model": "gpt-5",
                "gate_elapsed_seconds": 12.5,
                "gate_workspace_policy": "inherit",
                "gate_bundle_path": str(tmp_path / "bundle"),
                "gate_notification_id": "n123",
                "gate_decision_path": str(tmp_path / "gate_decision.md"),
                "agent_family": "alpha",
                "agent_family_role": "gate",
                "role_suffix": "--gate",
            }
        ),
        encoding="utf-8",
    )
    agent = _base_agent()

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.is_gate is True
    assert agent.status == "APPROVE"
    assert agent.status_bucket == "Stopped"
    assert agent.gate_output_path == str(output)
    assert agent.gate_output_truncated is True
    assert agent.gate_creator_agent == "alpha--0"
    assert agent.gate_next_action == "Continue after approval."
    assert agent.gate_next_output == "results,tail"
    assert agent.gate_elapsed_seconds == 12.5
    assert agent.gate_notification_id == "n123"
    assert agent.get_live_reply_content() == "gate output\n"


def test_terminal_gate_done_projects_stop_label_and_followup_fields() -> None:
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="sase",
                project_dir="/tmp/.sase/projects/sase",
                project_file="/tmp/.sase/projects/sase/sase.sase",
                workflow_dir_name="ace-run",
                artifact_dir="/tmp/.sase/projects/sase/artifacts/ace-run/20260812090000",
                timestamp="20260812090000",
                agent_meta=AgentMetaWire(
                    name="alpha--gate",
                    gate_id="g123",
                    gate_kind="approval",
                    gate_state="settling",
                    gate_start_status="APPROVE",
                    gate_stop_status="APPROVED",
                    run_started_at="2026-08-12T13:00:00Z",
                    stopped_at="2026-08-12T13:03:00Z",
                    agent_family="alpha",
                    agent_family_role="gate",
                    role_suffix="--gate",
                ),
                done=DoneMarkerWire(
                    outcome="gated",
                    cl_name="gate-row",
                    project_file="/tmp/.sase/projects/sase/sase.sase",
                    gate_id="g123",
                    gate_kind="approval",
                    gate_state="failed",
                    gate_elapsed_seconds=180.0,
                    gate_output_path="/tmp/gate.log",
                    gate_output_truncated=True,
                    gate_bundle_path="/tmp/gate-bundle",
                    gate_notification_id="n123",
                    gate_followup_outcome="not-launchable",
                    gate_followup_error="no branch selected",
                    gate_followup_degraded_reason="workspace unavailable",
                    gate_followup_prompt_path="/tmp/followup.md",
                    status_label="REVIEWED",
                ),
                has_done_marker=True,
            )
        ],
    )

    (agent,) = load_done_agents_from_snapshot(snapshot, {}, {})

    assert agent.is_gate is True
    assert agent.status == "REVIEWED"
    assert agent.status_bucket == "Failed"
    assert agent.gate_state == "failed"
    assert agent.gate_stop_status == "REVIEWED"
    assert agent.gate_elapsed_seconds == 180.0
    assert agent.gate_output_path == "/tmp/gate.log"
    assert agent.gate_output_truncated is True
    assert agent.gate_followup_error == "no branch selected"
    assert agent.gate_followup_prompt_path == "/tmp/followup.md"


def test_filesystem_done_gate_row_projects_custom_stop_status(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260812090000"
    artifact_dir.mkdir()
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "alpha--gate",
                "gate_id": "g123",
                "gate_state": "settling",
                "gate_start_status": "APPROVE",
                "gate_stop_status": "APPROVED",
                "agent_family": "alpha",
                "agent_family_role": "gate",
                "role_suffix": "--gate",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "gate-row",
                "outcome": "gated",
                "project_file": "/tmp/gate.sase",
                "gate_id": "g123",
                "gate_state": "answered",
                "status_label": "APPROVED",
            }
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.is_gate is True
    assert agent.status == "APPROVED"
    assert agent.gate_stop_status == "APPROVED"
    assert agent.gate_state == "answered"
