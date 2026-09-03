"""Shared planning model for ``sase init`` onboarding."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

InitOperation = Literal["create", "update", "overwrite", "delete", "validate", "deploy"]
InitCheckStatus = Literal["current", "drift", "blocked"]

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
    actions: tuple[InitAction, ...] = ()
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
    """Serialize one planned action for doctor or ``--check --json``."""
    payload: dict[str, Any] = {
        "path": str(action.path),
        "operation": action.operation,
        "detail": action.detail,
    }
    if not include_content:
        return payload
    if isinstance(action.new_content, bytes):
        payload["new_content"] = base64.standard_b64encode(action.new_content).decode(
            "ascii"
        )
        payload["content_encoding"] = "base64"
    elif isinstance(action.new_content, str):
        payload["new_content"] = action.new_content
        payload["content_encoding"] = "utf-8"
    else:
        payload["new_content"] = None
    return payload


def serialize_init_plan(
    plan: InitPlan,
    *,
    max_actions: int | None = None,
    include_content: bool = False,
    include_run_fields: bool = False,
) -> dict[str, Any]:
    """Serialize one planner row.

    ``max_actions`` caps the emitted action list. The full count is always in
    ``action_count``; when a cap actually drops actions the row also carries
    ``truncated: true`` so consumers never see a silent slice.
    """
    actions = plan.actions
    truncated = False
    if max_actions is not None and len(actions) > max_actions:
        actions = actions[:max_actions]
        truncated = True
    payload: dict[str, Any] = {
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
    if truncated:
        payload["truncated"] = True
    if include_run_fields:
        payload["has_changes"] = plan.has_changes
        payload["runnable"] = plan.runnable
        payload["requires_tty"] = plan.requires_tty
    return payload


__all__ = [
    "INIT_CHECK_JSON_SCHEMA_VERSION",
    "InitAction",
    "InitCheckStatus",
    "InitOperation",
    "InitPlan",
    "serialize_init_plan",
]
