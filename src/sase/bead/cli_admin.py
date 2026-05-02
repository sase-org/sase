"""Administrative bead CLI command handlers."""

from __future__ import annotations

import argparse
import sys

from sase.bead.cli_common import get_project


def handle_bead_dep(args: argparse.Namespace) -> None:
    if args.dep_action == "add":
        with get_project() as proj:
            dep = proj.add_dependency(args.issue, args.depends_on)
            print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_sync(args: argparse.Namespace) -> None:
    with get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ JSONL is in sync with git")
            else:
                print("○ JSONL has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced issues to git")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    with get_project() as proj:
        messages = proj.doctor()
        for msg in messages:
            print(msg)


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Quick Start:
  sase bead init                                 Create sdd/beads/ in current directory
  sase bead create -t "Fix bug" --type phase(<plan-id>)
  sase bead create -t "New feature" --type plan(sdd/plans/202605/feature.md) --tier plan
  sase bead create -t "Epic" --type plan(sdd/epics/202605/epic.md) --tier epic
  sase bead create -t "Legend" --type plan(sdd/legends/202605/roadmap.md) --tier legend
  sase bead create -t "Linked epic" --type plan(sdd/epics/202605/epic.md,<legend-id>) --tier epic
  sase bead list                                 List all issues
  sase bead list --status=open                   List open issues
  sase bead list --tier=epic                     List epic plan beads
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead close <id>                           Close an issue
  sase bead rm <id>                              Remove an issue (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Commit JSONL to git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check
  sase bead work <epic>                          Mark an epic-tier plan ready to work""")
