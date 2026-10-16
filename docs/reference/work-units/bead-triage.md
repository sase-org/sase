---
title: Bead triage
description: How bead dependencies, follow-ups, corroboration, and snoozes are handled.
---

# Bead triage

This page explains how SASE agents and people triage bead work and follow-ups.

## Standalone Task Workflow

Task beads separate collecting follow-up work from deciding whether to run it:

```
open (draft) ──mark ready──▶ ready (triage) ──launch──▶ in_progress ──close──▶ closed
                                  │
                                  └──close with reason──▶ closed (canceled)
```

1. Invoke `/sase_new_task`. It first checks for semantic duplicates and causally related
   in-progress epics. Only when neither exists does it create and refine a draft:

   ```bash
   sase bead create -T 'task(bug)' -t "Remove the compatibility shim" \
     -w "The new parser has shipped and the old path is still imported" \
     -d "Verify callers and remove the old path." \
     -z medium -f location=src/compat.py -f repro='old path still imported'
   sase bead note <task-id> "Found while landing sase-123"
   sase bead dep add <task-id> <blocking-bead-id>
   ```

   New task beads start `open`. While they are open, edit their title, description,
   notes, references, dependencies, optional model, and required size without creating a
   triage notification.

2. Offer the task for review:

   ```bash
   sase bead update <task-id> --status ready
   sase bead ready
   ```

   `sase bead ready` lists only task beads whose stored status is `ready` and whose
   dependencies are all closed. A task may remain stored as `ready` while blocked; it
   becomes visible to this command when the last blocker closes. The scheduled triage
   scan currently behaves differently, as described next.

