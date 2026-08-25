"""``sase bead task-type show`` — one catalog member in full."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.text import Text

from ._models import TaskTypeRecord, TaskTypeRegistry
from .cli_render import resolve_console, yes_no
from .detail import (
    TaskTypeDetail,
    task_type_detail,
    task_type_detail_to_json,
    task_type_field_heading,
    task_type_field_validator_lines,
)
from .registry import get_task_type_registry


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
    _render_show(task_type_detail(record), console=resolve_console(console))
    return 0


def _render_show(detail: TaskTypeDetail, *, console: Console) -> None:
    accent = detail.accent_color or "dim"
    heading = Text()
    heading.append(f"{detail.glyph} ", style=accent)
    heading.append(detail.label, style=f"bold {accent}")
    heading.append(f"  ({detail.task_type})", style="dim")
    console.print(heading)
    if detail.summary:
        console.print(detail.summary)
    console.print()
    console.print("[bold]WHEN TO USE[/bold]")
    console.print(f"  {detail.when_to_use}")
    if detail.create_refusal:
        console.print()
        console.print("[bold]CREATE REFUSAL[/bold]")
        console.print(f"  {detail.create_refusal}")
    console.print()
    console.print("[bold]FIELDS[/bold]")
    if not detail.fields:
        console.print("  (none)")
    for field in detail.fields:
        console.print(f"  {task_type_field_heading(field)}")
        if field.help:
            console.print(f"    {field.help}")
        for line in task_type_field_validator_lines(field):
            console.print(f"    {line}")
    console.print()
    console.print("[bold]BODY TEMPLATE[/bold]")
    if detail.body_template.strip():
        for line in detail.body_template.splitlines() or [""]:
            console.print(f"  {line}")
    else:
        console.print("  (none)")
    console.print()
    console.print("[bold]TRIAGE[/bold]")
    console.print(f"  min_plus_ones: {detail.triage.min_plus_ones}")
    console.print()
    console.print("[bold]PROVENANCE[/bold]")
    console.print(f"  source:       {detail.provenance.label}")
    console.print(f"  package:      {detail.provenance.package}")
    console.print(f"  version:      {detail.provenance.version}")
    console.print(f"  agents:       {yes_no(detail.agent_creatable)}")
    console.print(f"  digest:       {detail.digest}")


def _show_json(record: TaskTypeRecord) -> dict[str, Any]:
    return task_type_detail_to_json(task_type_detail(record))


__all__ = [
    "handle_task_type_show",
]
