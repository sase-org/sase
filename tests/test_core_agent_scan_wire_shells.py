from __future__ import annotations

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)

from .core_agent_scan_wire_helpers import record_payload


def test_gate_shell_marker_fields_round_trip() -> None:
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                {
                    "project_name": "myproj",
                    "project_dir": "/tmp/projects/myproj",
                    "project_file": "/tmp/projects/myproj/myproj.sase",
                    "workflow_dir_name": "ace-run",
                    "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/gate",
                    "timestamp": "gate",
                    "agent_meta": {
                        "name": "acme--gate",
                        "agent_family": "acme",
                        "agent_family_role": "gate",
                        "gate_id": "gate-1",
                        "gate_kind": "approval",
                        "gate_state": "pending",
                        "gate_start_status": "WAITING",
                        "gate_stop_status": "ANSWERED",
                        "gate_accent": "#0BCDEC",
                        "gate_output_path": "gate.out",
                        "gate_output_truncated": True,
                        "gate_creator_agent": "acme--0",
                        "gate_followup_agent": "acme--1",
                        "gate_next_action": "Resume after gate.",
                        "gate_next_fork": "family",
                        "gate_next_output": "summary",
                        "gate_next_model": "@large",
                        "gate_followup_outcome": "launched",
                        "gate_followup_error": "claim moved late",
                        "gate_followup_degraded_reason": "workspace unavailable",
                        "gate_followup_prompt_path": "gate_followup.md",
                        "gate_elapsed_seconds": 2.5,
                        "gate_label": "approval/gate-1",
                        "gate_reason": "Need owner approval",
                        "gate_timeout_seconds": 600.0,
                        "gate_request_fingerprint": "sha256:cafe",
                        "gate_workspace_policy": "inherit",
                        "gate_bundle_path": "gate_bundle.json",
                        "gate_notification_id": "notif-1",
                        "gate_decision_path": "gate_decision.md",
                        "shell_kind": "gate",
                        "proc_id": "proc-gate",
                    },
                    "done": {
                        "outcome": "gated",
                        "gate_id": "gate-1",
                        "gate_kind": "approval",
                        "gate_state": "answered",
                        "gate_elapsed_seconds": 2.5,
                        "status_label": "ANSWERED",
                        "gate_output_path": "gate.out",
                        "gate_output_truncated": True,
                        "gate_bundle_path": "gate_bundle.json",
                        "gate_notification_id": "notif-1",
                        "gate_followup_outcome": "launched",
                        "gate_followup_error": "claim moved late",
                        "gate_followup_degraded_reason": "workspace unavailable",
                        "gate_followup_prompt_path": "gate_followup.md",
                    },
                    "running": None,
                    "waiting": None,
                    "pending_question": None,
                    "workflow_state": None,
                    "plan_path": None,
                    "prompt_steps": [],
                    "raw_prompt_snippet": None,
                    "has_done_marker": True,
                }
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.done is not None
    assert record.agent_meta.gate_id == "gate-1"
    assert record.agent_meta.gate_next_model == "@large"
    assert record.agent_meta.gate_output_truncated is True
    assert record.agent_meta.gate_decision_path == "gate_decision.md"
    assert record.done.gate_state == "answered"
    assert record.done.gate_elapsed_seconds == 2.5
    assert record.done.gate_output_truncated is True
    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]
    done_payload = payload["records"][0]["done"]
    assert meta_payload["gate_request_fingerprint"] == "sha256:cafe"
    assert meta_payload["gate_decision_path"] == "gate_decision.md"
    assert done_payload["gate_notification_id"] == "notif-1"
    assert done_payload["gate_followup_prompt_path"] == "gate_followup.md"


