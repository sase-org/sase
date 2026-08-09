"""Administrative bead CLI command handlers."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.conflict_resolver import handle_resolve_conflicts_command
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    get_project,
)
from sase.bead.design_ref_repair import (
    DesignRefRepairPreview,
    plan_design_ref_repairs,
)


def handle_bead_sync(args: argparse.Namespace) -> None:
    with get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ Bead state is in sync with git")
            else:
                print("○ Bead state has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced bead state to git")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    plan_roots = _resolve_doctor_plan_roots()
    reference_context = _resolve_doctor_reference_context()
    fix_design_refs = bool(getattr(args, "fix_design_refs", False))
    fix_issue_prefix = bool(getattr(args, "fix_issue_prefix", False))
    fix_projection = bool(getattr(args, "fix_projection", False))
    assume_yes = bool(getattr(args, "yes", False))
    with get_project() as proj:
        projection_preview: list[dict[str, Any]] = []
        if fix_projection:
            report = proj.doctor_report(plan_roots, reference_context)
            messages = [str(message) for message in report["messages"]]
            projection_preview = [
                dict(row)
                for row in report.get("projection_drift", [])
                if isinstance(row, dict)
            ]
        else:
            messages = proj.doctor(plan_roots, reference_context)
        for msg in messages:
            print(msg)
        preview = (
            plan_design_ref_repairs(
                proj.list_issues(),
                roots=plan_roots,
            )
            if fix_design_refs
            else None
        )

    if fix_projection:
        _repair_projection(
            projection_preview, plan_roots, reference_context, assume_yes
        )

    if fix_issue_prefix:
        _repair_issue_prefix(assume_yes)

    if preview is None:
        return
    _render_design_ref_repair_preview(preview)
    if not preview.repairs:
        print("No design references can be repaired safely.")
        return
    if not (assume_yes or _confirm_design_ref_repairs(len(preview.repairs))):
        print("Design reference repair cancelled; no changes applied.")
        return

    with bead_store_mutation(auto_commit_bead_store) as mutation:
        current_preview = plan_design_ref_repairs(
            mutation.project.list_issues(),
            roots=plan_roots,
        )
        if current_preview != preview:
            print(
                "ERROR: bead design references changed after the preview; "
                "no changes applied.",
                file=sys.stderr,
            )
            return
        for repair in preview.repairs:
            mutation.project.update(
                repair.bead_id,
                design=repair.new_reference,
            )
        mutation.commit(
            "chore(beads): repair "
            f"{len(preview.repairs)} design reference"
            f"{'' if len(preview.repairs) == 1 else 's'}"
        )
    print(
        f"✓ Repaired {len(preview.repairs)} bead design reference"
        f"{'' if len(preview.repairs) == 1 else 's'}"
    )


def _repair_projection(
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
        mutation.commit("chore(beads): reproject bead state from canonical events")
    print(
        f"✓ Reprojected {len(preview)} bead row"
        f"{'' if len(preview) == 1 else 's'} from canonical events"
    )


def _repair_issue_prefix(assume_yes: bool) -> None:
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


def _resolve_doctor_plan_roots() -> tuple[Path, ...]:
    try:
        from sase.sdd.plan_refs import (
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )

        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return resolve_plan_roots(workspace_dir, workspace_num)
    except Exception:
        return ()


def _resolve_doctor_reference_context() -> ArtifactRefContext | None:
    try:
        from sase.artifact_ref_context import artifact_ref_context
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution

        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return artifact_ref_context(workspace_dir, workspace_num)
    except Exception:
        return None


def _render_design_ref_repair_preview(
    preview: DesignRefRepairPreview,
) -> None:
    print("Design reference repair preview:")
    if preview.repairs:
        for repair in preview.repairs:
            print(
                f"  {repair.bead_id}: {repair.old_reference} -> {repair.new_reference}"
            )
    else:
        print("  (no repairs)")
    print("Unrepaired design references:")
    if preview.unrepaired:
        for unrepaired in preview.unrepaired:
            print(
                f"  {unrepaired.bead_id}: {unrepaired.old_reference} "
                f"({unrepaired.reason})"
            )
    else:
        print("  (none)")


def _confirm_design_ref_repairs(repair_count: int) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            f"Apply {repair_count} design reference repair"
            f"{'' if repair_count == 1 else 's'}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Source of truth:
  Version-controlled projects use this checkout's sdd/beads/ event store.
  issues.jsonl remains a generated compatibility projection.
  Normal reads do not merge numbered sibling workspaces or legacy stores.

Quick Start:
  sase bead init                                 Create sdd/beads/ in current directory
  Agents: use /sase_new_task before creating any task bead
  sase bead create -t "Follow-up" --type task --size small
                                                  Create a standalone draft task
  sase bead +1 <task-id> -n "Independent repro"  Corroborate an existing task
  sase bead create -t "Fix bug" --type phase(<plan-id>)
  sase bead create -t "New feature" --type plan(sdd/plans/202605/feature.md) --tier plan
  sase bead create -t "Epic" --type plan(sdd/plans/202605/epic.md) --tier epic
  sase bead list                                 List open/claimed/ready/in-progress issues
  sase bead list --format=json                   Machine-readable listing
  sase bead list --limit=5                       Limit printed issues
  sase bead list --status=open                   List open issues
  sase bead list --status=closed                 List newest 20 closed issues (-n 0 for all)
  sase bead list --tier=epic                     List epic plan beads
  sase bead list --type=task --since=1w --status=all
                                                  Task beads created in the last week
  sase bead ready                                Show unblocked ready task beads
  sase bead show <id>                            View issue details
  sase bead show <id> --format=json              Machine-readable bead detail
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead snooze <id> -u 3d -r "why"           Defer a task until a wake time
  sase bead snooze <id> -u 3d -p 2               Also wake it at 2 more +1s
  sase bead snooze <id> --cancel                 Wake a snoozed task now
  sase bead close <id> --note "verified"         Close with completion evidence
  sase bead rm <id> [<id2> ...]                 Remove issues (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead dep list [<id>]                      Inspect dependency provenance
  sase bead dep tree [<id>]                      Follow dependency chains
  sase bead dep rm <issue> <depends-on> [...]    Remove dependency edges
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Stage bead state in git
  sase bead stats                                Project statistics
  sase bead doctor                               Health and reference checks
  sase bead doctor --fix-design-refs             Repair legacy plan links
  sase bead doctor --fix-issue-prefix            Reset a leaked ProjectSpec-key issue prefix
  sase bead doctor --fix-projection              Repair issues.jsonl drift
  sase bead work <target> [<target> ...]        Launch plan, epic, or task agents in order""")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())
