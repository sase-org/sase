---
title: Bead TUI integration
description: How SASE's TUI connects bead records with plans and task work.
---

# Bead TUI integration

This page describes the bead surfaces and plan links in SASE's TUI.

## sase's TUI Integration {#ace-tui-integration}

### Plan File Linking

When creating a plan bead with `--type plan(PATH)`, the file path is stored in the
`design` field. sase's TUI can navigate from a bead to its linked SDD file.

For SDD-generated epics, `PATH` should be the shared plan reference emitted by the plan
approval flow: `sdd/plans/...` in in-tree mode, `.sase/sdd/plans/...` in local and
separate-repo modes, or `<YYYYMM>/...` in the split `--plans` repository. SASE resolves
those references against the effective SDD root when launching bead work. For manual
commands and prompts, `SASE_SDD_PLANS_DIR` or `sase repo path plans` is less ambiguous
than guessing which relative prefix applies.

### Task Bead Surfaces

sase's TUI Artifacts → Plans pane renders standalone task beads in their own section
with an orchid `◆` type marker and mint `◇ ready` state. The detail view labels the type
as `task`. The `s` action only changes status; it cycles a task through
`open → ready → in_progress → closed → open` (`claimed → ready`) but does not launch a
worker when it reaches `in_progress`. The `e` action edits its title and description.
The filing reason stays as filed. `n` creates a task and requires that reason in the
modal. `w` launches an open or ready task immediately, and asks before launching an epic
that has phase beads. A phase row says to launch the epic instead. Closed beads, blocked
epics, and epics with no phases are refused with a toast. The same launch is also
available from a `TaskTriage` notification or `sase bead work <task-id>`.

Generated bead pages and the mobile bead bridge expose the same literal type and status.
Default non-closed mobile listings include ready tasks. sase's TUI task detail exposes
stored metadata and each dependency's status, but it does not show a reverse blocker
list. When task design metadata is present, the pane shows its plan reference without
loading the linked document. Its shared phase/task presentation also shows the `small`
fallback for a task with no stored size.

### Plan Approval Flow

The plan approval popup in sase's TUI includes normal approval and **E** (Epic) actions.
Normal approval saves to the resolved SDD `plans/` directory with `tier: tale`. Every
epic approval surface behaves the same way — sase's TUI,
`sase plan approve --kind epic`, Telegram, and bare gate responses all hand
`sase bead work <plan-file> --yes-to-all` to a detached supervisor that runs it from the
project's primary workspace, then record that the host owns the launch in the planner
response. Epic Custom Approval exposes an optional Capacity control (`c`) beside Wait:
blank (Default) means omission; an explicit value must be at least 1, and `1` runs
alone. The durable approve result retains that integer so launch argv can emit
`--capacity N`; tale, reject, and feedback actions never submit it.

The preferred handoff is a [monitor](../automation/monitors.md) turn under the planner's
own agent session, labeled `Epic launch · <plan>`. The monitor turn reads
`EPIC APPROVED` while `sase bead work` runs. After any terminal outcome its configured
label is `EPIC CREATED`, including when the monitor failed, timed out, was stopped, or
was lost; the monitor's state, bucket, exit code, and output—not that label—show whether
the command succeeded. A successful launch separately attempts to back-fill the created
epic ID; when that metadata lands, the planner row moves to `EPIC CREATED`, and
otherwise the planner remains `EPIC APPROVED`. No follow-up agent is recorded because
`sase bead work` launches the phase agents itself. The monitor takes a zero workspace
claim rather than the planner's, since the launch runs in the primary workspace. When
the planner's agent session cannot be resolved, the same command is submitted as one
deduplicated global `detached` proc instead.

Either handoff is durable and unowned by any interactive session: it survives the
approving process, and normal command success or failure emits the epic-completion
notification. For a monitor handoff, that notification is held until the monitor turn
itself settles, so opening it shows the settled monitor rather than a running one. If
the process that settles the monitor dies before sending it, monitor reconciliation or
the `epic_launch_flush` AXE job publishes it later, at most once. Inspect a monitor
through `sase monitor list` / `sase monitor show <id> --follow`, and the proc fallback
through every default `sase proc list` and Procs-tab scope,
`sase proc show <id> --follow`, and `sase proc kill`. The approval passes
`--artifacts-dir`, `--capacity N` when the durable result set an explicit capacity, and
`--cl-name` when a Patch is involved, so a successful launch attempts to back-fill the
epic ID and committed plan path into planner metadata.

There is no planner-side subprocess fallback and no foreground path. An absent or
unresolvable planner agent session selects the detached-proc fallback; other
monitor-start errors do not. If the host cannot resolve the primary workspace, finds the
approved-epic plans store unusable, or cannot submit the selected handoff, approval
fails loudly and reports the `sase bead work <plan> --yes-to-all` resume command rather
than launching invisibly. Immediately after a successful handoff, the planner publishes
its prompt archive entry, finishes as `EPIC APPROVED`, and does not race the command for
ownership of the epic plan file.

## Related

- [Beads](beads.md)
- [Starting bead work](bead-work.md)
