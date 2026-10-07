"""Bead onboarding help CLI command handler."""

from __future__ import annotations

import argparse


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Source of truth:
  Version-controlled projects use this checkout's sdd/beads/ event store.
  issues.jsonl remains a generated compatibility projection.
  Normal reads do not merge numbered sibling workspaces or legacy stores.

Quick Start:
  sase bead init                                 Create sdd/beads/ in current directory
  Agents: use /sase_new_task before creating any task bead
  sase bead create -t "Follow-up" --type 'task(bug)' --size small \\
      -w "A second agent reproduced this failure" \\
      -f location=src/foo.py -f repro='fails on retry'
                                                  Create a standalone typed draft task
  sase bead +1 <task-id> -n "Independent repro"  Corroborate an existing task
  sase bead create -t "Fix bug" --type phase(<plan-id>) -w "Epic plan defines this phase"
  sase bead create -t "New feature" --type plan(sdd/plans/202605/feature.md) --tier plan -w "Planning the feature breakdown"
  sase bead create -t "Epic" --type plan(sdd/plans/202605/epic.md) --tier epic -w "Planning the epic breakdown"
  sase bead list                                 List open/claimed/ready/in-progress issues
  sase bead task-type                            List agent-creatable task types
  sase bead task-type show flake                 Inspect one type's fields and template
  sase bead list --format=json                   Machine-readable listing
  sase bead list --limit=5                       Limit printed issues
  sase bead list --status=open                   List open issues
  sase bead list --status=closed                 List newest 20 closed issues (-n 0 for all)
  sase bead list --tier=epic                     List epic plan beads
  sase bead list --type=task --since=1w --status=all
                                                  Task beads created in the last week
  sase bead ready                                Show unblocked ready task beads
  sase bead read <id> -r "<why>"                 Audited agent read with a reason
  sase bead show <id>                            View issue details (human viewing)
  sase bead show <id> --format=json              Machine-readable bead detail
  sase bead show <epic-id>..                     Show an epic plus its direct children
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead open <id>                            Reopen an issue
  sase bead snooze <id> -u 3d -r "why"           Defer a task until a wake time
  sase bead snooze <id> -u 3d -p 2               Also wake it at 2 more +1s
  sase bead snooze <id> --cancel                 Wake a snoozed task now
  sase bead epic-symbols [<id>]                  List Justfile --epic-symbol entries
  sase bead close <id> --note "verified"         Close with completion evidence
  sase bead attach <id> ./shot.png -n "trace"    Attach a file snapshot (bytes kept on every machine)
  Attachments get an automatic audience: clean workspace files go public, the rest stays
  private. Pass -K for secrets; never pass -W as an agent — offer publish via /sase_gate
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
  sase bead doctor --fix-plan-archive            Archive recoverable missing plans
  sase bead doctor --fix-projection              Repair issues.jsonl drift
  sase bead doctor --fix-attachments             Repair attachment orphans and uploads
  sase bead doctor --verify-cache                Compare the read-model cache against replay
  sase bead work <target> [<target> ...]        Launch plan, epic, or task agents in order""")


__all__ = ["handle_bead_onboard"]
