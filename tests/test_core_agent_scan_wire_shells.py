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
                        "family_shell": {
                            "kind": "gate",
                            "id": "gate-1",
                            "state": "pending",
                            "start_status": "WAITING",
                            "stop_status": "ANSWERED",
                            "output_path": "gate.out",
                            "output_truncated": True,
                            "followup_agent": "acme--1",
                            "next_action": "Resume after gate.",
                            "next_output": "summary",
                            "next_model": "@large",
                            "followup_outcome": "launched",
                            "followup_error": "claim moved late",
                            "followup_degraded_reason": "workspace unavailable",
                            "followup_prompt_path": "gate_followup.md",
                            "elapsed_seconds": 2.5,
                            "label": "approval/gate-1",
                            "reason": "Need owner approval",
                            "timeout_seconds": 600.0,
                            "request_fingerprint": "sha256:cafe",
                            "gate": {
                                "kind": "approval",
                                "accent": "#0BCDEC",
                                "creator_agent": "acme--0",
                                "next_fork": "family",
                                "workspace_policy": "inherit",
                                "bundle_path": "gate_bundle.json",
                                "notification_id": "notif-1",
                                "decision_path": "gate_decision.md",
                            },
                        },
                        "shell_kind": "gate",
                        "proc_id": "proc-gate",
                    },
                    "done": {
                        "outcome": "gated",
                        "family_shell": {
                            "kind": "gate",
                            "id": "gate-1",
                            "state": "answered",
                            "elapsed_seconds": 2.5,
                            "output_path": "gate.out",
                            "output_truncated": True,
                            "followup_outcome": "launched",
                            "followup_error": "claim moved late",
                            "followup_degraded_reason": "workspace unavailable",
                            "followup_prompt_path": "gate_followup.md",
                            "gate": {
                                "kind": "approval",
                                "bundle_path": "gate_bundle.json",
                                "notification_id": "notif-1",
                            },
                        },
                        "status_label": "ANSWERED",
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
    meta_shell = record.agent_meta.family_shell
    assert meta_shell is not None
    assert meta_shell.id == "gate-1"
    assert meta_shell.next_model == "@large"
    assert meta_shell.output_truncated is True
    assert meta_shell.gate is not None
    assert meta_shell.gate.decision_path == "gate_decision.md"
    done_shell = record.done.family_shell
    assert done_shell is not None
    assert done_shell.state == "answered"
    assert done_shell.elapsed_seconds == 2.5
    assert done_shell.output_truncated is True

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]["family_shell"]
    done_payload = payload["records"][0]["done"]["family_shell"]
    assert meta_payload["request_fingerprint"] == "sha256:cafe"
    assert meta_payload["gate"]["decision_path"] == "gate_decision.md"
    assert done_payload["gate"]["notification_id"] == "notif-1"
    assert done_payload["followup_prompt_path"] == "gate_followup.md"


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
                        "family_shell": {
                            "kind": "monitor",
                            "id": "m4kq",
                            "label": "just check-full",
                            "reason": "Verify the refactor",
                            "next_action": "Reply to the user.",
                            "start_status": "MONITORING",
                            "stop_status": "MONITORED",
                            "timeout_seconds": 2700.0,
                            "state": "running",
                            "output_path": "live_reply.md",
                            "output_truncated": True,
                            "next_output": "tail",
                            "next_model": "@small",
                            "request_fingerprint": "sha256:deadbeef",
                            "monitor": {
                                "command": "just check-full",
                                "cwd": "/home/bryan/workspaces/acme",
                                "starter_agent": "acme--0",
                                "tail_lines": 200,
                                "pgid": 4242,
                                "supervisor_identity": "boot-abc123:98765",
                                "settled": True,
                                "idle_timeout_seconds": 600.0,
                            },
                        },
                    },
                    done={
                        "outcome": "monitored",
                        "family_shell": {
                            "kind": "monitor",
                            "state": "completed",
                            "elapsed_seconds": 17.5,
                            "monitor": {"exit_code": 0},
                        },
                        "status_label": "MONITORED",
                    },
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    meta_shell = record.agent_meta.family_shell
    assert meta_shell is not None
    assert meta_shell.start_status == "MONITORING"
    assert meta_shell.stop_status == "MONITORED"
    assert meta_shell.id == "m4kq"
    assert meta_shell.state == "running"
    assert meta_shell.output_truncated is True
    assert meta_shell.request_fingerprint == "sha256:deadbeef"
    assert meta_shell.monitor is not None
    assert meta_shell.monitor.command == "just check-full"
    assert meta_shell.monitor.tail_lines == 200
    assert meta_shell.monitor.pgid == 4242
    assert meta_shell.monitor.supervisor_identity == "boot-abc123:98765"
    assert meta_shell.monitor.settled is True
    assert meta_shell.monitor.idle_timeout_seconds == 600.0
    assert record.done is not None
    done_shell = record.done.family_shell
    assert done_shell is not None
    assert done_shell.state == "completed"
    assert done_shell.elapsed_seconds == 17.5
    assert done_shell.monitor is not None
    assert done_shell.monitor.exit_code == 0
    assert record.done.status_label == "MONITORED"

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]["family_shell"]
    assert meta_payload["id"] == "m4kq"
    assert meta_payload["state"] == "running"
    assert meta_payload["monitor"]["pgid"] == 4242
    assert meta_payload["monitor"]["supervisor_identity"] == "boot-abc123:98765"
    assert meta_payload["monitor"]["settled"] is True
    assert meta_payload["monitor"]["idle_timeout_seconds"] == 600.0
    assert meta_payload["next_output"] == "tail"
    assert meta_payload["next_model"] == "@small"
    assert meta_payload["request_fingerprint"] == "sha256:deadbeef"
    done_payload = payload["records"][0]["done"]
    assert done_payload["family_shell"]["state"] == "completed"
    assert done_payload["status_label"] == "MONITORED"
    assert meta_payload["start_status"] == "MONITORING"
    assert meta_payload["stop_status"] == "MONITORED"


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
                        "family_shell": {
                            "kind": "monitor",
                            "id": "m4kq",
                            "start_status": "TESTING",
                            "stop_status": "TESTED",
                            "state": "completed",
                        },
                    },
                    done={
                        "outcome": "monitored",
                        "family_shell": {"kind": "monitor", "state": "completed"},
                        "status_label": "TESTED",
                    },
                )
            ],
        }
    )

    record = snapshot.records[0]
    assert record.agent_meta is not None
    meta_shell = record.agent_meta.family_shell
    assert meta_shell is not None
    assert meta_shell.start_status == "TESTING"
    assert meta_shell.stop_status == "TESTED"
    assert record.done is not None
    assert record.done.status_label == "TESTED"

    payload = agent_scan_wire_to_json_dict(snapshot)
    meta_payload = payload["records"][0]["agent_meta"]["family_shell"]
    assert meta_payload["start_status"] == "TESTING"
    assert meta_payload["stop_status"] == "TESTED"
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
    assert record.agent_meta.family_shell is None
    assert record.done is not None
    assert record.done.family_shell is None
    assert record.done.status_label is None
