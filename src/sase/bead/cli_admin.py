"""Administrative bead CLI command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

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
    with get_project() as proj:
        messages = proj.doctor(plan_roots)
        for msg in messages:
            print(msg)
        if not bool(getattr(args, "fix_design_refs", False)):
            return
        preview = plan_design_ref_repairs(
            proj.list_issues(),
            roots=plan_roots,
        )

    _render_design_ref_repair_preview(preview)
    if not preview.repairs:
        print("No design references can be repaired safely.")
        return
    if not _confirm_design_ref_repairs(len(preview.repairs)):
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
  sase bead create -t "Fix bug" --type phase(<plan-id>)
  sase bead create -t "New feature" --type plan(sdd/plans/202605/feature.md) --tier plan
  sase bead create -t "Epic" --type plan(sdd/plans/202605/epic.md) --tier epic
  sase bead list                                 List open/claimed/in-progress issues
  sase bead list --format=json                   Machine-readable listing
  sase bead list --limit=5                       Limit printed issues
  sase bead list --status=open                   List open issues
  sase bead list --status=closed                 List newest 20 closed issues (-n 0 for all)
  sase bead list --tier=epic                     List epic plan beads
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead show <id> --format=json              Machine-readable bead detail
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead close <id>                           Close an issue
  sase bead rm <id> [<id2> ...]                 Remove issues (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Stage bead state in git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check
  sase bead doctor --fix-design-refs             Repair legacy plan links
  sase bead work <epic-id>                       Launch epic phase agents""")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())
