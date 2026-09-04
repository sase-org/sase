"""JSON payload helpers for ``sase init --check --json``."""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any, TextIO

from rich.console import Console

from .init_plan import InitPlan, init_check_document, serialize_init_plan
from .init_project_scope import (
    InitProjectTarget,
    resolve_cwd_init_project_identity,
)


def _planner_check_row(plan: InitPlan) -> dict[str, Any]:
    """Serialize one planner for the JSON check payload."""
    return serialize_init_plan(plan, include_content=True, include_status=True)


def _project_check_row(
    *,
    name: str,
    display_name: str,
    status: str,
    plans: Sequence[InitPlan] = (),
    unavailable_reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Serialize one targeted project for the JSON check payload."""
    row: dict[str, Any] = {
        "name": name,
        "display_name": display_name,
        "status": status,
        "unavailable_reason": unavailable_reason,
        "planners": [_planner_check_row(plan) for plan in plans],
    }
    if error is not None:
        row["error"] = error
    return row


def target_check_row(
    target: InitProjectTarget,
    *,
    status: str,
    plans: Sequence[InitPlan] = (),
    error: str | None = None,
) -> dict[str, Any]:
    """Serialize one inventory target for the JSON check payload."""
    return _project_check_row(
        name=target.project_name,
        display_name=target.display_name,
        status=status,
        plans=plans,
        unavailable_reason=target.unavailable_reason,
        error=error,
    )


def cwd_check_row(
    plans: Sequence[InitPlan],
    *,
    status: str,
) -> dict[str, Any]:
    """Serialize the current working directory as one JSON project entry."""
    name, display_name = resolve_cwd_init_project_identity()
    return _project_check_row(
        name=name,
        display_name=display_name,
        status=status,
        plans=plans,
    )


def emit_init_check_json(
    projects: Sequence[dict[str, Any]],
    *,
    console: Console | None = None,
    file: TextIO | None = None,
) -> dict[str, Any]:
    """Write one JSON document and return it."""
    payload = init_check_document(list(projects))
    output = file
    if output is None and console is not None:
        console_file = getattr(console, "file", None)
        if console_file is not None:
            output = console_file
    if output is None:
        import sys

        output = sys.stdout
    json.dump(payload, output, indent=2, ensure_ascii=False)
    output.write("\n")
    return payload


__all__ = [
    "cwd_check_row",
    "emit_init_check_json",
    "target_check_row",
]
