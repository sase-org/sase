"""Administrative bead CLI command handlers."""

from __future__ import annotations

import argparse
import sys

from sase.bead.conflict_resolver import handle_resolve_conflicts_command
from sase.bead.cli_common import auto_commit_bead_store, get_project


def handle_bead_dep(args: argparse.Namespace) -> None:
    if args.dep_action == "add":
        with get_project() as proj:
            dep = proj.add_dependency(args.issue, args.depends_on)
        auto_commit_bead_store(
            f"chore(beads): link {dep.issue_id} -> {dep.depends_on_id}"
        )
        print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


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
    with get_project() as proj:
        messages = proj.doctor()
        for msg in messages:
            print(msg)


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
  sase bead list                                 List open/in-progress issues
  sase bead list --limit=5                       Limit printed issues
  sase bead list --status=open                   List open issues
  sase bead list --status=closed                 List newest 20 closed issues (-n 0 for all)
  sase bead list --tier=epic                     List epic plan beads
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead close <id>                           Close an issue
  sase bead rm <id>                              Remove an issue (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Stage bead state in git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check
  sase bead work <epic-id>                       Launch epic phase agents""")


def handle_bead_resolve_conflicts(args: argparse.Namespace) -> None:
    raise SystemExit(handle_resolve_conflicts_command())
