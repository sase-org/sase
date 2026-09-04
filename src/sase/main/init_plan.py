"""Shared planning model for ``sase init`` onboarding."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

InitOperation = Literal["create", "update", "overwrite", "delete", "validate", "deploy"]
INIT_CHECK_JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class InitAction:
    """One planned initialization action."""

    path: Path
    operation: InitOperation
    detail: str = ""
    new_content: str | bytes | None = None


@dataclass(frozen=True)
class InitPlan:
    """Read-only plan for one ``sase init`` subcommand."""

    command: str
    label: str
    summary: str
    actions: tuple[InitAction, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    requires_tty: bool = False

    @property
    def has_changes(self) -> bool:
        """Whether this subcommand would change anything if applied."""
        return bool(self.actions)

    @property
    def runnable(self) -> bool:
        """Whether this plan can be applied."""
        return not self.blockers


def _serialize_init_action(
    action: InitAction,
    *,
    include_content: bool = False,
) -> dict[str, Any]:
    """Serialize one planned action.

    ``include_content`` adds ``new_content`` so a consumer can render a unified
    diff without a second planning pass. Binary payloads are base64-encoded.
    """
    row: dict[str, Any] = {
        "path": str(action.path),
        "operation": action.operation,
        "detail": action.detail,
    }
    if not include_content:
        return row
    if isinstance(action.new_content, bytes):
        row["new_content"] = base64.standard_b64encode(action.new_content).decode(
            "ascii"
        )
        row["new_content_encoding"] = "base64"
    else:
        row["new_content"] = action.new_content
    return row


def serialize_init_plan(
    plan: InitPlan,
    *,
    max_actions: int | None = None,
    include_content: bool = False,
    include_status: bool = False,
) -> dict[str, Any]:
    """Serialize one ``InitPlan``.

    Action lists are never truncated silently: pass ``max_actions`` to cap the
    emitted actions, and the row then includes ``actions_truncated`` plus the
    full ``action_count``.
    """
    actions = plan.actions
    truncated = False
    if max_actions is not None and len(actions) > max_actions:
        actions = actions[:max_actions]
        truncated = True
    row: dict[str, Any] = {
        "name": plan.command,
        "label": plan.label,
        "summary": plan.summary,
        "actions": [
            _serialize_init_action(action, include_content=include_content)
            for action in actions
        ],
        "action_count": len(plan.actions),
        "warnings": list(plan.warnings),
        "blockers": list(plan.blockers),
    }
    if include_status:
        row["has_changes"] = plan.has_changes
        row["runnable"] = plan.runnable
        row["requires_tty"] = plan.requires_tty
    if truncated:
        row["actions_truncated"] = True
    return row


def _project_is_blocked(project: dict[str, Any]) -> bool:
    if project.get("unavailable_reason") or project.get("error"):
        return True
    if project.get("status") in {"failed", "cancelled"}:
        return True
    return any(
        not planner.get("runnable", True) for planner in project.get("planners", [])
    )


def _project_has_drift(project: dict[str, Any]) -> bool:
    if project.get("status") == "needs_attention":
        return True
    return any(planner.get("has_changes") for planner in project.get("planners", []))


def _aggregate_init_check_status(
    projects: list[dict[str, Any]],
) -> Literal["current", "drift", "blocked"]:
    """Return the top-level check status for a multi-project payload."""
    if any(_project_is_blocked(project) for project in projects):
        return "blocked"
    if any(_project_has_drift(project) for project in projects):
        return "drift"
    return "current"


def init_check_document(projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Return one schema-versioned ``sase init --check --json`` document."""
    return {
        "schema_version": INIT_CHECK_JSON_SCHEMA_VERSION,
        "status": _aggregate_init_check_status(projects),
        "projects": projects,
    }


__all__ = [
    "INIT_CHECK_JSON_SCHEMA_VERSION",
    "InitAction",
    "InitOperation",
    "InitPlan",
    "init_check_document",
    "serialize_init_plan",
]
