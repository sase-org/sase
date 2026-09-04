"""Typed mirrors of ``sase init --check --json`` plus derived predicates.

Everything here runs on a worker thread. Do not import Textual.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sase.core.time import local_now
from sase.main.init_plan import INIT_CHECK_JSON_SCHEMA_VERSION

InitCheckStatus = Literal["current", "drift", "blocked"]
_KNOWN_CHECK_STATUSES: frozenset[str] = frozenset(("current", "drift", "blocked"))
_TAIL_LINES = 10
_TAIL_CHARS = 600


class InitCheckPayloadError(ValueError):
    """The captured check output could not be parsed as a supported payload."""


@dataclass(frozen=True, slots=True)
class InitActionRow:
    """One planned action, with diffs filled in after ``attach_action_diffs``."""

    path: str
    operation: str
    detail: str = ""
    added: int = 0
    removed: int = 0
    diff_lines: tuple[str, ...] = ()
    diff_note: str | None = None
    new_content: str | None = None
    new_content_encoding: str | None = None


@dataclass(frozen=True, slots=True)
class InitPlannerRow:
    """One planner (config / memory / repo / skills) in a check payload."""

    name: str
    label: str
    summary: str
    has_changes: bool = False
    runnable: bool = True
    requires_tty: bool = False
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    actions: tuple[InitActionRow, ...] = ()
    action_count: int = 0
    actions_truncated: bool = False


@dataclass(frozen=True, slots=True)
class InitProjectPlan:
    """One targeted project's check row plus derived modal/toast predicates."""

    name: str
    display_name: str
    status: str
    unavailable_reason: str | None = None
    error: str | None = None
    planners: tuple[InitPlannerRow, ...] = ()

    @property
    def unavailable(self) -> bool:
        return self.unavailable_reason is not None

    @property
    def held(self) -> bool:
        return any(planner.blockers for planner in self.planners)

    @property
    def requires_tty(self) -> bool:
        return any(
            planner.requires_tty for planner in self.planners if planner.blockers
        )

    @property
    def changed_runnable(self) -> bool:
        return any(
            planner.has_changes and planner.runnable for planner in self.planners
        )

    @property
    def is_current(self) -> bool:
        if self.unavailable or self.held:
            return False
        return not any(planner.has_changes for planner in self.planners)


@dataclass(frozen=True, slots=True)
class InitCheckPayload:
    """One schema-versioned ``sase init --check --json`` document."""

    schema_version: int
    status: InitCheckStatus
    projects: tuple[InitProjectPlan, ...]
    planned_at: datetime


def parse_init_check_payload(stdout: str) -> InitCheckPayload:
    """Parse captured check stdout into a typed payload.

    Raises :class:`InitCheckPayloadError` with a bounded tail of the captured
    output when nothing JSON-shaped can be loaded, and with a version-naming
    message when ``schema_version`` does not match this TUI.
    """
    document = _load_json_document(stdout)
    version = _as_int(document.get("schema_version"), default=0)
    if version != INIT_CHECK_JSON_SCHEMA_VERSION:
        binary = shutil.which("sase") or "sase"
        raise InitCheckPayloadError(
            f"Unsupported init check JSON schema_version {version} "
            f"(expected {INIT_CHECK_JSON_SCHEMA_VERSION}). "
            f"The TUI invoked `{binary}` on PATH."
        )
    status = document.get("status")
    if status not in _KNOWN_CHECK_STATUSES:
        raise InitCheckPayloadError(
            f"Unsupported init check status {status!r}; "
            "expected one of current, drift, blocked."
        )
    raw_projects = document.get("projects")
    if not isinstance(raw_projects, list):
        raise InitCheckPayloadError(
            "init check JSON payload is missing a projects list."
        )
    projects = tuple(
        _parse_project(item) for item in raw_projects if isinstance(item, dict)
    )
    return InitCheckPayload(
        schema_version=version,
        status=status,  # type: ignore[arg-type]
        projects=projects,
        planned_at=local_now(),
    )


