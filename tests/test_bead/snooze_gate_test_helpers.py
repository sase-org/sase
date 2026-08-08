"""Shared helpers for trusted BeadSnooze gate tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from sase.bead.model import SnoozeRecord
from sase.bead.snooze_gate import (
    BEAD_SNOOZE_PREVIEW_PATH,
    _build_bead_snooze_gate_spec,
)

WAKE_TIME = "2026-08-09T09:00:00-04:00"


def snooze_record(**overrides: Any) -> SnoozeRecord:
    fields: dict[str, Any] = {
        "until": WAKE_TIME,
        "snoozed_at": "2026-08-06T09:00:00-04:00",
        "snoozed_by": "bryanbugyi34@gmail.com",
        "reason": "waiting on the upstream fix",
    }
    fields.update(overrides)
    return SnoozeRecord(**fields)


def bead_snooze_spec(
    *, request_id: str = "bead-snooze-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "snooze": snooze_record(),
        "description": "Make invalidation deterministic.",
        "notes": "Discovered while landing sase-bg.",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "producer": {"agent_name": "snooze-test"},
    }
    fields.update(overrides)
    return _build_bead_snooze_gate_spec(**fields)


def preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == BEAD_SNOOZE_PREVIEW_PATH
    )


def mutation_double() -> tuple[MagicMock, Any, Any]:
    """Return a bead-store mutation double and the scope that yields it."""
    project = MagicMock()
    project.owner = "owner@example"
    project.last_mutation_outcome = {
        "closed_ids": ["sase-task.1"],
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    return project, mutation, mutation_scope