def test_monitor_marker_fields_round_trip() -> None:
    """Monitor family members must survive the agent artifact scan."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                record_payload(
                    agent_meta={
                        "name": "acme--mon",
                        "agent_family": "acme",
                        "agent_family_role": "monitor",
                        "monitor_id": "m4kq",
                        "monitor_command": "just check-full",
                        "monitor_cwd": "/home/bryan/workspaces/acme",
                        "monitor_label": "just check-full",
                        "monitor_reason": "Verify the refactor",
                        "monitor_next_action": "Reply to the user.",
                        "monitor_start_status": "MONITORING",
                        "monitor_stop_status": "MONITORED",
                        "monitor_timeout_seconds": 2700.0,
                        "monitor_state": "running",
                        "monitor_exit_code": None,
                        "monitor_output_path": "live_reply.md",
                        "monitor_output_truncated": True,
                        "monitor_starter_agent": "acme--0",
                        "monitor_followup_agent": None,
                        "monitor_tail_lines": 200,
                        "monitor_pgid": 4242,
                        "monitor_supervisor_identity": "boot-abc123:98765",
                        "monitor_settled": True,
                        "monitor_idle_timeout_seconds": 600.0,
                        "monitor_next_output": "tail",
                        "monitor_next_model": "@small",
                        "monitor_request_fingerprint": "sha256:deadbeef",
                    },
                    done={
                        "outcome": "monitored",
                        "monitor_state": "completed",
                        "monitor_exit_code": 0,
                        "monitor_elapsed_seconds": 17.5,
                        "status_label": "MONITORED",
                    },
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.monitor_start_status == "MONITORING"
    assert record.agent_meta.monitor_stop_status == "MONITORED"
    assert record.agent_meta.monitor_id == "m4kq"
    assert record.agent_meta.monitor_command == "just check-full"
    assert record.agent_meta.monitor_state == "running"
    assert record.agent_meta.monitor_output_truncated is True
    assert record.agent_meta.monitor_tail_lines == 200
    assert record.agent_meta.monitor_pgid == 4242
    assert record.agent_meta.monitor_supervisor_identity == "boot-abc123:98765"
    assert record.agent_meta.monitor_settled is True
    assert record.agent_meta.monitor_idle_timeout_seconds == 600.0
    assert record.agent_meta.monitor_next_output == "tail"
    assert record.agent_meta.monitor_next_model == "@small"
    assert record.agent_meta.monitor_request_fingerprint == "sha256:deadbeef"
    assert record.done is not None
    assert record.done.monitor_state == "completed"
    assert record.done.monitor_exit_code == 0
    assert record.done.monitor_elapsed_seconds == 17.5
    assert record.done.status_label == "MONITORED"

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]
    assert meta_payload["monitor_id"] == "m4kq"
    assert meta_payload["monitor_state"] == "running"
    assert meta_payload["monitor_pgid"] == 4242
    assert meta_payload["monitor_supervisor_identity"] == "boot-abc123:98765"
    assert meta_payload["monitor_settled"] is True
    assert meta_payload["monitor_idle_timeout_seconds"] == 600.0
    assert meta_payload["monitor_next_output"] == "tail"
    assert meta_payload["monitor_next_model"] == "@small"
    assert meta_payload["monitor_request_fingerprint"] == "sha256:deadbeef"
    done_payload = payload["records"][0]["done"]
    assert done_payload["monitor_state"] == "completed"
    assert done_payload["status_label"] == "MONITORED"
    assert meta_payload["monitor_start_status"] == "MONITORING"
    assert meta_payload["monitor_stop_status"] == "MONITORED"


def test_monitor_custom_stop_status_round_trips() -> None:
    """A custom stop label must survive the agent artifact scan."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                record_payload(
                    agent_meta={
                        "name": "acme--mon",
                        "agent_family": "acme",
                        "agent_family_role": "monitor",
                        "monitor_id": "m4kq",
                        "monitor_start_status": "TESTING",
                        "monitor_stop_status": "TESTED",
                        "monitor_state": "completed",
                    },
                    done={
                        "outcome": "monitored",
                        "monitor_state": "completed",
                        "status_label": "TESTED",
                    },
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.monitor_start_status == "TESTING"
    assert record.agent_meta.monitor_stop_status == "TESTED"
    assert record.done is not None
    assert record.done.status_label == "TESTED"

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]
    assert meta_payload["monitor_start_status"] == "TESTING"
    assert meta_payload["monitor_stop_status"] == "TESTED"
    assert payload["records"][0]["done"]["status_label"] == "TESTED"


def test_monitor_marker_fields_default_for_older_records() -> None:
    """A record from a pre-monitor core/agent must still parse cleanly."""
    snapshot = agent_scan_wire_from_dict(
        {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": "/tmp/projects",
            "options": {},
            "stats": {},
            "records": [
                record_payload(
                    agent_meta={"name": "pre-monitor-agent"},
                    done={"outcome": "completed", "cl_name": "myproj"},
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.monitor_id is None
    assert record.agent_meta.monitor_state is None
    assert record.agent_meta.monitor_output_truncated is False
    assert record.agent_meta.monitor_pgid is None
    assert record.agent_meta.monitor_supervisor_identity is None
    assert record.agent_meta.monitor_settled is False
    assert record.agent_meta.monitor_idle_timeout_seconds is None
    assert record.agent_meta.monitor_next_output is None
    assert record.agent_meta.monitor_next_model is None
    assert record.agent_meta.monitor_request_fingerprint is None
    assert record.done is not None
    assert record.done.monitor_state is None
    assert record.done.monitor_exit_code is None
    assert record.done.status_label is None
