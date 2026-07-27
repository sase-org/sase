"""Render the canonical bead event stream as per-issue history."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sase.bead.cli_common import get_read_view


def handle_bead_history(args: argparse.Namespace) -> None:
    issue_id = args.id
    if not issue_id:
        print("Error: issue ID is required", file=sys.stderr)
        sys.exit(2)

    with get_read_view() as view:
        try:
            history = view.history(issue_id)
        except KeyError:
            print(f"Error: issue not found: {issue_id}", file=sys.stderr)
            sys.exit(1)

    entries = _filtered_entries(
        history.get("entries", []),
        fields=args.field,
        limit=args.limit,
    )
    envelope = {
        "issue_id": history["issue_id"],
        "schema_version": history["schema_version"],
        "entries": entries,
    }

    match args.format:
        case "compact":
            print(_render_compact(entries), end="")
        case "full":
            print(_render_full(entries), end="")
        case "json":
            print(json.dumps(envelope, indent=2) + "\n", end="")
        case _:
            raise AssertionError(f"unknown history format: {args.format}")


def _filtered_entries(
    raw_entries: object,
    *,
    fields: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(raw_entries, list):
        return []
    entries = [
        {
            **entry,
            "changes": list(entry.get("changes", [])),
        }
        for entry in raw_entries
        if isinstance(entry, dict)
    ]
    if fields:
        selected = set(fields)
        filtered: list[dict[str, Any]] = []
        for entry in entries:
            changes = [
                change for change in entry["changes"] if change.get("field") in selected
            ]
            if changes:
                filtered.append({**entry, "changes": changes})
        entries = filtered
    if limit:
        entries = entries[-limit:]
    return entries


def _render_compact(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No history entries found.\n"
    lines = []
    for entry in entries:
        fields = ", ".join(str(change["field"]) for change in entry["changes"])
        lines.append(
            f"{entry['timestamp']} · {entry['actor']} · "
            f"{entry['operation']} · {fields or '(no changes)'}"
        )
    return "\n".join(lines) + "\n"


def _render_full(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No history entries found.\n"
    sections = []
    for entry in entries:
        lines = [
            f"{entry['timestamp']} · {entry['actor']} · {entry['operation']}",
            f"  Event: {entry['event_id']}",
        ]
        changes = entry["changes"]
        if not changes:
            lines.append("  Changes: (none)")
        for change in changes:
            lines.append(f"  {change['field']}:")
            lines.extend(_render_change_side("from", change.get("from")))
            lines.extend(_render_change_side("to", change.get("to")))
        sections.append("\n".join(lines))
    return f"\n{'-' * 60}\n".join(sections) + "\n"


def _render_change_side(label: str, value: object) -> list[str]:
    if value is None:
        return [f"    {label}: (unset)"]
    if isinstance(value, str):
        value_lines = value.splitlines() or [""]
        if len(value_lines) == 1:
            return [f"    {label}: {value_lines[0]}"]
        return [
            f"    {label}:",
            *(f"      {line}" for line in value_lines),
        ]
    return [f"    {label}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"]


__all__ = ["handle_bead_history"]
