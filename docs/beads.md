# Bead Issue Tracking

Bead is a lightweight, git-native issue tracking system built into sase. It uses
Rust-backed event storage, query/reduction, and mutation logic through the required
`sase_core_rs` extension, with generated JSONL compatibility projections for older
tooling (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into
plan-like containers, executable child phases, and standalone task beads for discovered
follow-up work. Plan beads can represent ordinary plans or executable epics through
their `tier` metadata; task beads capture independent work that does not need an epic
DAG.

## Table of Contents

- [Quick Start](#quick-start)
- [Bead ID Arguments](#bead-id-arguments)
- [Data Model](#data-model)
  - [Issue Types](#issue-types)
  - [Status Lifecycle](#status-lifecycle)
  - [Bead Claim Lifecycle](#bead-claim-lifecycle)
  - [Standalone Task Workflow](#standalone-task-workflow)
  - [Snoozing a Task Bead](#snoozing-a-task-bead)
  - [Task Corroboration (+1)](#task-corroboration-1)
  - [Close History](#close-history)
  - [Dependencies](#dependencies)
  - [Discovered Follow-Up Capture and Triage](#discovered-follow-up-capture-and-triage)
  - [Artifact References](#artifact-references)
  - [Creation Time Presentation](#creation-time-presentation)
- [Storage](#storage)
  - [Directory Structure](#directory-structure)
  - [Event Log + Compatibility Projections](#event-log-compatibility-projections)
  - [Sync Mechanism](#sync-mechanism)
    - [Publication Verification](#publication-verification)
    - [Duplicate Bead IDs](#duplicate-bead-ids)
- [Bead Pages](#bead-pages)
- [CLI Commands](#cli-commands)
- [Rust Backend](#rust-backend)
- [Current Checkout Source Of Truth](#current-checkout-source-of-truth)
- [ACE TUI Integration](#ace-tui-integration)

## Quick Start

```bash
PLANS_ROOT=$(sase repo path plans)
sase bead init                                          # Initialize beads in current project
sase bead create -t "New feature" --type "plan(${PLANS_ROOT}/202605/feature.md)" --tier plan
sase bead create -t "Epic" --type "plan(${PLANS_ROOT}/202605/epic.md)" --tier epic
sase bead create -t "Sub-task" --type "phase(beads-001)" --size small # Create a sized epic phase
sase bead create -t "Fix flaky test" --type task --size small # Create a standalone draft task
sase bead +1 beads-002 --note "Independent reproduction" # Corroborate an existing task
sase bead update beads-002 --status=ready               # Offer the task for human triage
sase bead list                                          # List open, claimed, ready, snoozed, and in-progress issues
sase bead list --status=open                            # List open issues
sase bead list --status=ready --type=task                # List tasks awaiting triage
sase bead list --status=closed                          # List closed issues
sase bead search auth                                   # Search issues in every status
sase bead ready                                         # Show unblocked ready task beads
sase bead show beads-001                                # View issue details
sase bead ref add beads-001 research:202607/report.md   # Attach durable context
sase bead ref list beads-001 --resolve                  # List references and resolution state
sase bead ref rm beads-001 research:202607/report.md    # Detach a reference
sase bead update beads-001.1 --status=in_progress       # Claim an issue
sase bead note beads-001.1 "Verified with just check"   # Append an attributed note
sase bead open beads-001.1                              # Reopen an issue
sase bead close beads-001.1                             # Close an issue
sase bead dep add beads-001.2 beads-001.1               # Add dependency
sase bead dep list beads-001.2 --format full            # Inspect dependency provenance
sase bead dep tree beads-001.2                          # Follow the blocking chain
sase bead dep rm beads-001.2 beads-001.1                # Remove a wrong dependency
sase bead blocked                                       # Show blocked issues
sase bead sync                                          # Export and stage JSONL in git
sase bead pages refresh                                # Preview regenerated bead pages
sase bead pages refresh --write                        # Regenerate, commit, and push bead pages
sase bead pages url beads-001.1                        # Print the hosted page URL when available
sase bead stats                                         # Project statistics
sase bead doctor                                        # Health check
sase bead doctor --fix-issue-prefix                     # Reset a leaked ProjectSpec-key issue prefix
sase bead doctor --fix-projection                       # Repair issues.jsonl from canonical events
sase bead work "$PLANS_ROOT/202605/epic.md" --dry-run   # Preview bead creation and launch waves
sase bead work "$PLANS_ROOT/202605/epic.md" --yes       # Create, link, and launch an epic plan
sase bead work beads-001                                # Launch agents for an epic plan bead
sase bead work beads-002 --dry-run                      # Preview one standalone task worker
sase bead work beads-002 --yes                          # Launch one standalone task worker
```

## Bead ID Arguments

Every `sase bead` command argument that names an existing bead accepts either the full
ID or its shorthand suffix after the final dash. For example, `sase bead show 001`
resolves to `beads-001`, and dotted descendants work the same way:
`sase bead close 001.2` resolves to `beads-001.2`. Output, events, dependencies,
reference ownership, commit summaries, agent names, generated page paths, and JSON
payloads always use the canonical full ID.

Full IDs are still accepted unchanged, including IDs whose project prefix contains
dashes. If a shorthand suffix matches more than one bead, SASE rejects the command and
lists the candidate full IDs instead of choosing one arbitrarily.

## Data Model

### Issue Types

| Type      | Description                                                    | ID Format                                 |
| --------- | -------------------------------------------------------------- | ----------------------------------------- |
| **Plan**  | Plan-like container with a tier; may be a child epic           | `{prefix}-{counter}` or `{parent_id}.{N}` |
| **Phase** | Sized executable child within an epic/plan bead                | `{parent_id}.{N}`                         |
| **Task**  | Independent, explicitly sized work item with no parent or tier | `{prefix}-{counter}`                      |

Plans are groupings that can optionally link to an SDD file via the `design` field.
Phases always belong to a parent plan and use hierarchical IDs (e.g., `beads-001.1`,
`beads-001.2`). Task beads are top-level, carry neither a parent nor a tier, and require
a size when newly created. An epic proposed by a phase or land agent becomes a child
plan bead beneath the bead responsible for that agent. For example, phase `beads-001.2`
can own child epic `beads-001.2.1`; an epic proposed by the land agent can become the
next direct child such as `beads-001.3`.

Task beads are deliberately flat: the task creation form takes no plan path or parent
ID, and a task cannot carry a plan tier or ChangeSpec metadata. Use a task for
independent follow-up work that one worker can own. Use an epic and phase beads when the
work needs a validated plan, dependency waves, or a final land agent.

The generic `sase bead update <task-id> --design <path>` command currently accepts
design metadata on a task, even though task creation does not. That metadata does not
give the task a parent or make task launch plan-backed: `sase bead work` still sends the
task description and notes to one worker. ACE's Plans pane shows the stored reference
but does not load its document into the task detail.

Plan beads carry a tier. The paths below are relative to the effective plans root. Use
`sase repo path plans` or `SASE_SDD_PLANS_DIR` to locate it without depending on the
storage layout.

| Tier   | Plans-root path | Behavior                                           |
| ------ | --------------- | -------------------------------------------------- |
| `plan` | `{YYYYMM}/*.md` | Normal non-epic implementation plan (`tier: tale`) |
| `epic` | `{YYYYMM}/*.md` | Executable multi-phase plan (`tier: epic`)         |

Epics use the plan syntax:

```bash
sase bead create --title "Epic" --type "plan(${SASE_SDD_PLANS_DIR}/202605/epic.md)" --tier epic
```

### Status Lifecycle

| Status        | Icon | Description                                                               |
| ------------- | ---- | ------------------------------------------------------------------------- |
| `open`        | `○`  | Not started; for task beads, still a draft that is not offered for triage |
| `claimed`     | `◎`  | Reserved by a live agent that has not started work                        |
| `ready`       | `◇`  | Task bead explicitly offered for triage; invalid for plan and phase beads |
| `snoozed`     | `◈`  | Task bead deferred to a wake time (or +1 target); invalid for plan/phase  |
| `in_progress` | `◐`  | Being worked on, or preassigned by an epic/task launch checkpoint         |
| `closed`      | `✓`  | Completed, canceled, or superseded                                        |

Status can transition between values via `sase bead update --status=<status>`. A task
normally moves `open → ready` when its draft is proposed, `ready → open` when retracted,
and `ready → in_progress` when launched. Only task beads may carry `ready`; set it after
the title, description, notes, dependencies, and any desired size or model are ready for
human review. Moving a bead to `closed` is rejected while any descendant remains open,
claimed, ready, snoozed, or in progress. Close those descendants deliberately first;
`update --status=closed` never cascades. `sase bead open <id>` reopens the bead and
every closed ancestor above it, archiving their resolution, close reason, and close
timestamp into [close history](#close-history) instead of discarding them, so a closed
parent never sits above reopened work but the reason it was closed is not lost either.
`claimed` is machine-managed by the agent runner (see
[Bead Claim Lifecycle](#bead-claim-lifecycle)); do not set it by hand. `snoozed` cannot
be set through `update --status` either — snoozing requires a wake time, so
`sase bead update -s snoozed` is refused with a pointer to `sase bead snooze`, the same
way `update --status=closed` points at `sase bead close`. See
[Snoozing a Task Bead](#snoozing-a-task-bead) for the full workflow.

Every new close records a typed `resolution`: `done`, `canceled`, or `superseded`.
Normal closes default to `done`; `close_reason` remains optional free text for the human
explanation. Closing an already-closed bead is a verified no-op: the command succeeds
when any supplied reason or resolution agrees with the recorded close, and fails without
writing when the request conflicts. Historical closed beads are not backfilled, so their
resolution remains unset and human-readable detail views show `(unrecorded)`.

### Bead Claim Lifecycle

An agent launched with `%id(<name>, bead=<id>)` reserves its bead before it starts
working, so a bead is never silently owned by a process that nothing else can see:

```
open ──claim──▶ claimed ──promote──▶ in_progress ──close──▶ closed
  ▲                │
  └────release─────┘        (claim owner died before launching)
```

- **Claim.** When a bead-carrying agent enters a wait phase (dependency `%wait`,
  runner-slot, or duration waits), the runner sets the bead to `claimed` and assigns it
  to the agent name. Claims are written to the project's canonical bead store, committed
  locally, and then published synchronously on a best-effort basis so other hosts can
  see the claim: the runner runs the managed sync worker for that store right after the
  commit lands. Publication never rolls a claim back — a missing git repo or missing
  remote is a silent local-only outcome, and a real sync failure only prints a warning
  with the managed-sync log path while the local commit stands. Claiming is advisory: it
  never blocks or fails an agent launch, and a straight-through launch with no waits
  skips it entirely. Because it is advisory, the claim is acquired **best-effort**: the
  runner retries a bounded number of times (refreshing the canonical store once when the
  bead is not there yet, which is normal right after an epic graph is published), and
  whatever it fails to acquire is picked up by the `bead_claim_checks` reconciler. A
  bead can therefore turn `claimed` a few seconds after its agent starts waiting rather
  than instantly.
- **Promote.** Immediately before model execution the runner performs the existing
  just-in-time claim, which sets `status=in_progress` and assigns the runner name.
  Promotion is what makes the claim permanent; from that point the claim is never
  released automatically. In managed standalone SDD stores the promotion must produce a
  local commit and is published the same best-effort way before model execution; in
  in-tree stores the agent commits the promotion along with its implementation instead.
- **Release.** If the owning agent dies before it ever promoted its claim, the bead
  returns to `open` with an empty assignee. The runner shutdown path releases the claim
  on ordinary kills (except when a retry handoff is pending, which keeps the claim), and
  the `bead_claim_checks` chop is the backstop for SIGKILL, crashes, and reboots. It
  releases a claim only when the owning agent is dead, never promoted, and resolvable to
  its artifact; anything else is left untouched and reported by `sase doctor` instead. A
  committed release is published the same best-effort way as a claim, so a freed bead
  does not stay claimed on other hosts.
- **Reconcile.** The `bead_claim_checks` chop — registered under the `waits` lumberjack
  — runs in both directions. Next to the release pass above, an acquire pass claims a
  bead on behalf of a live agent that is waiting without a claim, which is what makes a
  lost or delayed claim self-healing within one `waits` interval. A held claim is
  recorded in the agent's `bead_claim.json` artifact file, so an agent that already
  holds its claim costs the chop nothing: it is filtered out without opening a bead
  store. `sase doctor` reports the residue in either direction — a claim with no
  resolvable owner, and a live pre-launch agent whose bead is still `open`.

Claim and release are compare-and-swap operations: a claim succeeds only from `open`
(re-claiming your own claim is a no-op), and a release succeeds only when the bead is
still `claimed` by the releasing agent. Both decline silently rather than overwriting
someone else's state, so all three layers are safe to run concurrently.

The diagram above describes an ordinary bead-carrying agent. `sase bead work` uses a
stronger batch checkpoint: before spawning any epic worker, it sets every scheduled
phase to `in_progress` with its deterministic worker as assignee and does the same for
the epic and land worker. The later runner-side wait claim and launch promotion become
idempotent no-ops. Scheduling still ignores bead status and decides from agent liveness
(artifacts and PID checks), so a retry can schedule preassigned work without creating a
duplicate name.

Task-bead launches use the same strong checkpoint principle for one worker:
`sase bead work <task-id>` assigns the task to the deterministic agent name `<task-id>`,
sets it to `in_progress`, commits that state, synchronizes it unless `--no-push` was
requested, and only then spawns the worker. A task launched through this path therefore
does not pass through the advisory `claimed` state.

### Standalone Task Workflow

Task beads separate collecting follow-up work from deciding whether to run it:

```
open (draft) ──mark ready──▶ ready (triage) ──launch──▶ in_progress ──close──▶ closed
                                  │
                                  └──close with reason──▶ closed (canceled)
```

1. Invoke `/sase_new_task`. It first checks for semantic duplicates and causally related
   in-progress epics. Only when neither exists does it create and refine a draft:

   ```bash
   sase bead create -T task -t "Remove the compatibility shim" \
     -d "The new parser has shipped; verify callers and remove the old path." \
     -z medium
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

3. Triage it. The default AXE `checks` lumberjack scans enabled non-home projects every
   five minutes and creates one priority `TaskTriage` gate for each task whose stored
   status is `ready`. This scan currently does not apply the dependency filter used by
   `sase bead ready`, so a blocked ready task can still receive a gate. The reviewed
   preview contains the task's title, description, and notes. **Launch** accepts
   optional feedback and submits one global detached background task that runs
   `sase bead work <task-id> --yes-to-all`; **Close** requires feedback and closes the
   bead with `resolution=canceled` and that feedback as the reason. The detached launch
   survives ACE, CLI, Telegram, or mobile client exit and appears in `sase task list`
   and ACE's Tasks tab.

   Only one pending gate is kept per task. If the task leaves stored status `ready`, AXE
   cancels the pending gate. If a request is answered, canceled, or missing while the
   task is still `ready`, the next scan creates a new generation-specific request. The
   same happens if the task leaves `ready` and returns later. Normally a launch or close
   changes the bead state before the next five-minute scan.

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
   ID, description, and notes through the `work_task_bead` xprompt and is instructed to
   close the task with verification evidence.

5. Route the worker model. A task's explicit `model` wins. Otherwise a stored size
   selects the corresponding `@xsmall_phase_worker`, `@small_phase_worker`,
   `@medium_phase_worker`, `@large_phase_worker`, or `@xlarge_phase_worker` alias; a
   legacy task without size metadata uses `@small_phase_worker`. As with epic phases,
   `large` and `xlarge` task prompts add `#plan`, while smaller tasks implement
   directly.

### Snoozing a Task Bead

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
`Snoozed` tab (see [Tabs and Ordering](notifications.md#tabs-and-ordering) in the
notifications doc) for the whole deferral. When the wake time arrives, the notification
resurfaces as a `BeadSnooze` gate with three options: **Close** (primary; empty feedback
uses a preset "stale, no new evidence" reason, any feedback text replaces it), **Ready**
(returns the bead to `ready`, where the ordinary `TaskTriage` gate takes over), and
**Snooze** (re-snoozes with one required `duration` line using the same
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

### Task Corroboration (+1)

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

Adding new evidence to an `open` draft or `closed` task atomically promotes it to
`ready`. If the task was `closed`, its close metadata is archived into
[close history](#close-history) rather than discarded, and the `+1 EVIDENCE` entry that
did the reopening is marked. A `claimed`, `ready`, or `in_progress` task keeps its
status. The same mutation attaches normalized artifact refs, and plan/phase targets are
rejected without writing.

### Close History

A bead remembers how it was closed even after a later reopen undoes that close. The
_current_ close, when a bead is closed right now, stays exactly where it has always
lived: the flat `closed_at`, `close_reason`, and `resolution` fields. `close_history` is
strictly the past — an append-only, oldest-first list of close episodes that have since
been undone. This applies to every bead type (task, phase, and plan), not just tasks:
phases and plans are reopened by `sase bead open` and by epic work preclaims, and "why
was this closed before?" is the same useful question there too.

Each record captures one undone close:

| Field          | Description                                                |
| -------------- | ---------------------------------------------------------- |
| `closed_at`    | When the archived close happened                           |
| `close_reason` | The free-text reason recorded on that close, if any        |
| `resolution`   | `done`, `canceled`, or `superseded`, if recorded           |
| `reopened_at`  | When the close was undone                                  |
| `reopened_via` | `plus_one`, `open`, `update`, or `epic_preclaim`           |
| `reopened_by`  | Who reopened it, populated only for `plus_one` (see below) |

A record is created whenever a closed bead leaves `closed`: `sase bead +1` on a closed
task (`plus_one`), `sase bead open` (`open`), `sase bead update --status` moving a bead
away from `closed` (`update`), and an epic work preclaim relaunching a previously-closed
phase or epic (`epic_preclaim`). Reopening a bead that was never closed adds no record.
A bead closed, reopened, and closed again accumulates one record per undone close;
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
  ACE beads pane, and the generated bead page lineage roster.
- `sase bead show --format full` renders a `PREVIOUSLY CLOSED` section — placed where
  `RESOLUTION` sits, above `DESCRIPTION` — with one entry per record, newest first, and
  the `+1 EVIDENCE` entry that reopened the bead marked with `↺ reopened this task`.
- `sase bead show --format json` (and other JSON-emitting bead commands sharing the same
  issue schema) include `close_history` on the issue object, and each
  `plus_one_evidence` entry carries a derived `reopened_bead` boolean.
- `sase bead search` indexes archived close reasons, resolutions, and timestamps, so a
  reason recorded before a reopen is still findable.
- The ACE beads pane shows the `↺N` badge on list rows, a "Previously closed" property
  and a `## Previously Closed` body section in the detail pane, and a `has:reopened`
  filter label.
- Generated bead pages render a `## Previously Closed` section and a `**↺ Reopened:**`
  primary fact.
- The `TaskTriage` gate preview — the highest-value surface, since **Launch** is its
  default decision — renders one `> [!WARNING]` callout per record above the
  description, newest first, and adds the `↺N` badge to its notification note.

### Dependencies

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

### Discovered Follow-Up Capture and Triage

Unless a prompt forbids bead creation, agents should run `/sase_new_task` for useful
work discovered outside their current scope. The skill searches every task status and
all in-progress epic plans before allowing a new task:

```bash
sase bead create -T task -t "Fix flaky integration test" \
  -d "The retry test flakes under parallel pytest; discovered while landing sase-xy." \
  --size small
sase bead update <task-id> -s ready
```

For a semantic duplicate, the skill uses `sase bead +1` and does not create a task. When
an in-progress epic credibly caused the issue—not merely shares its topic—the skill
records a `DISCOVERED ISSUE:` note on that epic and does not create a task. Both records
are made when both cases apply. Only a genuinely distinct issue becomes a sized draft.

The task stays `open` while its title, description, size, model, references, and
dependencies are drafted. Marking it `ready` proposes it to the project owner. The
`bead_task_triage` chop scans enabled projects every five minutes and raises one
human-only `TaskTriage` gate per ready task bead. The compact
`[bead] <bead-id> — <title>` notification lands in the `Beads` panel, and the filing
agent travels with the gate into its Markdown preview when that attribution is known.
The chop records pending gates in lane state so later ticks do not repeat the
notification, cancels a pending gate if the bead leaves `ready`, and uses a new
deterministic generation if the same task becomes ready again or its pending gate needs
a presentation-contract refresh.

The gate offers two decisions:

- **Launch** (default) submits a detached background task that runs
  `sase bead work <task-id> --yes-to-all`. Optional feedback is appended to the worker
  prompt.
- **Close** requires feedback and closes the task with that reason and
  `resolution=canceled`.

Epic phase workers follow a stricter capture rule: they do not create beads. Instead, a
phase worker appends `PROPOSED FOLLOW-UP: <one-line summary — detail>` to its own bead
with `sase bead note`. The epic land agent collects those notes, files the worthwhile
proposals as `task` beads, marks them `ready`, and records why it declined any others.

### Artifact References

Every bead can carry a `refs` list: an ordered, deduplicated set of canonical artifact
references. This is distinct from `design`. `design` points to the one plan that
produced the bead; `refs` can point to many supporting artifacts such as research
reports, explicit files, related beads, agents, commits, bugs, chats, or configured
document roles.

Reference entries are stored without the prompt-time `@` sigil:

```bash
research:202607/artifact_capture_and_retention/artifact_capture_and_retention.md
file:default:0123456789abcdef01234567
bead:sase-b7
```

Write commands parse and normalize references before storing them, deduplicate repeated
entries while preserving first-write order, and do not require the reference to resolve
on the current machine. That matches the durable, cross-machine purpose of the field: a
reference may be valid even when this checkout does not have the sidecar, artifact row,
or agent history needed to resolve it locally. `sase bead doctor` performs the
resolution audit and reports references with unknown namespaces, missing targets, or
ambiguous targets.

### Creation Time Presentation

Every bead's `created_at` is `TEXT NOT NULL` in the store schema and is populated on
every bead, always in aware-UTC ISO form (`2026-04-28T01:34:17Z`). Every surface that
renders a bead also renders when it was created, through the single shared module
`src/sase/bead_time_presentation.py`, so the glyph, accent color, wording, and timezone
agree everywhere.

Two glyphs carry the vocabulary, both rendered in the muted teal accent `#5FAFAF`,
deliberately distinct from the bead identity colors (gold ids, blue phase, purple task)
so creation time reads as provenance metadata rather than competing with the title:

| Glyph | Meaning      |
| ----- | ------------ |
| `⧖`   | created      |
| `✎`   | last updated |

Three density tiers, selected per surface:

- **Full** — a labeled row on detail surfaces:
  `⧖ Created   2026-04-28 01:34:17 EDT · 3mo ago`
- **Compact** — a glyph-prefixed cell on single-line rows: `⧖ 3mo`
- **Data** — the raw stored ISO string, unformatted, on JSON/wire surfaces.

**The live-vs-persisted rule** governs which form a surface may use: a relative age may
appear only on surfaces that are re-rendered on every read (ACE panes, the BEAD lane,
CLI terminal output). Any surface whose bytes are persisted, hashed, or reconstructed
for validation — the TaskTriage gate preview, bead pages, JSON, the mobile wire —
renders the absolute timestamp only (`relative=False`), because a relative age would
make those bytes drift as the bead ages and break byte-stability or gate validation.

Unparseable or empty values render an honest `unknown` placeholder rather than a
fabricated time; elapsed time is clamped at zero so clock skew renders `now` instead of
a negative age.

Any new bead-rendering surface must format creation and update time through
`sase.bead_time_presentation` rather than formatting a timestamp itself. Known,
deliberate exceptions where a bead-rendering surface does not show its own creation
time:

- The dependency-edge `added <ts> by <who>` line in
  `sase bead dep list`/`sase bead dep tree` — the dependency edge's own timestamp, not
  the bead's; the bead's creation time appears in the same row as a separate `⧖` cell.
- The artifact-reference completion menu's shared age column, which renders `updated_at`
  for both bead and agent rows; repointing it would change agent-row semantics for no
  gain, so the bead's creation age instead rides in the glyph-labeled detail string.
- The bead pages Mermaid lineage graph node labels, which stay minimal
  (`id: title [status]`) for diagram readability; the full instant is one click away in
  the same page's identity block.

`tests/test_bead_time_surface_coverage.py` enumerates every covered surface and asserts
each renders a creation time for a fixture bead, so a future surface cannot silently
regress this contract.

## Storage

### Directory Structure

When the workspace provider declares in-tree storage, as the built-in `bare_git`
provider does:

```
sdd/beads/
  config.json           # Configuration (issue prefix, counter, owner)
  events/
    manifest.json       # Event-store schema and migration metadata
    streams/
      <root-id>.jsonl   # Canonical append-only event stream
  issues.jsonl          # Generated compatibility projection
  beads.db              # SQLite compatibility cache (gitignored)
```

Providerless local storage and legacy single-sidecar storage use `.sase/sdd/beads/` with
the same structure. Local storage uses the primary workspace; every sidecar layout uses
the active workspace clone and records provider/remote metadata in the primary
workspace's `.sase/sdd-store.json`.

Split sidecar storage puts bead state in its own auto-cloned `<owner>/<repo>--beads`
repository, checked out at `<workspace>/sase/repos/beads`. That repository keeps the
store **at its root** rather than under a `beads/` subdirectory, so `config.json`,
`metadata.json`, `issues.jsonl`, and `events/` sit beside the generated `README.md`,
`assets/`, `.gitignore`, and generated `pages/`. A split project that has not been
migrated yet still keeps bead state at `beads/` in the root of its auto-cloned `--plans`
repository; the `.sase/sdd-store.json` record decides which, and only a record that
names a `beads` sidecar (schema version 3) resolves to the dedicated repository. See
[SDD Storage](sdd_storage.md) for the record format and the adoption transaction that
performs the move.

Isolating bead state this way gives it its own git history, its own cooperative write
lock, and its own repository-health preflight, so hot bead writes no longer serialize
behind plan writes and a wedged bead rebase cannot block plan commits or epic approval.

Normal bead commands read and write one store for the active checkout. In in-tree mode,
canonical bead state lives in the current checkout's `sdd/beads/events/**` event store
plus `sdd/beads/config.json`. Providerless local commands route to the primary
workspace's `.sase/sdd/beads/` store. Sidecar-policy commands first materialize the
provider store, then route to the active workspace clone so an agent in workspace `#N`
writes its matching `.sase/sdd/` checkout, its `sase/repos/beads/` clone, or its
`sase/repos/plans/beads/` directory. If the event store is absent, reads fall back to
legacy `issues.jsonl`. Numbered sibling workspaces and legacy stores are not merged into
normal `sase bead` reads.

`sase bead` clones the beads sidecar on demand. When the store record names one and
`sase/repos/beads` is missing or its origin does not match the recorded remote, the
command materializes the clone before serving the request—reads included, since a read
cannot be served from a clone that does not exist. If the clone cannot be made usable,
the command fails with an error naming the repository and its remote. Projects whose
record has no beads sidecar clone nothing extra.

### Event Log + Compatibility Projections

Rust owns the bead storage/query/mutation path. The append-only event streams are the
canonical git-portable state. `issues.jsonl` remains a generated compatibility
projection, and `beads.db` remains a local compatibility cache. They are kept in sync:

- **Writes** append canonical Rust events first, then regenerate `issues.jsonl` and
  refresh `beads.db`.
- **Reads** prefer `events/manifest.json` plus `events/streams/*.jsonl`, falling back to
  legacy `issues.jsonl` only when no event store is present.
- **History** replays those same streams in projection order; `sase bead history <id>`
  makes every recorded field revision readable without changing canonical state.
- **Fresh clones** read directly from the tracked event streams and can rebuild the
  compatibility mirrors on demand.
- **Dependency removals** are recorded as `dependency_removed` events. During merged
  replay, a remove sorts after an add with the same timestamp, so add-then-remove
  deterministically leaves the edge absent.
- **Closed intervals** start with the first close after a bead becomes closed. Later
  close events in the same interval are kept in the log but ignored by the projection,
  so duplicate closes cannot move `closed_at` or erase a close reason. Reopening or
  otherwise moving out of `closed` ends the interval and archives its close metadata as
  a [close-history](#close-history) record instead of discarding it.
- **Note appends** use `note_appended` events whose payload stores only the new entry
  text. The reducer renders the timestamped attribution from the event metadata, so
  concurrent note appends merge as separate entries instead of replacing each other.
  Legacy `issue_updated { notes }` events remain whole-field replacements.

The `.gitignore` excludes `beads.db*` files. The event store, `issues.jsonl`, and
`config.json` are tracked in git.

### Sync Mechanism

`sase bead sync` regenerates the compatibility projection from the canonical event store
and stages the bead state in the owning git repo, including `events/**`, `issues.jsonl`,
and `config.json`. The projection contains one JSON object per line, sorted by issue ID
for clean diffs.

When both stores exist, the event store wins. Manual edits to `issues.jsonl` do not
change command output unless the event store is absent.

#### Publication Verification

Agents work in numbered workspace clones that are eventually discarded. A bead mutation
that is committed but never pushed therefore does not merely arrive late — it is
destroyed. Committing is not sufficient on its own, because the configured push policy
can be asynchronous, queued, or aimed at a different checkout than the one holding the
commit.

So every bead CLI mutation that creates a commit runs a verification pass after the
normal push policy: it resolves the bead store's own git root, and if that root has a
tracking upstream and still carries unpushed canonical bead commits, it forces one
synchronous push against the checkout holding them and re-verifies. If commits remain
unpublished the command **fails** with an operator diagnostic naming the unpublished
commit count, the store path and repository, the latest managed sync log, and a literal
`git -C <repo> push` remediation:

```text
ERROR: <mutation> was committed locally but NOT published.
  unpublished bead commit(s): 1
  bead store: …/sase/repos/plans/beads
  store repository: …/sase/repos/plans
  latest managed sync log: …
  This mutation exists only in this checkout. It is invisible to everyone else and is destroyed if this workspace is
  evicted.
  Remediation: git -C … push
```

A store with nothing of its own to publish to is reported as not applicable and never
fails the command: no git root, no tracking upstream, an [in-tree](#directory-structure)
layout, or a store this checkout may only read (one discovered through a checkout-local
`.sase/sdd-store.json` record, which refuses mutations outright). `--no-push` skips the
check along with the push it verifies. The check is also defensive about itself: a
verification that raises is logged and ignored rather than converting an otherwise
healthy mutation into a failure.

Because verifying a close by reading the local store cannot distinguish a published
close from one that will die with the workspace, agent-facing instructions point at the
close command's own exit status and this diagnostic rather than at a follow-up
`sase bead show`.

Two other surfaces enforce the same invariant:

- **The commit finalizer** commits leftover bead state as a safety net, then runs the
  same verification against the store it committed to. Unpublished state fails the run
  with `status=failed` and `reason=bead_state_unpublished` in
  `commit_finalizer_result.json`, carrying the full diagnostic, instead of reporting
  `finalized`. The failure is raised at the finalizer's return points, so the agent's
  own commit passes still run first — aborting earlier would strand uncommitted code in
  the workspace in order to report a bead problem.
- **Launch-time workspace preparation** refuses to evict a numbered workspace (`#2` and
  above) whose sidecar bead-store clones hold unpublished canonical commits. It
  publishes synchronously first; if commits remain it retains a recovery ref under
  `refs/sase/recovery/` in the store's own repository and fails the launch rather than
  renaming `sase/repos` into the workspace's `.sase/trash`. The printed refusal names
  both the ref and the store repository, so the commits are recoverable by hand with
  `git -C <store-repo> log <ref>` and a push of that ref's history. The guard
  understands the sidecar layouts — `sase/repos/beads` for a split clone root and
  `sase/repos/plans/beads` for a combined sidecar — in addition to `<repo_root>/beads`
  and in-tree stores. Ordinary (non-launch) workspace preparation warns and proceeds
  instead of refusing; only a store whose recovery ref could not be written stops it
  too.

#### Duplicate Bead IDs

Two clones minting from their own `next_counter` can allocate the same bead ID and each
write their own `events/streams/<id>.jsonl`. A naive merge of that add/add conflict
produces a stream with two `issue_created` events, which the reducer rejects —
historically wedging the shared store because every sync retry failed the same way.

Conflict resolution relocates one of the two beads instead of failing. The resolver
allocates the relocation ID from a store-wide pool built from `config.json`'s
`next_counter` plus every stream ID already in the store, so the ID a collision lands on
depends only on the store's contents and not on which clone happens to resolve the
conflict first. Both beads survive under distinct IDs, and the resolver reports
`relocated duplicate beads: <old> -> <new>` — in its own resolution message and in the
managed sync log under `~/.sase/bead_push_logs/sync-*.log`. If a bead you expect is
missing after a concurrent-mint conflict, search those logs for that line: the bead
still exists, under the new ID.

## Bead Pages

Projects with a hosted beads sidecar can publish one Markdown page per bead. Pages live
in the `--beads` repository under `pages/<root>/`, where `<root>` is the bead ID segment
before the first dot. The root bead renders as `pages/<root>/README.md`; descendants
render as `pages/<root>/<bead-id>.md`.

An artifact reference such as `@bead:sase-9z` addresses that generated page directly.
The payload is the exact bead ID, with no prefix-less shorthand and no `#L`, `#page=`,
or `#t=` fragment support. Addressing is lexical and offline: SASE derives the page path
from the ID without reading `issues.jsonl`, then reports the page missing if it has not
yet been published. Run `sase bead pages refresh --write` to publish or repair bead
pages before sharing durable `@bead:` refs.

Pages are generated projections, not hand-maintained state. They are rebuilt from the
canonical bead event store plus the primary repository's commit history, and they link
to the bead's plan, artifact references, parent and child beads, dependencies,
associated agents, and commits. Current commits use a structured `SASE_BEAD=<id>` footer
tag instead of a subject-line parenthetical; historical commits with trailing
`(<bead-id>)` subjects are still recognized when the ID exists in the store. Published
agent and family pages in the agents sidecar link back to the bead they worked, so the
bead↔agent relationship is navigable in both directions.

Each page's identity block also renders the bead's creator as `**Created by:** <name>`,
between `**Owner:**` and `**Assignee:**`. It links to the creator's hosted
agents-sidecar page when one resolves and otherwise renders as inline code with no link;
a bead with no recorded creator omits the fact entirely.

```bash
sase bead pages refresh                 # dry run; writes nothing
sase bead pages refresh --write         # write changed pages and commit one beads-sidecar batch
sase bead pages refresh --bead beads-1  # refresh one lineage
sase bead pages refresh --json          # machine-readable report
sase bead pages url beads-1.2           # print the hosted URL for one bead
```

Per-commit publication refreshes the committed bead's lineage after a `create_commit` or
`create_pull_request` workflow that carries `SASE_BEAD=`. The shared `pages/README.md`
roster is owned by `sase bead pages refresh`, so regular commits avoid rewriting a file
every active agent could touch. `sase bead show <id>` prints a `PAGE` section when the
local sidecar remote and branch resolve to a hosted URL; `--format json` includes
`page_url` in the same case. Its `CREATED BY` section similarly links agent-created
beads to the corresponding hosted agents-sidecar page. An epic agent clan's summary
panel also shows its epic bead's hosted page URL when one resolves; run
`sase plan links refresh` to repair a plan whose `BEAD` bullet predates hosted links.
Epic clan summaries place the label and complete URL on one logical line, with no
SASE-authored break or whitespace inside the address. A panel too narrow for the
composed row moves the whole address to the next row flush-left, so terminal URL
matchers and copy/paste always see the complete target.

## CLI Commands

With no subcommand, `sase bead` defaults to `sase bead list` with default options. Use
the explicit `sase bead list` form when passing list filters.

### `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker.

### `sase bead +1 <task-id>`

Corroborate an existing task with independently attributed evidence. `--note` is
required; `--ref` is repeatable and `--author` overrides normal current-agent
attribution. Each reporter counts once, the creator does not count, and repeat reporters
are unchanged no-ops. New evidence promotes `open` and `closed` tasks to `ready`
atomically, archiving any close metadata into close history rather than discarding it,
preserves other active statuses, and rejects plan or phase beads. See
[Task Corroboration (+1)](#task-corroboration-1) and [Close History](#close-history).

### `sase bead close <id> [<id2> ...]`

Close one or more issues. Every requested bead is checked before the first write, so a
batch either closes completely or leaves the store untouched. A bead with any non-closed
descendant is rejected and names the unfinished work; phase agents should continue to
close only their assigned phase bead, not the parent epic. Closing does not touch a
bead's existing [close history](#close-history); a new record is only archived there the
next time the bead reopens.

Closing a bead that is already closed exits successfully and reports `Already closed`
without appending another close event, changing `issues.jsonl`, or creating a store
commit. If the repeat close includes a note, the note is still appended and committed as
a note-only mutation. If the repeat close supplies an explicit `--resolution` or
`--reason` that disagrees with the recorded close, the command exits non-zero before
writing and points at `sase bead open` or `sase bead note` as the appropriate remedy.

For an epic plan bead, `--phases` (`-p`) closes phase beads by their numeric bead-ID
suffix: for example, `sase bead close sase-at -p 1-3,5` closes `sase-at.1`, `sase-at.2`,
`sase-at.3`, and `sase-at.5`. The epic target itself may be full or shorthand. The
option accepts comma-separated numbers and inclusive ranges, may be repeated, and
requires exactly one epic ID. It never closes the epic itself. A plan-tier, untiered, or
phase target is rejected without writing to the store.

`--force` is the explicit exception for canceling or superseding an unfinished tree. It
requires a non-empty reason and an explicit `canceled` or `superseded` resolution;
`--force --resolution done` is rejected. A forced close recursively closes the
unfinished descendants with the same non-done resolution, gives each one a close reason
naming the forcing parent, and records the swept descendant IDs in that parent's close
event.

`--note` appends one attributed note to every explicitly listed bead before any close
events, in the same mutation, so completion evidence and the close land in one commit
and one push instead of two. The note entry is stored as a `note_appended` event,
matching `sase bead note`; forced closes apply it only to the listed beads, never to the
swept descendants. Keep `sase bead note` for mid-work progress notes and for adding
evidence to a bead that is already closed.

Closing a delegated child plan/epic also closes its parent phase automatically once
every child of that phase is closed. This upward cascade continues only through phase
parents and never auto-closes a parent plan/epic; the parent land agent retains that
responsibility. Removing a child epic does not trigger the cascade, so its phase stays
open and can be scheduled again on retry.

When a close changes the store, SASE commits it and then publishes it according to
`sdd.push_after_commit` (default: `async`), followed by the
[publication check](#publication-verification) that turns an unpublished mutation into a
failure instead of a false success. Use `--no-push` to keep the commit local while
batching bead mutations, then publish the batch with a later `sase bead sync`.

| Flag               | Description                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------ |
| `-f, --force`      | Sweep unfinished descendants; requires a reason and `canceled` or `superseded`                               |
| `-P, --no-push`    | Commit the close locally but skip the post-commit push                                                       |
| `-n, --note`       | Append this attributed note to each listed issue before closing it                                           |
| `-p, --phases`     | Close numbered phases of one epic; accepts comma-separated numbers and ranges                                |
| `-r, --reason`     | Optional close reason text; required with `--force`                                                          |
| `-R, --resolution` | `canceled`, `done`, or `superseded`; real closes default to `done`; repeat closes compare only when supplied |

### `sase bead create`

Create a new issue.

| Flag                | Required             | Description                                                                                                                                                                                                                       |
| ------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-t, --title`       | yes                  | Issue title                                                                                                                                                                                                                       |
| `-T, --type`        | yes                  | Bead type: `task`, `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)`; parent IDs may be full or shorthand                                                                                                          |
| `-d, --description` | no                   | Issue description                                                                                                                                                                                                                 |
| `-a, --assignee`    | no                   | Assignee name                                                                                                                                                                                                                     |
| `--tier`            | no                   | Plan-bead tier: `plan` or `epic`                                                                                                                                                                                                  |
| `-c, --changespec`  | no                   | Attach a ChangeSpec name to a plan bead                                                                                                                                                                                           |
| `-b, --bug-id`      | no                   | Bug ID for the attached ChangeSpec; requires `--changespec`                                                                                                                                                                       |
| `-m, --model`       | no                   | Model used when this bead is launched. Provider-qualified (e.g. `codex/gpt-5.6-sol`) or a configured local alias (e.g. `#pro`). On epic plan beads this becomes the land-agent model; on phase/task beads it is the worker model. |
| `-R, --ref`         | no                   | Artifact reference to attach to the bead; repeatable and stored canonically                                                                                                                                                       |
| `-z, --size`        | task: yes; phase: no | Phase/task size: `xsmall`, `small`, `medium`, `large`, or `xlarge`. It controls model routing and whether large/xlarge work receives a plan-first handoff. Legacy sizeless tasks remain readable.                                 |

ChangeSpec metadata is valid only on plan beads. It is used by the epic-approval and
`sase bead work` flows to keep plan beads linked to the ChangeSpec they are intended to
produce.

New beads are attributed to the acting SASE agent (from `SASE_AGENT_NAME` or
`agent_meta.json`), falling back to the store owner when no agent identity resolves. A
`phase` bead always inherits its creator from its parent epic instead of being
attributed independently. A `plan` bead prefers the `proposed_by` value
`sase plan propose` stamps onto the plan file at proposal time, and falls back to the
acting agent when the plan carries none. See [`sase bead show`](#sase-bead-show-id) for
how the resolved creator is displayed.

### `sase bead dep`

Inspect and manage dependency edges. With no child subcommand, `sase bead dep` delegates
to `sase bead dep list` and prints the same central delegation notice used by other
default-list verbs.

```bash
sase bead dep
sase bead dep add <issue> <depends_on>
sase bead dep list [<id>]
sase bead dep rm <issue> <depends_on> [<depends_on2> ...]
sase bead dep tree [<id>]
sase bead dep add 001.2 001.1
```

`dep add` makes `<issue>` depend on `<depends_on>`. The issue becomes blocked if the
dependency is not yet closed.

`dep list` prints dependency edges with their blocking state and recorded provenance. A
scoped read, such as `sase bead dep list beads-001.2`, includes every bead status by
default because closed dependencies are usually what you need to see when explaining
readiness. A store-wide read defaults to `open`, `claimed`, `ready`, and `in_progress`,
matching `sase bead list`.

`dep tree` walks the dependency graph as a deterministic tree. `--direction out` follows
what the root waits on, `--direction in` follows what is waiting on the root, and
`--direction both` renders both trees. Store-wide trees use the same active-status
default as store-wide `dep list`; scoped trees include every status by default.

Tree output marks graph states explicitly:

- `⇡ (shown above)` means a shared subtree was already expanded, as in a fan-in diamond.
- `↻ (cycle)` means a dependency cycle was detected and that branch stopped.
- `(+N more, use --levels 0)` means `--levels` truncated descendants.
- `? <id> (not found)` means an edge points at an unresolved bead ID.

`dep rm` removes one or more existing dependency edges from `<issue>` in one
all-or-nothing mutation. The command records `dependency_removed` events and then
reports whether the source bead is ready or still blocked.

| Subcommand | Flag              | Values                                                         | Description                                      |
| ---------- | ----------------- | -------------------------------------------------------------- | ------------------------------------------------ |
| `list`     | `-c, --color`     | `auto`, `always`, `never`                                      | Color mode for text output                       |
| `list`     | `-d, --direction` | `both`, `in`, `out`                                            | Edges to show; defaults to `both`                |
| `list`     | `-f, --format`    | `compact`, `full`, `json`                                      | Output format; defaults to `compact`             |
| `list`     | `-n, --limit`     | non-negative integer                                           | Maximum root beads to print; `0` means unlimited |
| `list`     | `-s, --status`    | `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | Filter by endpoint/status root (repeatable)      |
| `tree`     | `-c, --color`     | `auto`, `always`, `never`                                      | Color mode for text output                       |
| `tree`     | `-d, --direction` | `both`, `in`, `out`                                            | Direction to walk; defaults to `out`             |
| `tree`     | `-f, --format`    | `compact`, `full`, `json`                                      | Output format; defaults to `compact`             |
| `tree`     | `-L, --levels`    | non-negative integer                                           | Maximum levels to descend; `0` means unlimited   |
| `tree`     | `-s, --status`    | `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | Filter by bead status (repeatable)               |

### `sase bead ref`

Inspect and manage artifact references attached to beads. With no child subcommand,
`sase bead ref` delegates to `sase bead ref list`.

```bash
sase bead ref add <id> <ref> [<ref2> ...]
sase bead ref list [<id>]
sase bead ref list <id> --resolve
sase bead ref rm <id> <ref> [<ref2> ...]
```

`ref add` normalizes every supplied reference, appends entries that are not already
present, and reports a no-op when the bead already carries all of them. `ref rm` removes
the supplied normalized references and leaves absent entries alone. Both commands record
per-reference events, so concurrent agents attaching different references do not replace
each other's entries.

`ref list` prints stored canonical references. With `--resolve`, it also reports where
each reference resolves from the current workspace, or that it resolves nowhere. The
optional bead ID scopes the listing to one bead; without it, the command lists beads in
the current store that carry references. Add `--json` for a stable machine-readable
response.

| Subcommand | Flag            | Description                                      |
| ---------- | --------------- | ------------------------------------------------ |
| `list`     | `-j, --json`    | Emit machine-readable reference data             |
| `list`     | `-r, --resolve` | Resolve references against the current workspace |

### `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, event store, legacy projection, or compatibility cache
- Projection drift between canonical events and `issues.jsonl`
- Redundant close events, including how many landed in the recent diagnostic window
- Invalid events or unreduced orphan phase records
- Uncommitted bead-state changes
- Orphan children (phase or nested-plan beads whose parent is missing)
- Legacy or unresolved `design` plan references
- Issue prefix leaked as the project's ProjectSpec directory key instead of its
  `PROJECT_NAME` (reported; automatically repaired before the next top-level bead is
  minted, or repair on demand with `sase bead doctor --fix-issue-prefix`)
- Artifact references with unknown namespaces, missing targets, or ambiguous targets
- `claimed` beads whose assignee resolves to no agent artifact (reported only; run
  `sase bead open <id>` to clear them)
- `open` beads owned by a live agent that has not started work yet (reported only; it
  means the `bead_claim_checks` chop is not running or is failing, since it should have
  claimed them)

If bead commands fail before opening a store, run `sase core health` first. It verifies
that the required `sase_core_rs` extension is importable and exposes the representative
bead CLI binding used by the fast path.

`--fix-projection` previews rows where `issues.jsonl` differs from replaying the
canonical event streams, then rewrites the projection from the streams after
confirmation. The repair refuses unexpected diffs: row additions or removals, status
changes, fields outside `closed_at`, `close_reason`, `close_history`, and `updated_at`,
or any `closed_at` move later. `close_history` is allowed because the first repair after
upgrading to a sase-core release with close history legitimately materializes archived
records for beads whose close reasons were destroyed by a reopen before sase-core
started archiving them — see [Close History](#close-history). A successful repair
commits `chore(beads): reproject bead state from canonical events`; a second clean run
writes nothing. Use `--yes` for non-interactive repair after reviewing the preview
through an external approval gate.

`--fix-issue-prefix` previews and, after confirmation, resets a store's issue prefix on
demand when it was leaked as the project's ProjectSpec directory key (e.g.
`gh_bobs-org__bob-cli`) instead of its `PROJECT_NAME` (e.g. `bob-cli`). The same repair
also runs automatically before the next top-level bead is minted. A deliberately
customized prefix is never flagged. The repair is forward-only: existing bead IDs keep
the old prefix, and only new top-level beads use the corrected one.

| Flag                     | Description                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------- |
| `-F, --fix-design-refs`  | Repair recoverable legacy design references after confirmation                      |
| `-I, --fix-issue-prefix` | Repair a leaked ProjectSpec-key issue prefix to the project name after confirmation |
| `-P, --fix-projection`   | Rewrite `issues.jsonl` from canonical event streams after confirmation              |
| `-y, --yes`              | Apply the requested doctor repair without an interactive confirmation               |

### `sase bead history [<id>]`

Replay one bead's canonical event stream as an ordered, field-level timeline. Compact
output prints the timestamp, actor, operation, and changed field names for each event.
Full output prints every prior and new value, including earlier note revisions that
later updates replaced. JSON emits one envelope with `issue_id`, `schema_version`, and
`entries`. A duplicate close that the reducer treated as inert is labeled as redundant
instead of rendering as an empty change row.

Use `--lost-notes` to report notes snapshots whose nonblank text no longer appears in
the current notes. With no positional ID it scans the whole store; with an ID it checks
only that bead. Findings are sorted by bead ID. Add `--restore` to preview
provenance-tagged appends, prompt once, and restore every finding through the same
atomic append mutation used by `sase bead note`. Restoration is idempotent: restored
text is retained by later append snapshots, so a second scan reports nothing.
Non-interactive restoration declines safely unless `--yes` is supplied, and `--restore`
without `--lost-notes` is a usage error.

| Flag               | Values                    | Description                                                    |
| ------------------ | ------------------------- | -------------------------------------------------------------- |
| `-F, --field`      | field name                | Restrict to events changing the field; repeatable              |
| `-f, --format`     | `compact`, `full`, `json` | Output format; defaults to `compact`                           |
| `-n, --limit`      | non-negative integer      | Newest entries to print; omitted or `0` is unlimited           |
| `-l, --lost-notes` | boolean                   | Report beads whose current notes dropped an earlier revision   |
| `-R, --restore`    | boolean                   | With `--lost-notes`, re-append findings after one confirmation |
| `-y, --yes`        | boolean                   | With `--restore`, skip the confirmation prompt                 |

### `sase bead init`

Initialize the bead store for the current project. In effective in-tree SDD mode this is
`sdd/beads/`; local and legacy separate-repo modes use `.sase/sdd/beads/`. Split sidecar
mode uses the root of the `--beads` repository once the store record names that sidecar,
and `beads/` in the `--plans` repository until then.

A newly initialized store's default `issue_prefix` is the project's `PROJECT_NAME`
display name (falling back to the internal ProjectSpec key, then the git remote's repo
name, then the directory name) rather than the raw ProjectSpec key. Stores created
before this change that already leaked the key are forward-repaired automatically before
their next top-level bead is minted. Use `sase bead doctor --fix-issue-prefix` to repair
one on demand before creating another bead (see
[`sase bead doctor`](#sase-bead-doctor)).

### `sase bead list`

List issues with optional filtering. Without `--status`, the command lists `open`,
`claimed`, `ready`, `snoozed`, and `in_progress` issues; pass `--status=closed` when you
need closed history. When the default active query is empty and no explicit `--status`
was given, the command falls back to listing closed beads. `--status`, `--type`, and
`--tier` are repeatable.

Compact rows lead with an aligned, colored type indicator ahead of the existing status
glyph:

```
{type_glyph}<pad> {status_glyph} {id} · {title}{ ← parent_id}
```

```
▸ ◐ sase-bv · Attribute beads to the agent that created them
◆ ◐ sase-bt · Fix xdist flake in artifact modal copy shortcut
↳ ◐ sase-bv.3 · Record the creator on every bead creation path ← sase-bv
```

The fixed first column is the bead type; the second glyph is status. Type color is
controlled by the same `-c, --color` option as the status and ID styles, and the icons
remain distinct without color. Tier (`plan` vs. `epic`) stays out of this column; it
remains visible through `--tier`, `--format full`, and `--format json`.

| Type    | Icon | Description                                          |
| ------- | ---- | ---------------------------------------------------- |
| `plan`  | `▸`  | Plan-like container with a tier; may be a child epic |
| `phase` | `↳`  | Sized executable child within an epic/plan bead      |
| `task`  | `◆`  | Independent work item; new tasks require a size      |

| Flag           | Values                                                         | Description                                                                           |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `-c, --color`  | `auto`, `always`, `never`                                      | Color mode for compact output                                                         |
| `-f, --format` | `compact`, `json`, `full`                                      | Output format; defaults to `compact`                                                  |
| `-n, --limit`  | integer                                                        | Maximum beads to print; closed listings default to the newest 20, `0` means unlimited |
| `-s, --status` | `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | Filter by status (repeatable)                                                         |
| `--tier`       | `plan`, `epic`                                                 | Filter by plan-bead tier                                                              |
| `-t, --type`   | `plan`, `phase`, `task`                                        | Filter by type (repeatable)                                                           |

Active (`open`/`claimed`/`ready`/`in_progress`) listings are unlimited by default.
Whenever the final status scope includes `closed` and `--limit` is omitted, only the
newest 20 beads print; pass `--limit 0` for the full closed history.

### `sase bead note <id> <text>`

Append one timestamped, attributed entry to an issue's notes. The mutation records a
`note_appended` event containing only the entry text; the reducer renders
`[<timestamp> · <author>] <text>` from event metadata and separates it from existing
notes by a blank line. The mutation runs atomically in the Rust bead store, and
concurrent note writers merge as separate events rather than replacing each other.

| Flag           | Description                                                               |
| -------------- | ------------------------------------------------------------------------- |
| `-a, --author` | Author recorded on the entry; defaults to current agent, then store owner |

### `sase bead onboard`

Display a quick-start guide with common command examples, including required task size,
`/sase_new_task` agent policy, and task corroboration.

### `sase bead open <id>`

Reopen an issue with an `issue_opened` event. Every closed ancestor above it is reopened
in the same mutation, and the command prints the ancestor IDs it changed. Resolutions,
close reasons, and close timestamps are archived into each reopened bead's close history
instead of being discarded — see [Close History](#close-history); the full history also
remains available in `sase bead history --format full`.

### `sase bead ready`

Show task beads whose explicit status is `ready` and whose dependencies are all
`closed`. Epic work does not appear: phase beads are preassigned at epic launch rather
than entering a derived ready queue. When no rows qualify, the command prints
`No ready task beads (epic work is preassigned at launch).` A ready task with an active
blocker remains stored as `ready` but is omitted until the blocker closes.

### `sase bead rm <id> [<id2> ...]`

Remove one or more issues and recursively cascade-delete the union of all their
descendants, including phases nested beneath child epics. Every requested ID is
validated before anything is removed, so a missing ID leaves the store unchanged.
Overlapping or repeated selections remove and print each issue only once. This is
irreversible.

### `sase bead search <query>`

Find beads whose indexed text fields contain a case-insensitive literal substring. This
is substring search, not regex or glob matching. Current indexed fields include ID,
title, description, notes, design/plan path, artifact references, owner, assignee,
model, phase/task size, ChangeSpec name/bug ID, status, type, and tier; timestamps are
not searched. Unlike `sase bead list`, search includes `open`, `claimed`, `ready`,
`in_progress`, and `closed` beads by default, so it is the quickest way to recover older
context.

Compact output prints each matching bead with a short snippet. For multi-line fields
such as descriptions or notes, the snippet uses the line that matched the query when
possible instead of always showing the first line. JSON output exposes the exact
`matched_fields` list for each result.

```bash
sase bead search auth
sase bead search auth --format json
sase bead search auth --format full --limit 3
sase bead search auth --status open --type phase
sase bead search auth --type plan --tier epic
```

| Flag           | Values                                                         | Description                                     |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------- |
| `-c, --color`  | `auto`, `always`, `never`                                      | Color mode for compact output                   |
| `-f, --format` | `compact`, `json`, `full`                                      | Output format; defaults to `compact`            |
| `-n, --limit`  | non-negative integer                                           | Maximum results; omitted or `0` means unlimited |
| `-s, --status` | `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | Filter by status (repeatable)                   |
| `--tier`       | `plan`, `epic`                                                 | Filter by plan-bead tier (repeatable)           |
| `-t, --type`   | `plan`, `phase`, `task`                                        | Filter by type (repeatable)                     |

### `sase bead show <id>`

Display complete details for an issue including status, type, tier, parent lineage,
dependencies, blockers, description, notes, ChangeSpec metadata, model, linked plan
path, artifact references, creator, and the hosted page URL when one resolves locally.
The `CREATED BY` block localizes an agent's durable global name and links to its hosted
agents-sidecar page when that URL resolves. A human-created bead shows the creator's
email without a link. `sase bead list --format full` and
`sase bead search --format full` share the same `CREATED BY` block but never resolve or
print the hosted-agent link — only `sase bead show` does. Compact
`sase bead list`/`sase bead search` rows never show the creator at all. Closed beads
include their resolution, close reason, and close timestamp; legacy closures without a
resolution show `(unrecorded)`. Phase and task detail views always print a size: they
use the stored value when present and `small` when it is absent. Legacy sizeless task
launches use the same `@small_phase_worker` fallback. Any bead's children are grouped as
phases (with status and size) and child epics (with tier and status), including child
epics owned by a phase bead. Nested beads show their complete lineage back to the root
plan. A `claimed` bead also prints
`Claimed by: <assignee> (agent has not started working yet)`.

Detail resolution — the target issue plus its ancestors, children, dependencies, and
blockers — comes from a single Rust-side store read instead of the three independent
reductions earlier versions performed. Combined with a narrowed CLI parser (only the
`bead` subcommand tree is built, not every `sase` subcommand) and memoized
repo-inventory lookups (the creator-URL and artifact-reference-context resolvers no
longer each re-probe `git remote` and re-merge sidecar config from scratch), this keeps
`sase bead show` fast regardless of store size or how many other beads reference the
target — including beads with `refs`, which previously paid the repo-inventory cost
twice.

`full` is the default detail block. `compact` prints the same single row as
`sase bead list`. `json` emits a single-bead envelope with `issue`, `ancestors`,
`children`, `depends_on`, `blocks`, and `plan`, plus `page_url` when a hosted page URL
resolves and `created_by_url` when the creator's hosted agent page resolves; every
relationship reference includes a `resolved` flag and fixed null-valued fields for
unresolved IDs.

`--format full` renders a semantically colored, syntax-highlighted detail block
controlled by `-s/--style`. Styling is purely additive ANSI: stripping SGR escapes from
any styled output reproduces the exact `plain` bytes, so piping to a non-TTY (as every
agent does) is unaffected. `--color` decides **whether** ANSI may be emitted; `--style`
decides **how much** styling to apply once that gate is open:

| `--style` | Meaning                                                                                              |
| --------- | ---------------------------------------------------------------------------------------------------- |
| `auto`    | Resolve to `rich` when color is enabled, else `plain`. Default.                                      |
| `plain`   | No ANSI at all, regardless of `--color`.                                                             |
| `rich`    | Semantic palette plus markdown/code syntax highlighting inside `DESCRIPTION`, `NOTES`, and evidence. |

`--style` has no effect on `--format json`, which is never styled. For
`--format compact`, `plain` forces no ANSI while `auto`/`rich` enable the compact row's
semantic colors when the color gate is open.

```bash
sase bead show sase-64 --style rich --color always
```

`DESCRIPTION`, `NOTES`, and task `+1 EVIDENCE` notes wrap at the configured
`markdown.print_width` total columns by default (`88` unless you configure otherwise);
`NOTES` appears only when the bead has notes. The budget includes the rendered indent:
with `--wrap 60`, no line in a description block exceeds 60 columns unless it contains a
single token that is longer than the budget. Wrapping is break-only: short lines are
emitted byte-for-byte, existing line breaks are not reflowed into longer paragraphs, and
`--wrap none` or `--wrap 0` disables wrapping. `--wrap auto` uses the current terminal
width, floored at 20 columns.

The wrapper never splits URLs, inline code spans, Markdown links, autolinks, or ordinary
non-whitespace tokens. Fenced code blocks, indented code, tables, tab-bearing lines,
structured relationship rows, plan paths, refs, and the title row are left unwrapped.

```bash
sase bead show sase-64 --wrap auto
```

| Flag           | Values                             | Description                                                                 |
| -------------- | ---------------------------------- | --------------------------------------------------------------------------- |
| `-c, --color`  | `auto`, `always`, `never`          | Color mode; now applies to `--format full` too                              |
| `-f, --format` | `compact`, `json`, `full`          | Output format; defaults to `full`                                           |
| `-s, --style`  | `auto`, `plain`, `rich`            | Styling level for `--format full`; defaults to `auto`                       |
| `-w, --wrap`   | integer >= 20, `auto`, `none`, `0` | Prose wrap width for full output; defaults to `markdown.print_width` (`88`) |

### `sase bead snooze <id> [<id2> ...]`

Defer one or more `open` or `ready` task beads. See
[Snoozing a Task Bead](#snoozing-a-task-bead) for the full workflow. Multiple IDs apply
the same wake time, `+1` target, and reason atomically, matching `sase bead update`'s
batch semantics.

| Flag                    | Description                                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------------------- |
| `-u, --until TIME`      | Wake time: a duration (`30m`, `2h`, `1h30m`, `3d`) or absolute ISO-8601 timestamp; required unless `--cancel` |
| `-p, --plus-ones COUNT` | Also wake when this many additional `+1` reports arrive                                                       |
| `-r, --reason TEXT`     | Why this task is being deferred; embedded in the note this snooze appends                                     |
| `-c, --cancel`          | Wake these beads now, returning them to `ready`                                                               |

### `sase bead stats`

Show project statistics: total, open, claimed, ready, snoozed, in-progress, and closed
counts, plus plan, phase, and task counts.

### `sase bead sync`

Regenerate the compatibility projection from the canonical event store and stage bead
state in git. It does not create a commit; the staged event/projection files are
included in the next normal project or SDD commit.

| Flag           | Description                                   |
| -------------- | --------------------------------------------- |
| `-s, --status` | Check whether bead state has unstaged changes |

### `sase bead update <id> [<id2> ...]`

Update one or more fields on one or more issues. Every listed bead receives the same
field changes in a single all-or-nothing store mutation: every ID is resolved and every
resulting issue is validated before anything is written, so an unknown ID or an invalid
field value leaves every named bead untouched. Duplicate IDs, including a shorthand
alongside its resolved full form, collapse to a single update. A single-ID invocation is
unaffected — same syntax, output line, and commit message as before.

| Flag                | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `-s, --status`      | Change status                                                                         |
| `-t, --title`       | Change title                                                                          |
| `-d, --description` | Change description                                                                    |
| `-n, --notes`       | Replace notes                                                                         |
| `-D, --design`      | Change plan path                                                                      |
| `-a, --assignee`    | Change assignee                                                                       |
| `--tier`            | Change plan tier                                                                      |
| `-m, --model`       | Change the launch model. Pass an empty string to clear.                               |
| `-z, --size`        | Change a phase or task bead's `xsmall`, `small`, `medium`, `large`, or `xlarge` size. |

Use `sase bead update --notes` for an explicit field replacement. Use `sase bead note`
when recording progress that should accumulate with earlier notes.

Beads whose requested fields already hold the requested values are quiet no-ops: they
are reported as `Unchanged`, excluded from the commit, and an all-no-op batch writes
nothing. `--status closed` keeps the descendant guard that prefers `sase bead close`,
evaluated against the whole batch: a descendant that is itself being closed by the same
invocation counts as closed, so argument order does not matter, but a descendant left
out of the batch still rejects the whole update.

### `sase bead work <target>`

Create or resume an epic from a validated Markdown plan, launch an existing epic-tier
plan bead, or launch one standalone task bead. A target is treated as a plan file when
it ends in `.md`, contains a path separator, or names an existing file; other targets
are bead IDs whose type selects the epic or task path. Epic modes run one agent per
non-closed, non-delegated phase plus a final land agent. Task mode runs exactly one
deterministic worker; see [Standalone Task Workflow](#standalone-task-workflow) for its
full lifecycle.

For a task bead, `sase bead work <task-id>` accepts `ready` (normal), `open` (manual
launch), or recoverable `in_progress` state. It does not launch a duplicate when the
assigned agent is still alive, and it rejects closed tasks. `--dry-run` prints the
single worker prompt without changing the bead or agent registry. A real launch:

1. Force-reuses the task ID as the deterministic agent name after showing or confirming
   any destructive cleanup.
2. Selects the bead's stored model or its size-derived phase-worker alias; missing
   legacy size normalizes to small.
3. Renders one VCS-aware prompt ending in `#bd/work_task:<task-id>`, plus `#plan` for
   large/xlarge tasks.
4. Sets `status=in_progress` and `assignee=<task-id>` in one checkpoint commit,
   publishes it, then launches the worker.
5. Restores the prior task state if dispatch fails before any runner starts; a live
   runner keeps the checkpoint.

The `TaskTriage` gate's default Launch branch submits this command as a detached task
with `--yes-to-all`; optional gate feedback is appended to the worker prompt.

Plan-file mode is the canonical epic-approval entry point. It:

1. Validates the file against the epic plan schema and reports the complete diagnostics
   on failure.
2. Resolves the project's SDD and bead stores, initializing the bead store when needed.
3. Archives the plan under the resolved `{YYYYMM}/` plans directory and commits it.
4. Resumes the linked epic when the archived plan already has a valid `bead_id`.
5. Otherwise creates the epic plan bead from the plan's `title`, `goal`, top-level
   `model`, optional `parent_bead`, and optional ChangeSpec metadata; creates phase
   beads with their authored sizes in `phases[]` order; wires every `depends_on` edge;
   and commits the new `bead_id` link.
6. Invokes the existing bead-ID launch path.

A missing phase description becomes a deterministic pointer to the plan and phase ID. A
linked `bead_id` that no longer exists fails with instructions to remove the stale link
or restore the bead store. Failures before the launch checkpoint is committed remove the
newly-created epic and children and restore the plan link. A publication failure after
the checkpoint preserves the linked, preassigned epic as the safe retry point even
though no runner spawned. If dispatch fails with no runner spawned, plan-file mode
removes a newly created graph and restores the plan link; for an epic that already
existed, it instead restores that epic's prior readiness, assignments, and statuses.
Once a runner has spawned, the linked epic and checkpoint are preserved for recovery and
partial runners are terminated. Every plan-file failure after archiving prints the exact
`sase bead work ... --yes` command to resume.

When an epic-tier plan is proposed from bead work, `sase plan propose` automatically
stamps `parent_bead` from the phase agent's `SASE_PHASE_BEAD_ID`, or from the land
agent's `SASE_EPIC_BEAD_ID`. Plan-file mode resolves that bead and creates the new epic
beneath it, yielding recursive IDs such as `beads-001.2.1`; an unresolved parent fails
with a remedy instead of silently creating a top-level epic. `--parent <bead-id>`
overrides the authored association, while `--parent top-level` explicitly creates an
unparented epic. The override applies only to plan-file targets.

`--dry-run` plan-file mode validates and resolves the stores, previews the archive
destination, parented epic ID, authored beads, routed models, and dependency waves, and
does not write files, create beads, reserve names, or launch agents. `--json` prints one
stable object for scripting; successful human output always ends with a grep-friendly
`Epic: <id>` line used by approval hosts.

Once an epic bead exists, the shared launch path:

1. Validates that `<epic_id>` resolves to an issue of type `plan` with `tier=epic`. If
   the plan is already marked `is_ready_to_work`, the command treats the run as a retry
   and schedules any remaining non-closed phases. A phase that owns a non-closed child
   plan/epic is delegated work already in flight and is skipped until that child closes
   or is removed; retries therefore do not launch a duplicate phase agent.
2. On a confirmed launch, force-reuses the deterministic bead-work names —
   `<epic_id>.<N>` (for each open phase), `<epic_id>.land` (for the land agent), and the
   legacy `<epic_id>` land-agent name — by wiping any prior owner of those names,
   whether that owner is a completed, dismissed, or planned reservation or a still-live
   agent (live owners are terminated). This also covers owners that hold the name only
   as a `workflow_name`. If the forced-reuse cleanup cannot complete (a wipe fails or a
   name is still reserved afterward), the command aborts before mutating any bead state.
   `--dry-run` performs no cleanup; it only warns which live agents a real launch would
   force-reuse.
3. Flips the epic plan bead's `is_ready_to_work` flag to `True` when it was not already
   ready.
4. Builds a Kahn-wave schedule from the epic's schedulable open phase children,
   respecting dependencies and excluding delegated phases with an open child plan/epic.
   When every remaining phase is delegated, only the land agent is launched and remains
   parked behind the phase beads.
5. Associates each rendered worker with exactly one bead in its `%id`: the first phase
   uses its full agent name plus `bead=<phase-id>` beside the separate clan declaration,
   later phases combine their suffix, `clan=<epic-id>`, and `bead=<phase-id>`, and the
   land agent combines `land`, the clan, and `bead=<epic-id>`.
6. Renders a single `---`-separated multi-prompt. Each per-phase agent is named
   `<epic_id>.<N>` and references the [`work_phase_bead`](xprompt.md#available-tags)
   xprompt; a final land agent named `<epic_id>.land` references the
   [`land_epic`](xprompt.md#available-tags) xprompt. Every segment joins clan
   `<epic_id>` and assigns that whole clan to tribe `@epic` with the single
   `%clan(<epic_id>, tribe=epic)` directive. Each phase dependency becomes both a `%w`
   wait on the blocker phase-agent name and a `%w(bead=<blocker-phase-id>)` closure
   wait. The land agent likewise waits on every launched phase agent and on every
   authored phase bead, including already-closed or currently delegated phases.
   Requiring both conditions prevents a phase that delegated to a child epic from
   releasing dependents merely because its original agent finished; the child epic must
   land and close the parent phase first. A failed or killed phase keeps dependents and
   the land agent parked until its agent name is retried successfully and its bead
   closes. `xsmall`, `small`, and `medium` phases implement directly with
   `%model:@xsmall_phase_worker`, `%model:@small_phase_worker`, and
   `%model:@medium_phase_worker`, respectively. Only `large` and `xlarge` phases append
   `#plan` after their work reference and use `%model:@large_phase_worker` and
   `%model:@xlarge_phase_worker`. A stored phase `model` always wins over the
   size-derived alias without changing whether the phase receives `#plan`, and a missing
   legacy size behaves as `small`. The land agent emits `%model:<value>` when the epic
   plan bead has a stored `model`. Without one, it emits `%model:@epic_lander` below
   `bead.big_epic_phase_threshold` and `%model:@big_epic_lander` at or above the
   threshold (default `5`), using the total authored phase count even when resumed work
   has already-closed phases. Normal landers fall through `@epic_lander` to `@default`,
   while landers selected by the threshold fall through `@big_epic_lander` via
   `@smartest`. `xsmall` phases fall through `@xsmall_phase_worker` to the load-balanced
   `@cheaper` pool, `small` phases through `@small_phase_worker` to the `@cheap` pool,
   `medium` phases through `@medium_phase_worker`, `large` phases through
   `@large_phase_worker` to `@smart`, and `xlarge` phases through `@xlarge_phase_worker`
   to `@smartest`, inheriting that alias's target. The independent `@cheapest`
   load-balanced pool is available for explicit use but has no automatic consumer.
   Builtin aliases can be configured under `llm_provider.model_aliases.builtin`. Each
   phase segment and the final land-epic segment carries bare `%auto`, so submitted
   implementation and landing plans are auto-approved. An agent may author a tale or an
   epic as needed; the plan's authored `tier` selects the corresponding automatic
   follow-up path.
7. Before spawning any runner, batch-preassigns every scheduled phase bead to its
   rendered worker and the epic bead to `<epic_id>.land`, setting all of them to
   `in_progress`. It commits readiness, assignments, and the complete graph as one
   `chore(beads): checkpoint approved epic graph <id>` checkpoint. A retry whose graph
   is already committed may have no new checkpoint commit. Before dispatch, SASE applies
   the target-specific synchronization rules below.
8. Dispatches the rendered multi-prompt. Runner-side waiting claims and launch
   promotions see their preassignment and become no-ops. Each segment uses a force-reuse
   `%id(!<agent_name>, bead=<bead-id>)` form (with `clan=` on join segments), so
   re-running `sase bead work` after a killed or failed run wipes stale name owners
   before relaunch. The schedule is status-blind and uses agent liveness, which makes
   the checkpoint safe to retry.

When a phase agent auto-approves an epic-tier implementation plan, that child epic is
created beneath the phase and the phase remains open while delegated work runs. Landing
the child epic triggers the upward close cascade described above, which closes the phase
and lets its bead-gated dependents proceed. Until then, parent-epic retries skip that
delegated phase. The land agent now genuinely requires every phase bead to close; if a
phase crashes before closure, retry or close that phase explicitly rather than expecting
landing to sweep it up.

| Flag                  | Description                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| `-a, --artifacts-dir` | Planner artifacts directory to back-fill after an approved epic launch; plan-file targets only       |
| `-c, --cl-name`       | ChangeSpec name for the approved epic completion notification; plan-file targets only                |
| `-n, --dry-run`       | Preview the epic graph or task prompt, model routing, and cleanup without mutation                   |
| `-j, --json`          | Print one machine-readable result object; also implies `--yes-to-all`                                |
| `-P, --no-push`       | Skip checkpoint synchronization; a remote-backed detached store stops before spawning                |
| `-p, --parent`        | Override a plan file's `parent_bead`; use `top-level` for an unparented epic; plan-file targets only |
| `-y, --yes`           | Skip only the launch confirmation prompt                                                             |
| `-Y, --yes-to-all`    | Skip both the destructive-cleanup and launch confirmation prompts                                    |

The work xprompts are resolved by `XPromptTag` (tag-based lookup), so a project-local or
user-defined `work_phase_bead`, `work_task_bead`, or `land_epic` xprompt overrides the
built-in. For epic-tier work, every phase and land segment carries bare `%auto`, so
spawned agents can auto-approve submitted tale or epic plans and follow the path
selected by the authored `tier`, without a human-in-the-loop checkpoint between
dependency waves.

When the epic plan bead is attached to ChangeSpec metadata (`--changespec` /
`--bug-id`), `sase bead work` preserves the current project's VCS context in the
generated prompt. The first phase segment targets the project reference and adds a `#pr`
reference for the ChangeSpec, while later phase and land segments target the ChangeSpec
ref directly. For non-ChangeSpec epics launched from a known SASE workspace, each
segment is still prefixed with the detected VCS workflow and project name (for example
`#git:sase` or `#gh:sase-org/sase`). If the current directory is not associated with a
SASE project, the prompts are left unprefixed and run in the caller's normal launch
context.

If checkpoint creation fails before it commits, the command restores every phase/epic
status and assignee it changed, and restores `is_ready_to_work` only when this attempt
set it. A detached-store publication failure after the local checkpoint commit stops
before spawning and preserves that checkpoint as the safe retry point; rerun without
`--no-push` after fixing the remote. For an existing epic, an agent-dispatch failure
before any runner spawns restores the prior assignments and commits the recovery.
Plan-file mode additionally removes a graph created by that invocation and restores its
plan link. A partial-spawn failure SIGTERMs the children it did start and preserves the
preassigned checkpoint for recovery. An epic that was already ready remains ready.

Successful launches do not add a post-launch bead commit: the pre-spawn graph checkpoint
is the complete launch-owned state. The accepted `bead.push_after_commit` configuration
field is not consulted by this current path. The exact synchronization sequence depends
on the target:

- For a bead-ID target, SASE runs the managed sync worker synchronously after the
  checkpoint unless `--no-push` was passed. A store with no Git remote makes that sync a
  local no-op. Any reported sync or push error stops the launch before dispatch,
  including for an in-tree Git store. A remote-backed detached store has the additional
  requirement that the checkpoint was actually pushed.
- For a plan-file target, SASE synchronously publishes a remote-backed detached bead
  graph before dispatch. After a successful dispatch it makes a best-effort synchronous
  push of the plans store, which publishes the archived plan and its `bead_id` link. A
  failure in this later plans-store push is a warning, not a launch failure.
- `--no-push` skips these synchronization steps. It is usable only when workers can see
  the local checkpoint directly; a remote-backed detached bead store exits nonzero
  before any agent is spawned.

## Rust Backend

The bead data model, event reducer, JSONL/config codecs, compatibility-cache refresh,
mutation transactions, ID allocation, deterministic work-plan DAG, and common CLI output
planning are implemented in `sase-core` and exposed through `sase_core_rs`. Python keeps
the host logic that belongs in the application layer: locating the active bead store,
relativizing plan paths, resolving VCS context and xprompts for `sase bead work`,
prompting the user, launching agents, rolling back failed launches, and incrementing
telemetry counters.

Common `sase bead` commands dispatch through an early CLI fast path before the full
top-level parser is built. Help text and host-coupled commands still fall through to the
normal Python parser/handlers where needed.

Use these checks when changing bead internals:

```bash
sase core health -j
pytest tests/test_bead tests/test_core_facade/test_bead_read.py tests/test_core_facade/test_bead_mutation.py
just rust-check
just bead-perf-smoke
```

## Current Checkout Source Of Truth

In in-tree mode, every `sase bead` read and mutation command uses the current checkout's
`sdd/beads/events/**` event store and `sdd/beads/config.json`, with `issues.jsonl` used
only as a fallback when events are absent. Running the command in `myproject/` reads
that checkout's bead state; running it in `myproject_2/` reads `myproject_2/sdd/beads/`.
The CLI does not merge sibling workspace stores, and duplicate IDs in another checkout
do not override the active checkout's records.

ID allocation also uses only the active store's `config.json` and canonical event state.
If a sibling checkout has not pulled or merged the latest bead state, it may allocate
IDs based on its local state; sync bead changes through the normal VCS workflow when
several agents are coordinating on the same project.

Cross-project helper surfaces, such as mobile/editor bead pickers, may inspect one
canonical store per known project, but they still do not merge numbered sibling
workspaces or legacy bead stores for the same project.

## ACE TUI Integration

### Plan File Linking

When creating a plan bead with `--type plan(PATH)`, the file path is stored in the
`design` field. The ACE TUI can navigate from a bead to its linked SDD file.

For SDD-generated epics, `PATH` should be the shared plan reference emitted by the plan
approval flow: `sdd/plans/...` in in-tree mode, `.sase/sdd/plans/...` in local and
legacy separate-repo modes, or `<YYYYMM>/...` in the split `--plans` repository. SASE
resolves those references against the effective SDD root when launching bead work. For
manual commands and prompts, `SASE_SDD_PLANS_DIR` or `sase repo path plans` is less
ambiguous than guessing which relative prefix applies.

### Task Bead Surfaces

ACE's Artifacts → Plans pane renders standalone task beads in their own section with an
orchid `◆` type marker and mint `◇ ready` state. The detail view labels the type as
`task`. The `s` action only changes status; it cycles a task through
`open → ready → in_progress → closed → open` (`claimed → ready`) but does not launch a
worker when it reaches `in_progress`. The `e` action edits its title and description.
The pane's `w` action remains epic-only; launch tasks from their `TaskTriage`
notification or with `sase bead work <task-id>`.

Generated bead pages and the mobile bead bridge expose the same literal type and status.
Default non-closed mobile listings include ready tasks. ACE's task detail exposes stored
metadata and each dependency's status, but it does not show a reverse blocker list. When
task design metadata is present, the pane shows its plan reference without loading the
linked document. Its shared phase/task presentation also shows the `small` fallback for
a task with no stored size.

### Plan Approval Flow

The plan approval popup in ACE includes normal approval and **E** (Epic) actions. Normal
approval saves to the resolved SDD `plans/` directory with `tier: tale`. Every epic
approval surface behaves the same way — ACE, `sase plan approve --kind epic`, Telegram,
and bare gate responses all submit one deduplicated global `detached` task that runs
`sase bead work <plan-file> --yes-to-all` from the project's primary workspace, then
record that the host owns the launch in the planner response. Because the task is
detached and global, no interactive session owns it: it survives the approving process,
appears in every default `sase task list` and Tasks-tab scope, is streamable with
`sase task show <id> --follow`, supports kill, and still emits the epic-completion
notification. The approval passes `--artifacts-dir` (and `--cl-name` when a ChangeSpec
is involved), so a successful launch back-fills the epic ID and committed plan path into
planner metadata.

There is no planner-side subprocess fallback and no foreground path. If the host cannot
resolve the primary workspace, finds the approved-epic plans store unusable, or fails to
submit the task, approval fails loudly and reports the
`sase bead work <plan> --yes-to-all` resume command rather than launching invisibly.
After a successful handoff, the planner publishes its prompt archive entry, finishes as
`EPIC APPROVED`, and does not race the command for ownership of the epic plan file.
