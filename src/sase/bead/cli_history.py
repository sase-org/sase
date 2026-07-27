"""Render the canonical bead event stream as per-issue history."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import sys
from typing import Any

from sase.agent.identity import discover_agent_identity
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_read_view,
)


def handle_bead_history(args: argparse.Namespace) -> None:
    if args.restore and not args.lost_notes:
        print("Error: --restore requires --lost-notes", file=sys.stderr)
        sys.exit(2)
    if args.lost_notes:
        _handle_lost_notes(args)
        return

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


def _handle_lost_notes(args: argparse.Namespace) -> None:
    issue_id = args.id
    with get_read_view() as view:
        try:
            findings = view.lost_notes(issue_id)
        except KeyError:
            print(f"Error: issue not found: {issue_id}", file=sys.stderr)
            sys.exit(1)

    if args.restore:
        print(_render_lost_notes(findings, full=True, preview=True), end="")
        revision_count = _lost_revision_count(findings)
        if not revision_count:
            return
        if not _confirm_lost_note_restore(revision_count):
            print("Lost-note restoration cancelled; no changes applied.")
            return
        _restore_lost_notes(findings, issue_id)
        return

    match args.format:
        case "compact":
            print(_render_lost_notes(findings, full=False), end="")
        case "full":
            print(_render_lost_notes(findings, full=True), end="")
        case "json":
            print(json.dumps({"findings": findings}, indent=2) + "\n", end="")
        case _:
            raise AssertionError(f"unknown history format: {args.format}")


def _render_lost_notes(
    findings: list[dict[str, object]],
    *,
    full: bool,
    preview: bool = False,
) -> str:
    if not findings:
        return "No lost note revisions found.\n"
    lines = [("Lost-note restoration preview:" if preview else "Lost note revisions:")]
    restore_date = _restored_date()
    for finding in findings:
        issue_id = str(finding["issue_id"])
        revisions = _dropped_revisions(finding)
        count = len(revisions)
        lines.append(
            f"  {issue_id}: {count} dropped revision{'' if count == 1 else 's'}"
        )
        if not full:
            continue
        current = str(finding.get("current_notes", ""))
        lines.append(f"    current: {current if current else '(empty)'}")
        for revision in revisions:
            timestamp = str(revision["timestamp"])
            actor = str(revision["actor"])
            text = str(revision["text"])
            marker = f"[{timestamp} · {actor}] {text}"
            planned_append = f"[{timestamp} · {actor}] (restored {restore_date}) {text}"
            lines.append(
                f"    append: {planned_append}" if preview else f"    {marker}"
            )
    return "\n".join(lines) + "\n"


def _restore_lost_notes(
    preview: list[dict[str, object]],
    issue_id: str | None,
) -> None:
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        current = mutation.project.lost_notes(issue_id)
        if current != preview:
            print(
                "ERROR: bead notes changed after the preview; no changes applied.",
                file=sys.stderr,
            )
            return
        identity = discover_agent_identity()
        author = identity.name if identity is not None else mutation.project.owner
        restore_date = _restored_date()
        revision_count = 0
        for finding in preview:
            finding_id = str(finding["issue_id"])
            for revision in _dropped_revisions(finding):
                entry = (
                    f"[{revision['timestamp']} · {revision['actor']}] "
                    f"(restored {restore_date}) {revision['text']}"
                )
                mutation.project.append_note(
                    finding_id,
                    entry,
                    author=author,
                )
                revision_count += 1
        mutation.commit(
            "chore(beads): restore "
            f"{revision_count} lost note revision"
            f"{'' if revision_count == 1 else 's'}"
        )
    print(
        f"✓ Restored {revision_count} lost note revision"
        f"{'' if revision_count == 1 else 's'} across "
        f"{len(preview)} bead{'' if len(preview) == 1 else 's'}"
    )


def _dropped_revisions(
    finding: dict[str, object],
) -> list[dict[str, object]]:
    revisions = finding.get("dropped_revisions", [])
    if not isinstance(revisions, list):
        return []
    return [revision for revision in revisions if isinstance(revision, dict)]


def _lost_revision_count(findings: list[dict[str, object]]) -> int:
    return sum(len(_dropped_revisions(finding)) for finding in findings)


def _confirm_lost_note_restore(revision_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Restore {revision_count} lost note revision"
            f"{'' if revision_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _restored_date() -> str:
    return datetime.now(UTC).date().isoformat()


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