def bounded_output_tail(
    text: str,
    *,
    lines: int = _TAIL_LINES,
    chars: int = _TAIL_CHARS,
) -> str:
    """Return a bounded tail of captured subprocess output for error copy."""
    parts = text.splitlines()[-lines:]
    joined = "\n".join(parts).strip()
    if len(joined) > chars:
        return joined[-chars:]
    return joined


def _join_planner_labels(labels: Sequence[str]) -> str:
    """Join planner labels with commas and a final ``and``."""
    items = [label for label in labels if label]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def current_init_toast(payload: InitCheckPayload) -> str:
    """Return the no-op toast for a ``status: current`` check payload."""
    if len(payload.projects) == 1:
        project = payload.projects[0]
        display = project.display_name or project.name
        labels = [planner.label for planner in project.planners if planner.label]
        if not labels:
            return f"{display} is initialized"
        joined = _join_planner_labels(labels)
        verb = "is" if len(labels) == 1 else "are"
        return f"{display} is initialized · {joined} {verb} current"
    n = len(payload.projects)
    return f"{n} projects are current · nothing to initialize"


def _load_json_document(stdout: str) -> dict[str, Any]:
    candidates = (stdout, _json_slice(stdout))
    for candidate in candidates:
        if not candidate.strip():
            continue
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    tail = bounded_output_tail(stdout) or stdout.strip() or "(no output)"
    raise InitCheckPayloadError(tail)


def _json_slice(stdout: str) -> str:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end < start:
        return ""
    return stdout[start : end + 1]


def _parse_project(row: Mapping[str, Any]) -> InitProjectPlan:
    planners_raw = row.get("planners")
    if isinstance(planners_raw, list):
        planners = tuple(
            _parse_planner(item) for item in planners_raw if isinstance(item, dict)
        )
    else:
        planners = ()
    display = _as_str(row.get("display_name")) or _as_str(row.get("name"))
    return InitProjectPlan(
        name=_as_str(row.get("name")),
        display_name=display,
        status=_as_str(row.get("status"), default="current"),
        unavailable_reason=_optional_str(row.get("unavailable_reason")),
        error=_optional_str(row.get("error")),
        planners=planners,
    )


def _parse_planner(row: Mapping[str, Any]) -> InitPlannerRow:
    actions_raw = row.get("actions")
    if isinstance(actions_raw, list):
        actions = tuple(
            _parse_action(item) for item in actions_raw if isinstance(item, dict)
        )
    else:
        actions = ()
    action_count = _as_int(row.get("action_count"), default=len(actions))
    return InitPlannerRow(
        name=_as_str(row.get("name")),
        label=_as_str(row.get("label")) or _as_str(row.get("name")),
        summary=_as_str(row.get("summary")),
        has_changes=_as_bool(row.get("has_changes")),
        runnable=_as_bool(row.get("runnable"), default=True),
        requires_tty=_as_bool(row.get("requires_tty")),
        warnings=_string_tuple(row.get("warnings")),
        blockers=_string_tuple(row.get("blockers")),
        actions=actions,
        action_count=action_count,
        actions_truncated=_as_bool(row.get("actions_truncated")),
    )


def _parse_action(row: Mapping[str, Any]) -> InitActionRow:
    encoding = _optional_str(row.get("new_content_encoding"))
    content = row.get("new_content")
    new_content = content if isinstance(content, str) else None
    return InitActionRow(
        path=_as_str(row.get("path")),
        operation=_as_str(row.get("operation"), default="update"),
        detail=_as_str(row.get("detail")),
        new_content=new_content,
        new_content_encoding=encoding,
    )


def _as_str(value: object, *, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = _as_str(value)
    return text or None


def _as_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_as_str(item) for item in value if isinstance(item, str) and item)


__all__ = [
    "InitActionRow",
    "InitCheckPayload",
    "InitCheckPayloadError",
    "InitPlannerRow",
    "InitProjectPlan",
    "bounded_output_tail",
    "current_init_toast",
    "parse_init_check_payload",
]
