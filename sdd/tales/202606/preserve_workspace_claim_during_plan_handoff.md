---
create_time: 2026-06-28 08:23:51
status: done
prompt: sdd/prompts/202606/preserve_workspace_claim_during_plan_handoff.md
---
# Plan: Keep the workspace claimed during plan/question handoff

## Problem statement

The agent runner submits a plan (`/sase_plan` → `sase plan propose`) and asks the user questions (`/sase_questions` →
`sase questions ask`) using the same mechanism: the CLI writes a pending marker (`.sase_plan_pending` /
`.sase_questions_pending`) into `SASE_ARTIFACTS_DIR`, then SIGTERMs the agent runner's process group. A soft SIGTERM
handler in the runner is supposed to catch the signal, leave the process alive, and let the execution loop consume the
marker — creating the approval/question notification and then **blocking in a poll loop** until the user responds. On
plan approval (with a coder/epic/legend follow-up) the runner then continues to run that follow-up agent **in the same
workspace it was already using**.

A recently shipped fix (`fix: preserve soft SIGTERM for plan handoff`) restored the soft-handler behavior that a prior
change had accidentally broken (the handler had become a hard `sys.exit`, so the marker was never consumed and the runs
stalled with no notification). That fix is correct and necessary, and it also restores the symmetric
`sase questions ask` handoff.

However, it leaves a related defect exposed. The same SIGTERM handler also runs a workspace-release callback (added
earlier to promptly free claims when a runner is _killed / dies early_, so dead claims don't linger as "starting" rows).
Now that the handler is soft, the runner keeps running after that callback releases the workspace — but during a
plan/question handoff the runner still **needs** that workspace:

1. It blocks in the approval/question poll for as long as it takes the user to respond (often many minutes, sometimes
   hours).
2. On plan approval it writes SDD files into the workspace, commits there, and runs the follow-up coder/epic/legend
   agent in that same workspace. The follow-up path does not re-claim a workspace; it reuses the original one.

Because the workspace slot was removed from the project spec `RUNNING:` field at SIGTERM time, the workspace-allocation
path can hand the _same_ slot number to a different concurrent agent. That new agent cleans/checks out the shared
directory on startup, racing and clobbering the follow-up coder's work. Before the workspace-release callback existed,
the slot stayed claimed through the entire plan → approve → code lifecycle and was released only once, at the very end.
The current behavior is a regression of that property, now made reachable again by the restored soft handler.

This is most likely to bite on a busy host running many concurrent agents (high workspace-pool pressure makes a
just-freed slot the next one handed out) combined with the naturally wide approval window.

## Goals

- A plan/question handoff keeps its workspace claim for the full lifecycle (approval/question wait, SDD file writes, and
  the follow-up coder/epic/legend run), so the slot is never re-handed to another agent while the runner is still using
  it.
- A genuine kill or early/forced death still releases the claim promptly (preserve the original intent of the
  prompt-release callback so dead claims don't linger as "starting" rows).
- The single end-of-run release in the runner's `finally` block remains the authoritative release for the handoff case
  (it already always runs under the soft handler).

## Background: why the on-signal release is now redundant for correctness

With the soft handler, the runner never exits _from the signal_; it always returns to normal control flow and reaches
its `finally` block, which already releases the workspace. So the on-signal release no longer protects against "exiting
without releasing" — its only remaining value is _promptness_ for the genuine-kill case (releasing inside the handler
rather than a beat later in `finally`). For the handoff case it is purely harmful: it frees a slot the runner is about
to keep using.

The runner can distinguish the two cases at signal time using the same signal the rest of the loop already relies on:
the presence of a pending handoff marker in the current phase's artifacts directory. The plan/question CLIs write (and
`fsync`) that marker _before_ sending the SIGTERM, and the runner republishes `SASE_ARTIFACTS_DIR` to the current
phase's artifacts directory at the top of every loop iteration, so the marker is reliably visible to the handler in
every round (initial planner, feedback replans, and the accepted-plan follow-up).

## Proposed changes

### 1. Make the on-signal workspace release skip pending handoffs (primary)

Change the runner's workspace-release SIGTERM callback so it releases the claim **only when no plan or question handoff
is in progress**. Detect an in-progress handoff by checking for a pending marker (`.sase_plan_pending` or
`.sase_questions_pending`) in the current artifacts directory (resolved from the published `SASE_ARTIFACTS_DIR`, falling
back to the runner's known artifacts directory).

- No marker present → genuine kill / early death → release promptly, exactly as today.
- Marker present → handoff in progress → skip the on-signal release. The runner keeps the claim and the end-of-run
  `finally` block releases it once, after the follow-up coder/epic/legend run completes (or after the plan is rejected /
  the question flow ends).

Keep the check cheap and exception-safe (a stat/`exists` on two paths); any failure to read the marker should fall back
to the existing behavior so we never _fail to release_ on a real kill.

This keeps the soft-handler fix intact (the marker is still consumed and the notification still created) and restores
the "claim held for the whole lifecycle" property for both the plan and question handoffs.

### 2. Confirm the single-release invariant in `finally`

Verify the end-of-run release path still releases the claim exactly once for the handoff case (it does today via the
`finally` block) and that skipping the on-signal release does not leave a path where the claim is never released. The
release is keyed on claim identity (workspace number + workflow + cl_name), so a late release cannot remove a different
agent's claim; this plan does not change that.

### 3. Tests

- **On-signal release, genuine kill:** with no pending marker in the artifacts dir, the handler releases the workspace
  (current behavior preserved) and does not `sys.exit` (soft contract preserved).
- **On-signal release, plan handoff:** with `.sase_plan_pending` present, the handler does **not** release the
  workspace, still sets the killed flag, and does not `sys.exit`.
- **On-signal release, question handoff:** same as above with `.sase_questions_pending`.
- **End-to-end marker survival (regression for the original bug):** after a soft SIGTERM with a pending plan marker, the
  execution loop consumes the marker and reaches the approval path (notification creation), rather than exiting early.
  This closes the test gap left by the original fix, which only asserted the handler's shape.

## Verification

- `just install` then `just check` (per repo policy), after the linked Rust core workspace is refreshed so the binding
  matches this tree.
- Targeted runner tests for the new handoff-aware release behavior.
- Behavioral sanity: drive a plan propose, confirm the slot stays in the `RUNNING:` field through the approval wait and
  the follow-up coder run, and is released exactly once at completion.

## Risks and considerations

- **Stale marker on a genuine kill:** markers are read-and-deleted by the loop each round, so a pending marker normally
  means a real, current handoff. If a stale marker could linger, the on-signal release would be skipped on a genuine
  kill and the claim would instead be freed a beat later by `finally` (and, failing that, by the existing fast
  stale-claim reaper). This degrades only _promptness_, never correctness, and matches how the loop itself treats marker
  presence.
- **Do not regress the prompt-release fix:** the change must not weaken prompt release for genuine early/forced death —
  that path has no handoff marker and must continue to release inside the handler.
- **Out of scope:** recovering the already-stalled agents (their runner processes are dead and they have no approval
  notifications — they must be re-run; their archived plan files are preserved). Also out of scope: changing the
  workspace allocation/claim model or the approval poll design.
