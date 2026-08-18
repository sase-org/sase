"""Display-time rendering of a task bead's typed body block."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.bead.model import Issue
from sase.core.rust import require_rust_binding
from sase.task_types._validation import plain_task_type_spec
from sase.task_types.registry import get_task_type_registry

TASK_TYPE_BODY_SEPARATOR = "---"
_UNKNOWN_TYPE_HEADER = "Task type: {slug} (not installed on this machine)"


def render_task_type_display_block(
    issue: Issue,
    *,
    registry: Any | None = None,
) -> str:
    """Return the Markdown block appended below a bead's description.

    The stored description is never modified. An unknown type degrades to the
    raw key/value pairs rather than failing the read.
    """

    slug = issue.task_type
    if not slug:
        return ""
    values = dict(issue.task_type_fields)
    resolved = get_task_type_registry() if registry is None else registry
    record = resolved.by_slug.get(slug)
    if record is None:
        return _degraded_unknown_block(slug, values)
    return _render_known_body(record.spec, values)


def _render_known_body(spec: Mapping[str, Any], values: Mapping[str, str]) -> str:
    filled = _values_for_template(spec, values)
    rendered = require_rust_binding("render_task_type_body")(
        plain_task_type_spec(spec),
        filled,
    )
    return str(rendered or "")


def _values_for_template(
    spec: Mapping[str, Any],
    values: Mapping[str, str],
) -> dict[str, str]:
    """Fill missing template-role fields with empty strings so optionals render."""

    filled = dict(values)
    fields = spec.get("fields")
    if not isinstance(fields, list):
        return filled
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        name = field.get("name")
        if not isinstance(name, str) or not name or name in filled:
            continue
        roles = field.get("role") or ()
        if isinstance(roles, str):
            roles = (roles,)
        if "template" in roles:
            filled[name] = ""
    return filled


def _degraded_unknown_block(slug: str, values: Mapping[str, str]) -> str:
    lines = [_UNKNOWN_TYPE_HEADER.format(slug=slug)]
    if values:
        lines.append("")
        lines.extend(f"- **{key}:** {value}" for key, value in values.items())
    return "\n".join(lines)


__all__ = [
    "TASK_TYPE_BODY_SEPARATOR",
    "render_task_type_display_block",
]
