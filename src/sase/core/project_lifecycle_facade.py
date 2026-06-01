"""Python facade for Rust-backed ProjectSpec lifecycle helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectLifecycleWire,
    ProjectRecordWire,
    project_lifecycle_from_dict,
    project_record_from_dict,
)
from sase.core.rust import require_rust_binding


def read_project_lifecycle_from_content(content: str) -> ProjectLifecycleWire:
    """Parse effective ProjectSpec lifecycle state via ``sase_core_rs``."""

    binding = require_rust_binding("read_project_lifecycle_from_content")
    payload: dict[str, Any] = binding(content)
    return project_lifecycle_from_dict(dict(payload))


def apply_project_lifecycle_update(content: str, state: str) -> str:
    """Return ProjectSpec content with ``PROJECT_STATE`` updated by Rust."""

    binding = require_rust_binding("apply_project_lifecycle_update")
    return binding(content, state)  # type: ignore[no-any-return]


def list_project_records(
    projects_root: Path | str,
    include_states: Sequence[str] | str = ("active",),
    *,
    include_home: bool = False,
) -> list[ProjectRecordWire]:
    """List lifecycle records under a projects root via ``sase_core_rs``."""

    if include_states == "all":
        states = list(PROJECT_LIFECYCLE_STATES)
    else:
        states = (
            [include_states]
            if isinstance(include_states, str)
            else list(include_states)
        )
    binding = require_rust_binding("list_project_records")
    payload: list[dict[str, Any]] = binding(str(projects_root), states, include_home)
    return [project_record_from_dict(dict(item)) for item in payload]


__all__ = [
    "ProjectLifecycleWire",
    "ProjectRecordWire",
    "apply_project_lifecycle_update",
    "list_project_records",
    "read_project_lifecycle_from_content",
]