3. Triage it. The default AXE `checks` routine scans enabled non-home projects every
   five minutes and creates one priority `TaskTriage` gate for each task whose stored
   status is `ready` and that has accumulated at least its
   [effective `+1` bar](beads.md#per-type-triage-bar) — its task type's own
   `triage.min_plus_ones` (`0` for `ci`, `feature`, and `memory`; `1` for `bug`; `3` for
   `flake`), or
   [`bead.task_triage.min_plus_ones`](../config/automation-behavior.md#bead) for an
   untyped or unregistered type. A sub-threshold task is withheld from triage — it stays
   stored as `ready` and stays visible to `sase bead ready` and this triage guide's
   other commands, only the gate is withheld — and a `TaskTriage` gate already raised
   for a task that later falls below the bar is canceled and its notification dismissed.
   This scan currently does not apply the dependency filter used by `sase bead ready`,
   so a blocked ready task can still receive a gate. The reviewed preview contains the
   task's title, description, and notes. **Launch** accepts optional feedback and
   submits one global unattributed proc that runs
   `sase bead work <task-id> --yes-to-all`; **Close** requires feedback and closes the
   bead with `resolution=canceled` and that feedback as the reason. The detached launch
   survives sase's TUI, CLI, Telegram, or mobile client exit and appears in
   `sase proc list` and sase's TUI Procs tab. **Snooze** requires a wake time, accepts
   an optional `+N` wake threshold and reason, and defers the task until either
   condition is met.

   Only one pending gate is kept per task. If the task leaves stored status `ready`, AXE
   cancels the pending gate. If a request is answered, canceled, or missing while the
   task is still `ready`, the next scan creates a new generation-specific request. The
   same happens if the task leaves `ready` and returns later. After the bead mutation
   commits, `sase bead close` makes a best-effort attempt to cancel a just-closed task's
   pending `TaskTriage` or `BeadSnooze` gate. A cancellation failure does not undo or
   fail the close; the next five-minute scan remains the backstop. Choosing **Launch**
   in that gate answers it through the normal gate workflow, and a successful launch
   submission from sase's TUI Beads pane explicitly cancels the matching gate. A direct
   `sase bead work` command changes the task's status but does not settle an existing
   gate itself; the scheduled scan remains its cleanup backstop.

4. Work it. You can bypass scheduled triage and launch directly:

   ```bash
   sase bead work <task-id> --dry-run
   sase bead work <task-id> --yes
   ```

   A direct launch accepts `open`, `ready`, or recoverable `in_progress` task beads. It
   rejects `claimed` and `closed` tasks, but currently does not reject a task with
   active dependency blockers. An `in_progress` task assigned to a live agent is an
   idempotent success with no second launch. If the assignee is stale, SASE previews
   and, after the required cleanup confirmation, force-reuses the deterministic
   task-agent name. `--yes` skips only the launch prompt; use `--yes-to-all` when
   stale-agent cleanup must also be non-interactive.

   Before spawning, SASE commits the `in_progress` status and `<task-id>` assignee and
   applies the same target synchronization safety as bead-ID epic launches. A checkpoint
   failure, or a dispatch failure before any worker is spawned, restores the task's
   prior status and assignee. A partial dispatch failure terminates the partial launch
   but preserves the `in_progress` assignment for recovery. The worker receives the task
   ID, description, and notes through the `work_task_bead` macro and is instructed to
   close the task with verification evidence. A successful `sase stitch create` commit
   or PR from the task worker's primary-repo workspace can close the assigned bead only
   when invoked with `-B close`; intermediate commits use `-B keep` — see
   [Explicit Bead Action](../../commit_workflows.md#explicit-bead-action).

5. Route the worker model. A task's explicit `model` wins. Otherwise a stored size
   selects the corresponding `@xsmall`, `@small`, `@medium`, `@large`, or `@xlarge`
   alias directly; a legacy task without size metadata uses `@small`. As with epic
   phases, `large` and `xlarge` task prompts add `#plan`, while smaller tasks implement
   directly.

## Snoozing a Task Bead

An `open` or `ready` task bead can be deferred instead of triaged immediately:

```bash
sase bead snooze <task-id> -u 3d
sase bead snooze <task-id> -u 2h -r "waiting on the upstream fix"
sase bead snooze <task-id> -u 7d -p 2
sase bead snooze <task-id> --cancel
```

`-u/--until` (a duration such as `30m`, `2h`, `1h30m`, `3d`, or an absolute ISO-8601
timestamp) is required unless `--cancel` is given; a non-positive duration or a past
absolute time is rejected. `-p/--plus-ones` adds a second wake condition: the bead also
wakes when that many **additional** `+1` reports arrive, whichever wake condition is
reached first. `-r/--reason` is optional free text. `--cancel` returns the bead to
`ready` immediately and clears the snooze record; the same happens automatically once a
wake condition fires.

Every successful snooze (including a re-snooze) appends one attributed note recording
the wake time, the deferral length, any `+1` target, and the reason, in the same store
mutation that sets `status: snoozed`. This is what preserves the "why and until when"
after a wake clears the snooze record — `sase bead show` only renders the `SNOOZE` block
while the bead is still snoozed, so the note is the only place a past deferral's
conditions survive. For example:

```text
[2026-08-07T13:21:54Z · bryanbugyi34@gmail.com] Snoozed until 2026-08-10T09:21:53-04:00 (in 3d). Reason: waiting on the upstream fix
```

`--cancel` appends no note of its own; it only clears the snooze record.

Snoozing always snoozes the bead's own notification in the same step — there is no
separate scheduler, and the bead's row stays visible in the notification panel's
`Snoozed` tab (see [Tabs and Ordering](../automation/notifications.md#tabs-and-ordering)
in the notifications doc) for the whole deferral. When the wake time arrives, the
notification resurfaces as a `BeadSnooze` gate with three options: **Close** (primary;
empty feedback uses a preset "stale, no new evidence" reason, any feedback text replaces
it), **Ready** (returns the bead to `ready`, where the ordinary `TaskTriage` gate takes
over), and **Snooze** (re-snoozes with one required `duration` line using the same
`"<wake-time> [+<N>]"` vocabulary as the `-u`/`-p` flags combined into one expression,
for example `3d`, `2026-08-09T09:00:00-04:00`, or `3d +2`; optional feedback remains the
deferral reason). Reaching the `+1` target instead of the wake time promotes the bead
straight to `ready` with a preset note (`"Reopened by +1 threshold: ..."`) and cancels
the pending `BeadSnooze` gate in favor of a fresh `TaskTriage` gate — the two gate kinds
are mutually exclusive, and a task bead never holds more than one pending gate at a
time.

A ready task can also be snoozed directly from its `TaskTriage` gate's **Snooze**
option, without a separate CLI call; it uses the same required `duration` line and keeps
optional feedback separate as the reason — the most common time to defer a task is
exactly when the triage gate is already in front of you.

`status:snoozed` and `-status:snoozed` work as query and filter tokens like any other
status. The default bead-list filter (`-status:closed`) does **not** hide snoozed beads:
a snoozed task is still live work the user chose to defer, not a black hole.
`sase bead list --status snoozed` / `sase bead search --status snoozed` filter to just
those beads.

Beads-pane query property values also accept `*` wildcards: `id:sase-16n.*` lists an
epic's phases (see [Wildcards](../../query_language.md#wildcards)). `sase bead search`
is not a property query: its argument stays a literal substring (or `--regex` pattern).

## Task Corroboration (+1)

`sase bead +1` records one additional independently attributed report of the same
actionable task. It is evidence, not a generic vote: duplicates share the same
underlying defect/root cause or desired remediation, rather than merely a subsystem or
similar symptom.

```bash
sase bead +1 <task-id> --note "<independent reproduction and impact>"
sase bead +1 <task-id> --note "<independent evidence>" --ref <artifact-ref>
```

The note is required, artifact refs are repeatable, and `--author` supports explicit
attribution. Each reporter counts at most once, and the task creator does not count as
an additional reporter; a retry is an unchanged no-op that points the reporter to
`sase bead note` for supplementary evidence. The evidence entries—not a mutable
counter—derive the visible total and machine-readable `plus_one_count`.

Adding new evidence to an `open` draft atomically promotes it to `ready`. A closed task
reopens and promotes only when the reporter's observation window starts strictly after
the current close. SASE CLI callers derive that window from the current agent's
`agent_meta.json` `run_started_at`; human callers and `--verified-after-close` use the
current instant. Non-CLI callers that omit `observed_since` preserve the legacy
closed-task reopen behavior.

If the report was already in flight before the close, the evidence is still recorded but
the close remains standing. The command prints that the reopen was withheld, appends a
durable note naming the standing close, and surfaces the entry as post-close evidence.
Use `--verified-after-close` only for an actual reproduction on a tree that already
contains the close. A `claimed`, `ready`, `in_progress`, or `snoozed` task keeps its
existing status behavior. The same mutation attaches normalized artifact refs, and
plan/phase targets are rejected without writing.

## Close History

A bead remembers how it was closed even after a later reopen undoes that close. The
_current_ close, when a bead is closed right now, stays exactly where it has always
lived: the flat `closed_at`, `close_reason`, and `resolution` fields. `close_history` is
strictly the past — an append-only, oldest-first list of close episodes that have since
been undone. This applies to every bead type, including flag-typed task beads, not just
ordinary tasks: non-task beads are reopened by `sase bead open` and by epic work
preclaims, and "why was this closed before?" is the same useful question there too.

Each record captures one undone close:

| Field          | Description                                                |
| -------------- | ---------------------------------------------------------- |
| `closed_at`    | When the archived close happened                           |
| `close_reason` | The free-text reason recorded on that close, if any        |
| `resolution`   | `done`, `canceled`, or `superseded`, if recorded           |
| `reopened_at`  | When the close was undone                                  |
| `reopened_via` | `plus_one`, `open`, `update`, or `epic_preclaim`           |
| `reopened_by`  | Who reopened it, populated only for `plus_one` (see below) |

A record is created whenever a closed bead leaves `closed`: a qualifying fresh
`sase bead +1` on a closed task (`plus_one`), `sase bead open` (`open`),
`sase bead update --status` moving a bead away from `closed` (`update`), and an epic
work preclaim relaunching a previously-closed phase or epic (`epic_preclaim`). Stale
post-close `+1` evidence is retained on the still-closed task and does not archive the
current close into history. Reopening a bead that was never closed adds no record. A
bead closed, reopened, and closed again accumulates one record per undone close;
`sase bead show` renders them newest first.

`reopened_by` is populated only for `plus_one` reopens, because `add_task_plus_one` is
the one reopen path whose event actor is genuinely the agent that ran the command —
`sase bead close`/`open`/`update`'s mutations currently attribute their events to the
bead's creator rather than the acting agent, which is a separate, known defect.
Recording a `reopened_by` from those paths would confidently print the wrong name, so it
is left unpopulated there instead.

Because the canonical event log already recorded every close and reopen, existing stores
recover close reasons that a reopen previously destroyed **automatically**, the next
time their events are reduced (for example, on the next mutation, or with
`sase bead doctor --fix-projection`) — no backfill script is needed.

Every surface that shows a bead's status also shows its reopen history:

- The `↺N` badge sits next to the `+N` corroboration badge on `sase bead show`,
  `sase bead list`, `sase bead ready`, `sase bead blocked`, `sase bead search` rows, the
  sase's TUI beads pane, and the generated bead page lineage roster.
- A closed task with stale post-close evidence shows a `+1 after close` badge next to
  its normal `+N` corroboration badge; the same post-close marker appears in sase's TUI,
  generated bead pages, and task-triage previews.
- `sase bead show --format full` renders a `PREVIOUSLY CLOSED` section — placed where
  `RESOLUTION` sits, above `DESCRIPTION` — with one entry per record, newest first, and
  the `+1 EVIDENCE` entry that reopened the bead marked with `↺ reopened this task`.
- `sase bead show --format json` (and other JSON-emitting bead commands sharing the same
  issue schema) include `close_history` on the issue object. Each `plus_one_evidence`
  entry carries `observed_since` when provenance was provided, a derived
  `recorded_after_current_close` boolean for post-close evidence, and a derived
  `reopened_bead` boolean for the `+1` entry that actually reopened the task.
- `sase bead search` indexes archived close reasons, resolutions, and timestamps, so a
  reason recorded before a reopen is still findable.
- sase's TUI beads pane shows the `↺N` badge on list rows, a "Previously closed"
  property and a `## Previously Closed` body section in the detail pane, and a
  `has:reopened` filter label.
- Generated bead pages render a `## Previously Closed` section and a `**↺ Reopened:**`
  primary fact.
- The `TaskTriage` gate preview — the highest-value surface, since **Launch** is its
  default decision — renders one `> [!WARNING]` callout per record above the
  description, newest first, and adds the `↺N` badge to its notification note. A typed
  task's preview also includes a `**Task type:**` fact in the metadata block above
  `## Description`, for example `**Task type:** ≈ \`flake\``.

## Dependencies

Dependencies are one-way relationships: issue A **depends on** issue B. Every edge
records the source issue, the target issue, when the edge was added, and who added it.
An issue is:

- **Unblocked** if all its dependencies are `closed`.
- **Shown by `sase bead ready`** if it is a task with stored status `ready` and all
  dependencies are `closed`.
- **Blocked** if it has at least one dependency with status `open`, `claimed`, `ready`,
  or `in_progress`.

`sase bead dep list` prints the forward `DEPENDS ON` view, the reverse `BLOCKS` view, or
both, including the edge's provenance in `--format full`. `sase bead dep tree` walks the
same graph when a one-level detail view is not enough. Removing a dependency appends a
`dependency_removed` event rather than editing or erasing the original add event, so
history keeps both the mistake and its correction.

## Discovered Follow-Up Capture and Triage

Unless a prompt forbids bead creation, agents should run `/sase_new_task` for useful
work discovered outside their current scope. The skill searches every task status and
all in-progress epic plans before allowing a new task:

```bash
sase bead create -T 'task(flake)' -t "Fix flaky integration test" \
  -w "The retry test flakes under parallel pytest" \
  -d "Discovered while landing sase-xy." \
  --size small -f node_id=tests/retry.py::test_retry -f evidence='failed then passed'
sase bead update <task-id> -s ready
```

For a semantic duplicate, the skill uses `sase bead +1` and does not create a task. When
an in-progress epic credibly caused the issue—not merely shares its topic—the skill
records a `DISCOVERED ISSUE:` note on that epic and does not create a task. Both records
are made when both cases apply. Only a genuinely distinct issue becomes a sized draft.

Duplicate detection is not text search alone: the skill also sweeps
`sase bead list --type task --since 1w --status all` before drafting, because a
duplicate filed hours ago by another agent often shares no term with your query. If the
closest match is a closed task whose close reason declares it retired and forbids `+1`
(a "retired umbrella"), the skill does not corroborate or reopen it — it routes the
reporter to a new, node-specific task bead instead, then records a typed `related`
artifact link back to the retired umbrella.

The task stays `open` while its title, description, size, model, references, and
dependencies are drafted. Marking it `ready` proposes it to the project owner. The
`bead_task_triage` job scans enabled projects every five minutes and raises one
human-only `TaskTriage` gate per ready task bead that has accumulated at least its
[effective `+1` bar](beads.md#per-type-triage-bar) — its task type's own
`triage.min_plus_ones`, or
[`bead.task_triage.min_plus_ones`](../config/automation-behavior.md#bead) for an untyped
or unregistered type. A sub-threshold task is withheld from triage without any change to
its stored status, and a gate already raised for a task that later falls below the bar
is canceled and its notification dismissed. The compact `[bead] <bead-id> — <title>`
notification lands in the `Beads` panel. Every gate whose subject is a typed task bead
also carries a type chip (glyph + slug) and a second note with the compact typed facts
line. The Markdown preview's metadata block includes a **Task type** fact such as
`**Task type:** ≈ flake` next to **Size** and **References**. The filing agent travels
with the gate into its Markdown preview when that attribution is known. The job records
pending gates in lane state so later ticks do not repeat the notification, cancels a
pending gate if the bead leaves `ready` or falls below the `+1` bar, defers re-gating
while that task bead's detached launch is still in flight, and uses a new deterministic
generation if the same task becomes ready again or its pending gate needs a
presentation-contract refresh.

The hourly `bead_stale_cleanup` job is the other half of that bar. Sub-threshold ready
task beads stay `ready` and stay visible here; they are not closed automatically. Once
at least
[`bead.task_triage.stale_cleanup_min_beads`](../config/automation-behavior.md#bead) of
them have been below the bar for
[`bead.task_triage.stale_after_days`](../config/automation-behavior.md#bead) days, one
`BeadStaleCleanup` gate offers the oldest 50 (naming any remainder) so the reviewer can
close a selected subset as `canceled`. The job keeps a single pending gate and cancels
it when the backlog drops below the bar. See
[Stale Task Cleanup Notification](../automation/notification-types.md#stale-task-cleanup-notification)
and the
[housekeeping lane](../automation/scheduler-housekeeping.md#housekeeping-1-hour-interval).

The gate offers three decisions:

- **Launch** (default) submits an unattributed proc that runs
  `sase bead work <task-id> --yes-to-all`. Optional feedback is appended to the worker
  prompt.
- **Close** requires feedback and closes the task with that reason and
  `resolution=canceled`.
- **Snooze** requires a wake time, accepts an optional `+N` wake threshold and reason,
  and moves the task to `snoozed`. The next reconciliation replaces the settled triage
  gate with a snoozed `BeadSnooze` gate.

Epic phase workers follow a stricter capture rule: they do not create beads. Instead, a
phase worker appends `PROPOSED FOLLOW-UP: <one-line summary — detail>` to its own bead
with `sase bead note`. The epic land agent collects those notes, files the worthwhile
proposals as `task` beads, marks them `ready`, and records why it declined any others.

## Related

- [Beads](beads.md)
- [Bead CLI](bead-cli.md)
