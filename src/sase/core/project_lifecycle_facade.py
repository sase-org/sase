"""Python facade for Rust-backed ProjectSpec lifecycle helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_wire import (
    ProjectLifecycleWire,
    ProjectRecordWire,
    normalize_project_lifecycle_state_filter,
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


def apply_project_aliases_update(content: str, aliases: Sequence[str]) -> str:
    """Return ProjectSpec content with ``PROJECT_ALIASES`` updated by Rust."""

    binding = require_rust_binding("apply_project_aliases_update")
    return binding(content, list(aliases))  # type: ignore[no-any-return]


def apply_project_name_update(content: str, name: str | None) -> str:
    """Return ProjectSpec content with ``PROJECT_NAME`` updated by Rust."""

    binding = require_rust_binding("apply_project_name_update")
    return binding(content, name)  # type: ignore[no-any-return]


def list_project_records(
    projects_root: Path | str,
    include_states: Sequence[str] | str = ("enabled",),
    *,
    include_home: bool = False,
    projects_only: bool = False,
) -> list[ProjectRecordWire]:
    """List lifecycle records under a projects root via ``sase_core_rs``."""

    states = normalize_project_lifecycle_state_filter(include_states)
    binding = require_rust_binding("list_project_records")
    if projects_only:
        payload: list[dict[str, Any]] = binding(
            str(projects_root), states, include_home, True
        )
    else:
        payload = binding(str(projects_root), states, include_home)
    return [
        project_record_from_dict(dict(item))
        for item in payload
        if is_valid_sase_project_name(str(item.get("project_name", "")))
    ]


__all__ = [
    "ProjectLifecycleWire",
    "ProjectRecordWire",
    "apply_project_aliases_update",
    "apply_project_lifecycle_update",
    "apply_project_name_update",
    "list_project_records",
    "read_project_lifecycle_from_content",
]
