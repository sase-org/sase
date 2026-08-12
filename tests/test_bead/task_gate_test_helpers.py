"""Shared helpers for trusted TaskTriage gate tests."""

from __future__ import annotations

from typing import Any

from sase.bead._task_gate_spec import build_task_triage_gate_spec


def task_triage_spec(
    *, request_id: str = "task-triage-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "description": "Make invalidation deterministic.",
        "notes": "Discovered while landing sase-bg.",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "producer": {"agent_name": "triage-test"},
    }
    fields.update(overrides)
    return build_task_triage_gate_spec(**fields)
