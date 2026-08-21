"""``sase artifact link migrate-notes`` dry-run and apply."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table

from sase.sdd.artifact_link_migrate_notes import (
    RelatedNoteConversion,
    RelatedNoteMigrationPlan,
    RelatedNoteWorkItem,
    apply_related_note_migration,
    plan_related_note_migration,
)

_MIGRATE_NOTES_SCHEMA_VERSION = 1


def handle_link_migrate_notes(args: argparse.Namespace) -> int:
    """Dry-run RELATED: migration, or apply related events and MIGRATED: notes."""

    from sase.bead.cli_common import bead_store_mutation, get_read_view

    apply = bool(getattr(args, "apply", False))
    as_json = bool(getattr(args, "json", False))

    with get_read_view() as view:
        plan = plan_related_note_migration(view.list_issues())
    applied: dict[str, object] | None = None
    if apply:
        with bead_store_mutation() as mutation:
            applied = apply_related_note_migration(mutation.project, plan)
            if mutation.project.mutation_changed:
                mutation.commit("chore(beads): migrate RELATED: notes to related links")
    payload = _plan_to_json(plan, applied=applied)
    if as_json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_plan(plan, applied=applied)
    return 0


def _plan_to_json(
    plan: RelatedNoteMigrationPlan,
    *,
    applied: dict[str, object] | None,
) -> dict[str, object]:
    converted = [
        {
            "issue_id": item.issue_id,
            "line": item.line,
            "targets": list(item.targets),
            "why": item.why,
        }
        for item in plan.conversions
    ]
    worklist = [
        {
            "issue_id": item.issue_id,
            "line": item.line,
            "reason": item.reason,
        }
        for item in plan.worklist
    ]
    payload: dict[str, object] = {
        "schema_version": _MIGRATE_NOTES_SCHEMA_VERSION,
        "mode": "dry_run" if applied is None else "applied",
        "scanned_beads": plan.scanned_beads,
        "scanned_notes": plan.scanned_notes,
        "converted": converted,
        "worklist": worklist,
    }
    if applied is not None:
        payload["applied"] = applied
    return payload


def _print_plan(
    plan: RelatedNoteMigrationPlan,
    *,
    applied: dict[str, object] | None,
) -> None:
    console = Console(highlight=False)
    mode = "applied" if applied is not None else "dry-run"
    console.print(
        f"[bold]RELATED: migration ({mode})[/bold]  "
        f"{plan.scanned_notes} note(s) on {plan.scanned_beads} bead(s)"
    )
    if plan.conversions:
        table = Table(title="Convertible", show_header=True, header_style="bold")
        table.add_column("Bead")
        table.add_column("Targets")
        table.add_column("Why")
        conversion: RelatedNoteConversion
        for conversion in plan.conversions:
            table.add_row(
                conversion.issue_id, ", ".join(conversion.targets), conversion.why
            )
        console.print(table)
    else:
        console.print("No convertible RELATED: notes.")
    if plan.worklist:
        table = Table(title="Worklist", show_header=True, header_style="bold")
        table.add_column("Bead")
        table.add_column("Reason")
        table.add_column("Line")
        work_item: RelatedNoteWorkItem
        for work_item in plan.worklist:
            table.add_row(work_item.issue_id, work_item.reason, work_item.line)
        console.print(table)
    else:
        console.print("Worklist is empty.")
    if applied is not None:
        console.print(
            f"Wrote {applied.get('converted', 0)} related edge(s) and "
            f"{applied.get('migrated_notes', 0)} MIGRATED: note(s)."
        )


__all__ = ["handle_link_migrate_notes"]
