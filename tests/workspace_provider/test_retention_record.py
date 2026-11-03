"""Producer-to-consumer coverage for the terminal retention-record contract."""

from __future__ import annotations

import json
from pathlib import Path

from sase.workspace_provider.retention_record import (
    WorkspaceRetentionRecord,
    mark_workspace_retention_settled,
    read_workspace_retention_record,
    workspace_retention_lines,
)


def _record(**payload: object) -> WorkspaceRetentionRecord:
    body: dict[str, object] = {
        "kind": "terminal_workspace_retention",
        "disposition": "retain",
        "workspace_num": 17,
        "workspace_dir": "/work/held",
        "workflow": "ace-monitor",
        "terminal_reason": "failed",
        "turn_id": "abc123def456",
    }
    body.update(payload)
    return WorkspaceRetentionRecord(path="/tmp/retention.json", payload=body)


def test_stopped_and_lost_monitors_do_not_suggest_resume() -> None:
    for state in ("stopped", "lost", "running"):
        lines = workspace_retention_lines(
            _record(monitor_state=state, turn_id="abc123")
        )
        joined = "\n".join(lines)
        assert "sase monitor resume" not in joined
        assert "Dismiss this agent to release the workspace." in joined


def test_eligible_failed_monitor_names_resume_command() -> None:
    lines = workspace_retention_lines(
        _record(
            monitor_state="failed",
            monitor_next_action="Report the result.",
            turn_id="abc123def456",
        )
    )
    assert any("sase monitor resume abc123def456" in line for line in lines)
    assert any("dismiss this agent" in line for line in lines)


def test_fire_and_forget_monitor_does_not_suggest_resume() -> None:
    lines = workspace_retention_lines(
        _record(monitor_state="completed", monitor_next_action="", turn_id="abc123")
    )
    assert "sase monitor resume" not in "\n".join(lines)


def test_staged_hold_names_readopt_when_origin_is_known() -> None:
    lines = workspace_retention_lines(
        _record(
            workflow="ace-run",
            staged_id="stage-1",
            origin_agent_name="review--plan",
            turn_id=None,
        )
    )
    assert any("sase agent readopt review--plan" in line for line in lines)
    assert "sase monitor resume" not in "\n".join(lines)


def test_mark_settled_writes_shared_field_contract(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    path = artifacts / "diagnostics" / "workspace_retention.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "kind": "terminal_workspace_retention",
                "disposition": "retain",
                "workspace_num": 17,
            }
        ),
        encoding="utf-8",
    )

    assert (
        mark_workspace_retention_settled(
            artifacts,
            reason="resume_transfer",
            settled_at="2026-11-02T00:00:00+00:00",
            extra={"resumed_to": "acme--mon@1"},
        )
        is True
    )
    record = read_workspace_retention_record(artifacts)
    assert record is not None
    assert record.unresolved is False
    assert record.payload["settled_at"] == "2026-11-02T00:00:00+00:00"
    assert record.payload["settled_reason"] == "resume_transfer"
    assert record.payload["settled"] is True
    assert record.payload["settled_via"] == "resume_transfer"
    assert record.payload["resumed_to"] == "acme--mon@1"
    assert (
        mark_workspace_retention_settled(
            artifacts, reason="dismissed", settled_at="2026-11-02T01:00:00+00:00"
        )
        is False
    )
