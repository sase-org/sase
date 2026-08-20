"""Task-type memory-note and catalog snapshot rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.amd.inline_memory import validate_short_memory_structure
from sase.content_layout import resolve_project_layout
from sase.mdtemplates import render_markdown_template
from sase.memory.notes import AGENTS_PARENT, apply_memory_frontmatter
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.task_types import (
    build_committed_task_type_snapshot_entries,
    get_task_type_registry,
    machine_global_builtin_task_type_specs,
    render_task_type_snapshot_json,
)

from .formatting import format_generated_memory_markdown

MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME = "memory-sase-task-types.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_SASE_TASK_TYPES_TEMPLATE_VARS = frozenset({"task_type_entries"})


def generated_task_types_memory_relative_path() -> Path:
    """Return the generated ``sase/memory/task_types.md`` root-relative path."""
    return CANONICAL_MEMORY_RELATIVE_ROOT / "task_types.md"


def generated_task_type_snapshot_path(root: Path) -> Path:
    """Return the committed catalog snapshot path (D6), outside ``sase/memory``."""
    return resolve_project_layout(root).namespace_root.path / "task_types.json"


def _task_type_note_field_names(
    spec: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(required_names, optional_names)`` for one task-type spec."""
    raw_fields = spec.get("fields")
    fields = raw_fields if isinstance(raw_fields, list) else ()
    required = tuple(
        str(field["name"])
        for field in fields
        if isinstance(field, Mapping) and field.get("required")
    )
    optional = tuple(
        str(field["name"])
        for field in fields
        if isinstance(field, Mapping) and not field.get("required")
    )
    return required, optional


def _render_task_type_note_entry(spec: Mapping[str, Any]) -> str:
    slug = str(spec.get("task_type", ""))
    label = str(spec.get("label") or slug)
    when_to_use = str(spec.get("when_to_use") or "")
    required, optional = _task_type_note_field_names(spec)
    lines = [f"### `{slug}` — {label}", "", when_to_use]
    bullets = []
    if required:
        names = ", ".join(f"`{name}`" for name in required)
        bullets.append(f"- Required fields: {names}")
    if optional:
        names = ", ".join(f"`{name}`" for name in optional)
        bullets.append(f"- Optional fields: {names}")
    if bullets:
        lines.append("")
        lines.extend(bullets)
    lines.append("")
    lines.append(
        f"Run `sase bead task-type show {slug}` for the full field list, "
        "validators, and body template."
    )
    return "\n".join(lines)


def _render_task_type_note_entries(specs: Sequence[Mapping[str, Any]]) -> str:
    creatable = tuple(spec for spec in specs if spec.get("agent_creatable", True))
    if not creatable:
        return "No agent-creatable task types are registered."
    ordered = sorted(creatable, key=lambda spec: str(spec.get("task_type", "")))
    return "\n\n".join(_render_task_type_note_entry(spec) for spec in ordered)


def _project_task_type_snapshot_entries() -> tuple[dict[str, Any], ...]:
    """Return the committed catalog this project's snapshot may document.

    Builtins, project-config types, and types from ``plugins.required``
    distributions are included. Optional plugin types stay live-only so two
    machines with different optional plugin sets render the same note and
    ``sase/task_types.json``.
    """
    return build_committed_task_type_snapshot_entries(get_task_type_registry())


def _home_task_type_specs() -> tuple[Mapping[str, Any], ...]:
    """Return builtin specs after machine-global ``bead.task_types`` config.

    The project layer and plugin types stay out so a home note is identical for
    every project on the machine.
    """
    return machine_global_builtin_task_type_specs()


def render_generated_task_types_memory_body(
    *, include_project_memory: bool
) -> tuple[str | None, str | None]:
    """Render the stable ``sase/memory/task_types.md`` body or return a blocker."""
    specs: Sequence[Mapping[str, Any]] = (
        _project_task_type_snapshot_entries()
        if include_project_memory
        else _home_task_type_specs()
    )
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_SASE_TASK_TYPES_TEMPLATE_VARS,
        context={"task_type_entries": _render_task_type_note_entries(specs)},
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error or "failed to render sase/memory/task_types.md template",
        )
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        return (
            None,
            f"packaged {MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME}: {structure_error}",
        )
    return formatted, None


def generated_task_types_memory_content(generated_task_types_body: str) -> str:
    """Return ``sase/memory/task_types.md`` with generated short-note frontmatter."""
    return apply_memory_frontmatter(
        generated_task_types_body,
        note_type="short",
        parent=AGENTS_PARENT,
    )


def render_generated_task_type_snapshot_json() -> tuple[str | None, str | None]:
    """Render the committed ``sase/task_types.json`` catalog snapshot (D6)."""
    entries = _project_task_type_snapshot_entries()
    try:
        return render_task_type_snapshot_json(entries), None
    except Exception as exc:
        return None, f"failed to render sase/task_types.json snapshot: {exc}"
