---
title: Bead lifecycles
description:
  The status transitions for SASE beads, flag beads, bead claims, and stranded work.
---

# Bead lifecycles

This page describes the status transitions that govern beads and their claims.

## Status Lifecycle

| Status        | Icon | Description                                                                                      |
| ------------- | ---- | ------------------------------------------------------------------------------------------------ |
| `open`        | `○`  | Not started; for task beads, still a draft that is not offered for triage                        |
| `claimed`     | `◎`  | Reserved by a live agent that has not started work                                               |
| `ready`       | `◇`  | Task bead explicitly offered for triage; invalid for plan, phase, and `flag` task beads          |
| `snoozed`     | `◈`  | Task bead deferred to a wake time (or +1 target); invalid for plan, phase, and `flag` task beads |
| `in_progress` | `◐`  | Being worked on, or preassigned by an epic/task launch checkpoint                                |
| `closed`      | `✓`  | Completed, canceled, or superseded                                                               |

Status can transition between values via `sase bead update --status=<status>`. A task
normally moves `open → ready` when its draft is proposed, `ready → open` when retracted,
and `ready → in_progress` when launched. Only task beads may carry `ready`; set it after
the title, description, notes, dependencies, and any desired size or model are ready for
human review. Moving a bead to `closed` is rejected while any descendant remains open,
claimed, ready, snoozed, or in progress. Close those descendants deliberately first;
`update --status=closed` never cascades. `sase bead open <id>` reopens the bead and
every closed ancestor above it, archiving their resolution, close reason, and close
timestamp into [close history](bead-triage.md#close-history) instead of discarding them,
so a closed parent never sits above reopened work but the reason it was closed is not
lost either. `claimed` is machine-managed by the agent runner (see
[Bead Claim Lifecycle](#bead-claim-lifecycle)); do not set it by hand. `snoozed` cannot
be set through `update --status` either — snoozing requires a wake time, so
`sase bead update -s snoozed` is refused with a pointer to `sase bead snooze`, the same
way `update --status=closed` points at `sase bead close`. See
[Snoozing a Task Bead](bead-triage.md#snoozing-a-task-bead) for the full workflow.

Every new close records a typed `resolution`: `done`, `canceled`, or `superseded`.
Normal closes default to `done`; `close_reason` remains optional free text for the human
explanation. Closing an already-closed bead is a verified no-op: the command succeeds
when any supplied reason or resolution agrees with the recorded close, and fails without
writing when the request conflicts. Historical closed beads are not backfilled, so their
resolution remains unset and human-readable detail views show `(unrecorded)`.

## Flag Bead Lifecycle

A flag bead is not a fourth issue type and not the epic or task that introduced a
feature. It is a top-level task bead of type `flag`: the dedicated removal dossier for
one SASE feature flag, linked from the code-owned registry. Feature flags are a
`sase`-project concern only.

Two kinds exist, and the registry default is derived from the kind:

- **`beta`** — default **off**. The behavior is unproven; a user opts in.
- **`sunset`** — default **on**. The behavior is already the default; the flag keeps the
  old branch reachable while callers migrate.

Removing a flag deletes the **Off** branch and makes the **On** branch unconditional.

The bead carries seven required fields. `sase flag new` supplies `key`, `kind`,
`remove_by_date` (today + 90 days), and `remove_by_release` (current minor + 2). The
author writes the three a removal agent cannot reconstruct: `--when-enabled`,
`--when-disabled` (the branch deleted at removal), and `--remove-when` (the qualitative
gate). The typed body block renders those fields. `-d/--description` seeds the registry
entry's one-line help.

Create feature flags with `sase flag new <key>`, not by hand-editing the registry and
not with `sase bead create` or `/sase_new_task`. The command creates the typed task
bead, prints the registry entry to paste, and shows the both-states test checklist.
`sase bead create -T 'task(flag)'` is refused because the type is not agent-creatable.

Flag task beads stay `open` until someone is working them or they close; they do not use
`ready` or `snoozed`. A flag becomes due only when both the date and release threshold
have passed. Due-ness never flips the stored status and never changes the boolean value.
Extend both thresholds with `sase bead update <id> -b YYYY-MM-DD/release`.

AXE's bead-gate reconciler raises one `FlagTriage` gate for a live due flag task bead.
Its decisions are:

- **Remove** deletes the Off branch, makes the On branch unconditional, removes the
  registry entry, and closes the flag bead in the same change.
- **Extend** pushes both `remove_by` thresholds out and records why the flag is still
  temporary.
- **Keep** records that the behavior is permanent. It was never a feature flag; make it
  a config field and close the bead.
- **Close** abandons the removal. Use this when the flag was already removed or is
  intentionally orphaned; registry/bead integrity checks catch an inconsistent survivor.

## Bead Claim Lifecycle

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
- **Attach.** A launch whose bead was already closed when it was submitted attaches
  without reopening. Status, assignee, resolution, close reason, `closed_at`, close
  history, and every ancestor stay as they were. The same mutation appends one
  `CLOSED-BEAD LAUNCH:` note authored by the launching agent:

  ```text
  CLOSED-BEAD LAUNCH: agent <agent> launched against this closed bead; status left closed.
  Launch submitted <submitted_at>; run <run_id>.
  Prior close: <closed_at> · <resolution>.
  ```

  The `; run <run_id>` clause is omitted when the run id is absent; a missing
  `closed_at` or resolution prints `unknown`. There is no dedup: every such launch adds
  one note. The agent's prompt starts with this host notice:

  ```text
  Host notice: bead `<id>` was already closed (`<resolution>`, `<closed_at>`) when this
  run started. This run is attached to it without reopening it, and a
  `CLOSED-BEAD LAUNCH:` note on the bead records the relaunch. First check whether the
  earlier work already landed (`git log --grep <id>` and the bead's notes via
  `sase bead read <id>`). If it did, verify it and finish without redoing it; closing
  the bead again is a safe no-op. If the work is genuinely unfinished, run
  `sase bead open <id>` first and close it yourself with
  `sase bead close <id> --note "<what you verified>"` when done (the finalizer will not
  close a reopened `open` bead). If the resolution is `canceled` or `superseded`, do not
  redo the work unless this prompt explicitly asks for it.
  ```

  A close made after submission still fails the launch with `closed_while_queued`. The
  error names the bead, its `closed_at`, its resolution (plus the close reason when
  present), the submission time, and the remedy: relaunch to run it against the closed
  bead deliberately. `sase bead open` remains the path for a premature close.

- **Release.** If the owning agent dies before it ever promoted its claim, the bead
  returns to `open` with an empty assignee. The runner shutdown path releases the claim
  on ordinary kills (except when a retry handoff is pending, which keeps the claim), and
  the `bead_claim_checks` job is the backstop for SIGKILL, crashes, and reboots. It
  releases a claim only when the owning agent is dead, never promoted, and resolvable to
  its artifact; anything else is left untouched and reported by `sase doctor` instead. A
  committed release is published the same best-effort way as a claim, so a freed bead
  does not stay claimed on other hosts.
- **Reconcile.** The `bead_claim_checks` job — registered under the `waits` routine —
  runs in both directions. Next to the release pass above, an acquire pass claims a bead
  on behalf of a live agent that is waiting without a claim, which is what makes a lost
  or delayed claim self-healing within one `waits` interval. A held claim is recorded in
  the agent's `bead_claim.json` artifact file, so an agent that already holds its claim
  costs the job nothing: it is filtered out without opening a bead store. `sase doctor`
  reports the residue in either direction — a claim with no resolvable owner, and a live
  pre-launch agent whose bead is still `open`.

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

## Stranded beads

A bead is stranded when it is `in_progress` and nothing will resume it: no live session
member, no pending monitor, gate, handoff, or recovery, and no launched child epic still
working. Standalone `in_progress` task beads are included. ACE names this state ⚐
STRANDED.

Classifier states are `owned`, `delegated`, `settling` (a 120s grace after a turn ends),
`stranded`, `blocked` (an ancestor waiting on a stranded leaf), and `unknown` (the
collector could not read the session).

Stranded causes, first match wins: `followup_failed`, `failed`, `stopped`, `lost`,
`child_landed`, `close_failed`, `kept`, `unclosed`.

Remedies: fork the last turn with `%id(bead=<id>) #fork:<turn>`, or close the bead with
`sase bead close <id> --note "…"`. `sase doctor` reports stranded beads on the
`project.beads` check.

A live waiter blocked on a stranded bead raises one `wait_checks` notification for that
bead, shared by all waiters currently blocked on it.

## Related

- [Beads](beads.md)
- [Bead triage](bead-triage.md)
