"""Shared helpers for trusted FlagTriage gate tests."""

from __future__ import annotations

from typing import Any

from sase.bead._flag_gate_spec import build_flag_triage_gate_spec
from sase.bead.flag_fields import FLAG_TASK_TYPE
from sase.bead.model import FlagRecord


def flag_triage_spec(
    *, request_id: str = "flag-triage-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": "sase-flag.1",
        "project": "sase",
        "title": "Remove the prettier_enabled flag",
        "flag": FlagRecord(
            key="prettier_enabled",
            remove_by_date="2026-08-01",
            remove_by_release="0.16.0",
        ),
        "kind": "sunset",
        "due_state": "due",
        "due_as_of": "2026-08-16",
        "release": "0.16.0",
        "definition": {"kind": "sunset", "description": "Routes prettier formatting."},
        "description": "Roll out the new formatter by default.",
        "notes": "Discovered while landing sase-bg.",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "task_type": FLAG_TASK_TYPE,
        "task_type_fields": {
            "key": "prettier_enabled",
            "kind": "sunset",
            "when_enabled": "Markdown is formatted with prettier when it is installed.",
            "when_disabled": "Markdown formatting skips prettier entirely.",
            "remove_when": "No workflow still needs a prettier escape hatch.",
            "remove_by_date": "2026-08-01",
            "remove_by_release": "0.16.0",
        },
        "producer": {"agent_name": "flag-triage-test"},
    }
    fields.update(overrides)
    return build_flag_triage_gate_spec(**fields)
