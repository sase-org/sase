"""``sase bead task-type show`` — one catalog member in full."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any

from rich.console import Console
from rich.text import Text

from ._models import TaskTypeRecord, TaskTypeRegistry
from .cli_render import record_accent, record_glyph, resolve_console, yes_no
from .registry import get_task_type_registry

_SHOW_JSON_SCHEMA_VERSION = 1


def handle_task_type_show(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    registry: TaskTypeRegistry | None = None,
) -> int:
    """Run ``sase bead task-type show <slug>``."""

    slug = str(getattr(args, "slug", "") or "")
    resolved = get_task_type_registry() if registry is None else registry
    record = resolved.by_slug.get(slug)
    if record is None:
        available = ", ".join(sorted(resolved.by_slug)) or "(none)"
        print(
            f"Error: unknown task type: {slug}\nAvailable: {available}",
            file=sys.stderr,
        )
        return 1
    if bool(getattr(args, "json", False)):
        print(json.dumps(_show_json(record), indent=2, sort_keys=True))
        return 0
    _render_show(record, console=resolve_console(console))
    return 0


def _render_show(record: TaskTypeRecord, *, console: Console) -> None:
    accent = record_accent(record)
    heading = Text()
    heading.append(f"{record_glyph(record)} ", style=accent)
    heading.append(
        str(record.spec.get("label") or record.task_type), style=f"bold {accent}"
    )
    heading.append(f"  ({record.task_type})", style="dim")
    console.print(heading)
    summary = str(record.spec.get("summary") or "")
    if summary:
        console.print(summary)
    console.print()
    console.print("[bold]WHEN TO USE[/bold]")
    console.print(f"  {record.spec.get('when_to_use') or ''}")
    console.print()
    console.print("[bold]FIELDS[/bold]")
    fields = _spec_fields(record.spec)
    if not fields:
        console.print("  (none)")
    for field in fields:
        console.print(f"  {_field_heading(field)}")
        help_text = field.get("help")
        if isinstance(help_text, str) and help_text:
            console.print(f"    {help_text}")
        for line in _field_validator_lines(field):
            console.print(f"    {line}")
    console.print()
    console.print("[bold]BODY TEMPLATE[/bold]")
    template = record.spec.get("body_template")
    if isinstance(template, str) and template.strip():
        for line in template.splitlines() or [""]:
            console.print(f"  {line}")
    else:
        console.print("  (none)")
    console.print()
    console.print("[bold]TRIAGE[/bold]")
    console.print(f"  min_plus_ones: {_min_plus_ones(record.spec)}")
    console.print()
    console.print("[bold]PROVENANCE[/bold]")
    console.print(f"  source:       {record.provenance.label}")
    console.print(f"  package:      {record.provenance.package}")
    console.print(f"  version:      {record.provenance.version}")
    console.print(f"  agents:       {yes_no(record.agent_creatable)}")
    console.print(f"  digest:       {record.digest}")


def _show_json(record: TaskTypeRecord) -> dict[str, Any]:
    return {
        "accent_color": record.resolved_accent_color,
        "agent_creatable": record.agent_creatable,
        "body_template": record.spec.get("body_template") or "",
        "digest": record.digest,
        "fields": [_field_json(field) for field in _spec_fields(record.spec)],
        "glyph": record_glyph(record),
        "label": record.spec.get("label") or record.task_type,
        "provenance": {
            "label": record.provenance.label,
            "package": record.provenance.package,
            "source": record.provenance.source,
            "version": record.provenance.version,
        },
        "schema_version": _SHOW_JSON_SCHEMA_VERSION,
        "summary": record.spec.get("summary") or "",
        "task_type": record.task_type,
        "triage": {"min_plus_ones": _min_plus_ones(record.spec)},
        "when_to_use": record.spec.get("when_to_use") or "",
    }


def _spec_fields(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = spec.get("fields")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _field_heading(field: Mapping[str, Any]) -> str:
    name = str(field.get("name") or "")
    field_type = str(field.get("type") or "string")
    required = "required" if bool(field.get("required")) else "optional"
    roles = ", ".join(_field_roles(field)) or "data, template"
    return f"{name}  {field_type}  {required}  {roles}"


def _field_roles(field: Mapping[str, Any]) -> tuple[str, ...]:
    raw = field.get("role")
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    return ()


def _field_validator_lines(field: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    pattern = field.get("pattern")
    if isinstance(pattern, str) and pattern:
        lines.append(f"pattern: {pattern}")
    max_length = field.get("max_length")
    if isinstance(max_length, int):
        lines.append(f"max_length: {max_length}")
    values = field.get("values")
    if isinstance(values, list) and values:
        lines.append("values: " + ", ".join(str(item) for item in values))
    minimum = field.get("minimum")
    if isinstance(minimum, int):
        lines.append(f"minimum: {minimum}")
    maximum = field.get("maximum")
    if isinstance(maximum, int):
        lines.append(f"maximum: {maximum}")
    return lines


def _field_json(field: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "help": field.get("help") or "",
        "label": field.get("label") or "",
        "name": field.get("name") or "",
        "required": bool(field.get("required")),
        "role": list(_field_roles(field)) or ["data", "template"],
        "type": field.get("type") or "string",
    }
    for key in ("pattern", "max_length", "values", "minimum", "maximum"):
        if key in field:
            payload[key] = field[key]
    return payload


def _min_plus_ones(spec: Mapping[str, Any]) -> int:
    triage = spec.get("triage")
    if not isinstance(triage, Mapping):
        return 0
    raw = triage.get("min_plus_ones", 0)
    return raw if isinstance(raw, int) else 0


__all__ = [
    "handle_task_type_show",
]
