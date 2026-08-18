"""``sase bead task-type list`` — catalog table or JSON."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ._models import TaskTypeRecord, TaskTypeRegistry
from .cli_render import record_accent, record_glyph, resolve_console, yes_no
from .registry import get_task_type_registry

_LIST_JSON_SCHEMA_VERSION = 1


def handle_task_type_list(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    registry: TaskTypeRegistry | None = None,
) -> int:
    """Run ``sase bead task-type list``."""

    resolved = get_task_type_registry() if registry is None else registry
    include_all = bool(getattr(args, "all", False))
    records = _visible_records(resolved.records, include_all=include_all)
    if bool(getattr(args, "json", False)):
        print(
            json.dumps(
                _list_json(records, include_all=include_all),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _render_list(
        records,
        include_all=include_all,
        console=resolve_console(console),
    )
    return 0


def _visible_records(
    records: Sequence[TaskTypeRecord], *, include_all: bool
) -> tuple[TaskTypeRecord, ...]:
    if include_all:
        return tuple(records)
    return tuple(record for record in records if record.agent_creatable)


def _render_list(
    records: Sequence[TaskTypeRecord],
    *,
    include_all: bool,
    console: Console,
) -> None:
    if not records:
        if include_all:
            console.print("No task types are registered.")
        else:
            console.print(
                "No agent-creatable task types are registered. "
                "Pass -a/--all to include hidden types."
            )
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("SLUG", no_wrap=True)
    table.add_column("LABEL", no_wrap=True)
    table.add_column("SUMMARY")
    table.add_column("SOURCE", no_wrap=True)
    table.add_column("AGENTS", no_wrap=True)
    for record in records:
        accent = record_accent(record)
        slug = Text()
        slug.append(f"{record_glyph(record)} ", style=accent)
        slug.append(record.task_type, style=f"bold {accent}")
        agents = Text(
            yes_no(record.agent_creatable),
            style="green" if record.agent_creatable else "dim",
        )
        table.add_row(
            slug,
            Text(str(record.spec.get("label") or record.task_type), style=accent),
            str(record.spec.get("summary") or ""),
            record.provenance.source,
            agents,
        )
    console.print(table)


def _list_json(
    records: Sequence[TaskTypeRecord], *, include_all: bool
) -> dict[str, Any]:
    return {
        "include_all": include_all,
        "schema_version": _LIST_JSON_SCHEMA_VERSION,
        "task_types": [_record_list_json(record) for record in records],
    }


def _record_list_json(record: TaskTypeRecord) -> dict[str, Any]:
    return {
        "agent_creatable": record.agent_creatable,
        "digest": record.digest,
        "glyph": record_glyph(record),
        "label": record.spec.get("label") or record.task_type,
        "package": record.provenance.package,
        "source": record.provenance.source,
        "summary": record.spec.get("summary") or "",
        "task_type": record.task_type,
    }


__all__ = [
    "handle_task_type_list",
]
