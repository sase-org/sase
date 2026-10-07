"""Bead doctor repair operations.

Each ``repair_*`` entry is consumed by the doctor orchestrator in
``cli_admin_doctor``. Per-repair render/confirm/refusal helpers stay private
here because only the repair in this file uses them.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_project,
)
from sase.bead.plan_archive_doctor import (
    PlanArchiveDoctorReport,
    inspect_plan_archive_health,
    preview_plan_archive_repairs,
    repair_plan_archive as _apply_plan_archive_repairs,
)


def repair_plan_archive(
    preview: PlanArchiveDoctorReport,
    archive_store: Any,
    plan_roots: tuple[Path, ...],
    assume_yes: bool,
) -> None:
    for line in preview_plan_archive_repairs(preview):
        print(line)
    repair_count = len(preview.recoverable_findings)
    if not repair_count:
        print("No plan archives can be repaired on this machine.")
        return
    if not (assume_yes or _confirm_plan_archive_repair(repair_count)):
        print("Plan archive repair cancelled; no changes applied.")
        return

    with get_project() as proj:
        current = inspect_plan_archive_health(
            proj.list_issues(),
            archive_store,
            plan_roots=plan_roots,
        )
    if current != preview:
        print(
            "ERROR: plan archive findings changed after the preview; "
            "no changes applied.",
            file=sys.stderr,
        )
        return

    result = _apply_plan_archive_repairs(
        preview,
        archive_store,
        primary_root=Path.cwd(),
    )
    if not result.repaired:
        print("No plan archive changes were needed.")
        return
    committed = " and committed" if result.committed else ""
    print(
        f"✓ Repaired {len(result.repaired)} plan archive"
        f"{'' if len(result.repaired) == 1 else 's'}{committed}"
    )


def repair_projection(
    preview: list[dict[str, Any]],
    plan_roots: tuple[Path, ...],
    reference_context: ArtifactRefContext | None,
    assume_yes: bool,
) -> None:
    _render_projection_repair_preview(preview)
    if not preview:
        print("No projection drift to repair.")
        return
    refusal = _projection_repair_refusal(preview)
    if refusal is not None:
        print(
            f"ERROR: refusing projection repair: {refusal}",
            file=sys.stderr,
        )
        return
    if not (assume_yes or _confirm_projection_repair(len(preview))):
        print("Projection repair cancelled; no changes applied.")
        return

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        current_report = mutation.project.doctor_report(
            plan_roots,
            reference_context,
        )
        current_preview = [
            dict(row)
            for row in current_report.get("projection_drift", [])
            if isinstance(row, dict)
        ]
        if current_preview != preview:
            print(
                "ERROR: issues.jsonl projection drift changed after the "
                "preview; no changes applied.",
                file=sys.stderr,
            )
            return
        refusal = _projection_repair_refusal(current_preview)
        if refusal is not None:
            print(
                f"ERROR: refusing projection repair: {refusal}",
                file=sys.stderr,
            )
            return
        mutation.project.reproject_from_events()
        # No commit: since projection-off (sase-1h8.11) the regenerated
        # file is a git-ignored local export, so there is nothing to commit.
    print(
        f"✓ Reprojected {len(preview)} bead row"
        f"{'' if len(preview) == 1 else 's'} from canonical events"
    )


def repair_issue_prefix(assume_yes: bool) -> None:
    from sase.bead.prefix_policy import (
        repair_stale_key_prefix,
        stale_key_prefix_report,
    )

    with get_project() as proj:
        report = stale_key_prefix_report(proj.beads_dir)
        beads_dir = proj.beads_dir

    if report is None:
        print("No issue prefix to repair.")
        return

    _render_issue_prefix_repair_preview(report)
    if not (assume_yes or _confirm_issue_prefix_repair(report)):
        print("Issue prefix repair cancelled; no changes applied.")
        return

    from sase.bead.sync import bead_store_write_lock

    with bead_store_write_lock(beads_dir) as already_locked:
        if stale_key_prefix_report(beads_dir) != report:
            print(
                "ERROR: bead issue prefix changed after the preview; "
                "no changes applied.",
                file=sys.stderr,
            )
            return
        stored, corrected = report
        repair_stale_key_prefix(beads_dir)
        auto_commit_bead_store(
            f"chore(beads): repair issue prefix {stored} -> {corrected}",
            push_after_commit=False,
            already_locked=already_locked,
        )
    stored, corrected = report
    print(f"✓ Repaired bead issue prefix: {stored} -> {corrected}")


def repair_attachments(attachment_report: Any | None, assume_yes: bool) -> None:
    from sase.bead.attachment_doctor import (
        inspect_attachment_health,
        preview_attachment_repairs,
        repair_attachment_health,
    )

    report = attachment_report
    if report is None:
        try:
            report = inspect_attachment_health()
        except Exception as exc:  # noqa: BLE001 - doctor reports availability.
            print(f"Attachment repair unavailable: {exc}", file=sys.stderr)
            return
    for line in preview_attachment_repairs(report):
        print(line)
    if not any(
        [
            getattr(report, "orphans", ()),
            getattr(report, "corrupt", ()),
            getattr(report, "pending_upload", 0),
            getattr(report, "outbox_unreadable", False),
        ]
    ):
        print("No attachment repairs apply.")
        return
    if not (assume_yes or _confirm_attachment_repair()):
        print("Attachment repair cancelled; no changes applied.")
        return
    try:
        current = inspect_attachment_health()
    except Exception as exc:  # noqa: BLE001 - doctor reports availability.
        print(f"Attachment repair unavailable: {exc}", file=sys.stderr)
        return
    for result in repair_attachment_health(current):
        print(result)
    print("✓ Attachment repair complete")


def _render_issue_prefix_repair_preview(report: tuple[str, str]) -> None:
    stored, corrected = report
    print("Issue prefix repair preview:")
    print(f"  {stored} -> {corrected}")
    print(
        "Existing bead IDs keep the old prefix; only new top-level beads use "
        f"'{corrected}'."
    )


def _confirm_issue_prefix_repair(report: tuple[str, str]) -> bool:
    if not sys.stdin.isatty():
        return False
    stored, corrected = report
    try:
        answer = input(f"Reset issue prefix from '{stored}' to '{corrected}'? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _render_projection_repair_preview(
    preview: list[dict[str, Any]],
) -> None:
    print("Projection repair preview:")
    if not preview:
        print("  (no drift)")
        return
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preview:
        for field in row.get("changed_fields", []):
            by_field[str(field)].append(row)
    for field in sorted(by_field):
        rows = by_field[field]
        print(f"  {field} ({len(rows)} row(s)):")
        for row in rows:
            current = row.get("current")
            reduced = row.get("reduced")
            old_value = (
                current.get(field) if isinstance(current, dict) else "<missing row>"
            )
            new_value = (
                reduced.get(field) if isinstance(reduced, dict) else "<missing row>"
            )
            print(
                f"    {row.get('issue_id')}: "
                f"{_render_projection_value(old_value)} -> "
                f"{_render_projection_value(new_value)}"
            )


def _projection_repair_refusal(
    preview: list[dict[str, Any]],
) -> str | None:
    # close_history is allowed because the first repair after the close-history
    # upgrade legitimately materializes archived records for beads whose close
    # reasons were destroyed by a reopen before sase-core started archiving them.
    allowed_fields = {"closed_at", "close_reason", "close_history", "updated_at"}
    for row in preview:
        issue_id = str(row.get("issue_id", "<unknown>"))
        current = row.get("current")
        reduced = row.get("reduced")
        if not isinstance(current, dict) or not isinstance(reduced, dict):
            return f"{issue_id} would change the issues.jsonl row set"
        fields = {str(field) for field in row.get("changed_fields", [])}
        unexpected = sorted(fields - allowed_fields)
        if unexpected:
            return f"{issue_id} changes unexpected field(s): {', '.join(unexpected)}"
        if current.get("status") != reduced.get("status"):
            return f"{issue_id} changes status"
        if "closed_at" in fields:
            reason = _closed_at_repair_refusal(
                current.get("closed_at"),
                reduced.get("closed_at"),
            )
            if reason is not None:
                return f"{issue_id} {reason}"
    return None


def _closed_at_repair_refusal(current: object, reduced: object) -> str | None:
    if not isinstance(current, str):
        return "adds a closed_at value where none was recorded"
    if reduced is None:
        return None
    if not isinstance(reduced, str):
        return "has an invalid reduced closed_at value"
    try:
        current_time = datetime.fromisoformat(current.replace("Z", "+00:00"))
        reduced_time = datetime.fromisoformat(reduced.replace("Z", "+00:00"))
    except ValueError:
        return "has an unparseable closed_at value"
    if reduced_time > current_time:
        return f"moves closed_at later ({current} -> {reduced})"
    return None


def _render_projection_value(value: object) -> str:
    if value == "<missing row>":
        return str(value)
    return json.dumps(value, sort_keys=True)


def _confirm_projection_repair(row_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Rewrite {row_count} stale projection row"
            f"{'' if row_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _confirm_attachment_repair() -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input("Apply attachment repairs? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _confirm_plan_archive_repair(repair_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Archive {repair_count} missing plan"
            f"{'' if repair_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


__all__ = [
    "repair_attachments",
    "repair_issue_prefix",
    "repair_plan_archive",
    "repair_projection",
]
