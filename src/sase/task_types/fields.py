"""Create-time field parsing and validation for typed task beads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.task_types._snapshot import task_type_snapshot_entry as _snapshot_entry
from sase.task_types._validation import plain_task_type_spec
from sase.task_types.registry import get_task_type_registry

UNTYPED_TASK_TYPE = "untyped"

_FIELD_ASSIGNMENT_SEP = "="
_FILE_VALUE_PREFIX = "@"


class TaskTypeCreateError(ValueError):
    """A user-facing create-time task-type problem."""


def parse_field_args(raw_fields: Sequence[str] | None) -> dict[str, str]:
    """Parse repeatable ``k=v`` ``--field`` values.

    A value of the form ``@<path>`` is read from that file. Duplicate keys are
    an error rather than a silent last-wins.
    """

    parsed: dict[str, str] = {}
    for raw in raw_fields or ():
        key, value = _split_field_assignment(raw)
        if key in parsed:
            raise TaskTypeCreateError(f"duplicate --field key: {key}")
        parsed[key] = _resolve_field_value(key, value)
    return parsed


def resolve_created_task_type(
    slug: str,
    fields: Mapping[str, str],
    *,
    registry: Any | None = None,
) -> tuple[str, dict[str, str]]:
    """Resolve, authorize, and validate one typed-task create.

    Returns the canonical slug and the stored field map. Bare untyped creates
    pass an empty *slug* and must not carry fields.
    """

    stored_fields = dict(fields)
    if not slug:
        if stored_fields:
            raise TaskTypeCreateError(
                "task type fields require -T 'task(<slug>)'; "
                "bare -T task creates an untyped bead"
            )
        return "", {}

    resolved = get_task_type_registry() if registry is None else registry
    record = resolved.by_slug.get(slug)
    if record is None:
        raise TaskTypeCreateError(_unknown_task_type_message(slug, resolved))
    if not record.agent_creatable:
        raise TaskTypeCreateError(
            f"task type '{slug}' cannot be created by agents; "
            "it is reserved for the providing plugin"
        )
    problems = _field_value_problems(record.spec, stored_fields)
    if problems:
        details = "\n".join(f"  {name}: {message}" for name, message in problems)
        raise TaskTypeCreateError(f"invalid task type fields:\n{details}")
    return record.task_type, stored_fields


def issue_task_type_slug(task_type: str) -> str:
    """Return the filter/display slug for a stored ``task_type`` value."""

    return task_type if task_type else UNTYPED_TASK_TYPE


def issue_matches_task_types(task_type: str, wanted: Sequence[str]) -> bool:
    """Return whether a stored type matches one of the requested slugs."""

    if not wanted:
        return True
    current = issue_task_type_slug(task_type).casefold()
    return any(current == item.casefold() for item in wanted if item)


def _split_field_assignment(raw: str) -> tuple[str, str]:
    if _FIELD_ASSIGNMENT_SEP not in raw:
        raise TaskTypeCreateError(f"--field expects k=v, got {raw!r}")
    key, value = raw.split(_FIELD_ASSIGNMENT_SEP, 1)
    key = key.strip()
    if not key:
        raise TaskTypeCreateError(f"--field expects k=v, got {raw!r}")
    return key, value


def _resolve_field_value(key: str, value: str) -> str:
    if not value.startswith(_FILE_VALUE_PREFIX) or value == _FILE_VALUE_PREFIX:
        return value
    path = Path(value[len(_FILE_VALUE_PREFIX) :]).expanduser()
    if not path.is_file():
        raise TaskTypeCreateError(f"--field {key}: file not found: {path}")
    return path.read_text(encoding="utf-8")


def _field_value_problems(
    spec: Mapping[str, Any],
    values: Mapping[str, str],
) -> list[tuple[str, str]]:
    errors = require_rust_binding("validate_task_type_field_values")(
        plain_task_type_spec(spec),
        dict(values),
    )
    problems: list[tuple[str, str]] = []
    for error in errors or ():
        if isinstance(error, Mapping):
            field_name = str(error.get("field") or "")
            message = str(error.get("message") or error)
        else:
            field_name = ""
            message = str(error)
        problems.append((field_name or "field", message))
    return problems


def _unknown_task_type_message(slug: str, registry: Any) -> str:
    available = ", ".join(record.task_type for record in registry.agent_creatable)
    lines = [f"unknown task type {slug!r}"]
    if available:
        lines.append(f"Available agent-creatable types: {available}")
    else:
        lines.append("No agent-creatable task types are installed")
    snapshot = _snapshot_entry(slug)
    if snapshot is not None:
        package = str(snapshot.get("package") or "").strip()
        if package and package != "sase":
            lines.append(
                f"task type {slug!r} is provided by {package}; "
                f"run `sase plugin install {package}`"
            )
    return "\n".join(lines)


__all__ = [
    "UNTYPED_TASK_TYPE",
    "TaskTypeCreateError",
    "issue_matches_task_types",
    "issue_task_type_slug",
    "parse_field_args",
    "resolve_created_task_type",
]
