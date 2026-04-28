# Research: Finishing `sase commit` After Agent-Resolved Merge Conflicts

## Problem Statement

When an agent runs its `/sase_git_commit` or `/sase_hg_commit` skill, the command invokes `sase commit`, which runs
`CommitWorkflow.run()`. The workflow dispatches a VCS-specific operation (`create_commit`, `create_proposal`, or
`create_pull_request`). That dispatch internally performs multiple substeps — e.g. for git: `merge_with_master` →
`git commit` → bead amend → `push_with_retry`; for hg (Google plugin): `hg commit` + `hg evolve` + mail / upload.

If any substep **inside** the dispatch raises a merge conflict, the dispatch returns `(False, err)` and
`CommitWorkflow.run()` returns `False` at `workflow.py:154`. The agent observes the failure, resolves conflicts manually
(which it does competently — see the attached `sase ace` snapshot), and the local VCS state ends up correct and
committed.

However, every post-dispatch step in `CommitWorkflow.run()` is silently skipped:

| Step                      | File:line                         | Applies to      | Consequence if skipped                                 |
| ------------------------- | --------------------------------- | --------------- | ------------------------------------------------------ |
| `create_changespec`       | `workflow.py:160`                 | PR only         | No ChangeSpec row → CL not tracked in `.gp` file       |
| `write_result_marker`     | `workflow.py:171`, `186`          | All methods     | `commit_result.json` missing → xprompt post-steps fail |
| `append_commits_entry`    | `workflow.py:178`                 | commit, propose | No COMMITS drawer line → diff/chat/plan not linked     |
| `upload/push` (provider)  | inside dispatch (after conflict)  | All             | Local commit never reaches remote                      |
| `_post_commit_bead_amend` | `_git_commit_dispatch.py:120–140` | All             | Bead note not attached to commit                       |

For hg (Google plugin), dispatch also encompasses the `mail`/`upload` step. When the conflict resolves mid-dispatch, the
commit exists locally but is not mailed, not tagged with the bead, not linked to the ChangeSpec, and no
`commit_result.json` is written — so downstream xprompt post-steps that read the marker also fail.

The agent in the snapshot attempts to reason about the state manually (`hg log`, `hg parent`, `hg update tip`, etc.),
but it has no way to run the missing sase-side bookkeeping. The user's hand-held "I successfully applied and verified
the requested code review changes" report is, from sase's perspective, a false positive: the ChangeSpec and project
files are now stale.

## Current Architecture Summary

1. **Skill** (`src/sase/xprompts/skills/sase_git_commit.md`, `sase_hg_commit.md`) — markdown instructions telling the
   agent to call `sase commit -M … -f … --bead-id …`.
2. **CLI handler** (`src/sase/main/cl_handler.py:12`) — builds the payload and invokes
   `CommitWorkflow(payload, method).run()`.
3. **Workflow** (`src/sase/workflows/commit/workflow.py:61`) — orchestrates pre-dispatch prep, dispatch, and
   post-dispatch tracking.
4. **VCS dispatch** (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`, plus hg plugin) — performs the actual VCS
   commands.
5. **Post-commit tracking** (`src/sase/workflows/commit/commit_tracking.py`) — captures the diff, writes the result
   marker, appends COMMITS entries, creates ChangeSpecs.

Failure-mode contract today: on any dispatch failure, the workflow returns `False` and the CLI exits non-zero. No state
is persisted to allow resumption, and the agent has no affordance for finishing the bookkeeping after it resolves the
conflict.

## Precedent: `sync.yml`

An existing pattern partially solves a sibling problem. `src/sase/xprompts/sync.yml` defines an xprompt workflow with
three steps: setup → `sync_attempt` (Python) → `resolve` (agent step with `repeat: until all_resolved max: 20`) →
`report`. When a sync produces conflicts, the xprompt delegates resolution to the agent with explicit VCS-specific
instructions. The VCS provider already exposes the primitives `is_sync_in_progress()`, `get_conflicted_files()`, and
`continue_sync()` on `VCSProvider` (`_base.py:182–206`).

This tells us two things: (1) agent-driven conflict resolution is an established pattern in sase, and (2) the VCS
provider layer already distinguishes "in progress / paused" from "failed". We can lean on both.

## Alternative Solutions

### A. Resumable `CommitWorkflow` with a checkpoint file + `sase commit --resume`

`CommitWorkflow.run()` writes a JSON checkpoint after each completed post-dispatch step to a stable path (e.g.
`$SASE_ARTIFACTS_DIR/commit_state.json`, with a `~/.sase/commit_state/<session>.json` fallback). The checkpoint records:
`method`, `payload` (with workflow-mutated fields), `diff_path`, `cl_name`, `project_file`, `reserved_name`,
`base_cl_name`, `parent_cl_name`, `commit_hash`, `cs_name`, `entry_id`, and a list of `completed_steps`.

Add `sase commit --resume` which, in lieu of doing a fresh dispatch, reads the checkpoint, probes current VCS state
(e.g. `git rev-parse HEAD`), runs any substep that was skipped, and cleans up the checkpoint on success. The skill gains
a new "if a merge conflict happens" section telling the agent to resolve per VCS-specific steps and then run
`sase commit --resume`.

- **Pros:** Small additive change; uses existing workflow code paths; keeps the agent in the loop (it is already good at
  resolution); no new subprocess orchestration; post-commit operations always run exactly once; resilient to the agent
  re-running accidentally (checkpoint enables idempotency).
- **Cons:** Two surface areas to keep consistent (fresh run vs. resume); stale checkpoint files possible if the agent
  walks away; need to handle "partial dispatch" (e.g. git committed but never pushed) in the resume path; extra unit
  test surface.

### B. Split `sase commit` into `--vcs-only` and `--finalize` subcommands

The skill teaches the agent to always run the two commands sequentially: `sase commit --vcs-only` then
`sase commit --finalize`. On conflict, the agent only re-runs the failed phase. Each command is a narrower concern.

- **Pros:** Clear phase boundary; no hidden state.
- **Cons:** Breaks the current one-shot UX for the common (no-conflict) path; agent must remember to run both, and will
  drift; every existing skill / caller / test needs update; does not actually simplify failure handling (finalize still
  has to inspect VCS state to know what happened).

### C. Embed `sase commit` in a new xprompt workflow that wraps the sync-style pattern

Write `commit.yml` analogous to `sync.yml`. A `dispatch_attempt` Python step runs the commit up to the conflict point
and reports `{success, has_conflicts, resolved_payload}`. A `resolve` agent step (repeat until clean) handles conflicts.
A `finalize` Python step runs the post-commit bookkeeping.

- **Pros:** Mirrors the established sync pattern; keeps control flow explicit in YAML.
- **Cons:** The commit workflow is substantially more stateful than sync (diff capture, message mutation, PR name
  reservation, bead amend, ChangeSpec creation). It would still need a resumable Python core to persist state across
  xprompt steps — i.e., it reduces to solution A plus an extra layer. Also reroutes every commit through an xprompt that
  is currently driven by a skill, which is a larger UX change than the problem requires.

### D. Agent-driven conflict resolution inside the dispatch

`sase commit` itself spawns an agent subprocess when it detects conflicts, using a lightweight agent runtime call.
Post-dispatch steps then run in the same process.

- **Pros:** Single `sase commit` invocation from the calling agent's perspective; atomic.
- **Cons:** Requires sase CLI commands to act as agent runtime hosts — a pattern not currently used for `sase commit`.
  Conflict-resolution authority gets duplicated between the outer agent and the inner spawned agent; session context /
  tool permissions do not cleanly pass down; timeout and cancellation semantics become fragile. Large new surface area
  for a problem a checkpoint file can solve.

### E. Post-completion hook that finalizes deferred commits

On successful conflict resolution (detected via clean working tree + matching commit hash), a post-completion hook reads
`commit_state.json` and finishes the bookkeeping automatically. No `--resume` call required.

- **Pros:** Zero agent-side burden; fire-and-forget.
- **Cons:** The hook has no way to know whether the conflict-ridden attempt was for the currently-clean commit or for
  something else the agent did afterwards; ambiguity produces wrong COMMITS entries or double writes. Ties the commit
  lifecycle to hook scheduling, which already has its own fragility (see `sase_commit_stop_hook.py` dedup logic). Can be
  layered on top of A later if wanted.

### F. Pure skill-level instructions — "if it fails, retry `sase commit`"

Update only the skill: tell the agent "on conflict, resolve then re-run the same `sase commit` command". Make
`sase commit` detect "already committed" and skip redundant work.

- **Pros:** Simplest possible change.
- **Cons:** Requires deep idempotency work across dispatch (git `commit -m` on an empty index errors; hg behavior
  differs again). Cannot cleanly recover when the dispatch was halfway through (e.g. committed locally but never pushed)
  without a checkpoint. In practice this collapses to a less-principled version of A.

### G. Require `sase sync` before `sase commit`

Move the sync-with-remote logic out of dispatch entirely; require the agent to sync first. `sase commit` then has no
reason to merge and no reason to fail on conflict.

- **Pros:** Separation of concerns; the existing `sync.yml` already handles conflicts.
- **Cons:** Does not help `create_pull_request` (PR push can still conflict) or hg's `evolve`-during-commit; also
  significantly changes user/agent workflow; does not address the post-commit bookkeeping skip if any remaining dispatch
  step fails for any other reason (e.g. push rejected by server hook).

## Recommendation

**Adopt Solution A: a resumable `CommitWorkflow` with a checkpoint file, surfaced via `sase commit --resume` and
explicit skill instructions.**

### Why this one

- **Aligned with existing patterns.** The `sync.yml` precedent shows that agent-driven conflict resolution + structured
  continuation is the direction sase is already headed. Solution A brings that pattern to commits with the minimum
  amount of new infrastructure.
- **Preserves the thing that works.** The agent is already excellent at reading conflict markers, picking the correct
  side, and running the right `--continue` command. The snapshot the user attached proves this. Solution A does not try
  to relocate that capability.
- **Fixes the actual root cause.** The bug is that post-dispatch steps are attached to a single function return value. A
  checkpoint decouples "did dispatch finish?" from "did bookkeeping finish?" and lets the second run independently.
- **Small, additive code change.** Concretely, it involves:
  1. A `_CommitCheckpoint` dataclass + `{save, load, delete}` helpers (~60 lines).
  2. `CommitWorkflow.run()` writing the checkpoint after each post-dispatch step.
  3. A new `CommitWorkflow.resume()` entry point that reads the checkpoint, probes VCS state (commit hash, branch, clean
     working tree), and calls each missing tracking step (`append_commits_entry`, `create_changespec`,
     `write_result_marker`, provider-specific push/upload/amend).
  4. A `sase commit --resume` CLI flag wired through `cl_handler.handle_commit_command`.
  5. Two new paragraphs in the two skill files (`sase_git_commit.md`, `sase_hg_commit.md`) that describe the
     conflict-resolution recipe, following the pattern from `sync.yml` lines 29–53.
  6. A specific non-zero exit code for "conflict detected and requires agent resolution" (distinct from generic
     failure), returned when the provider sets `is_sync_in_progress(cwd) == True` or a known conflict marker is present.
- **Checkpoints are self-expiring.** Tie the checkpoint path to `SASE_AGENT_TIMESTAMP` (already used by
  `sase_commit_stop_hook.py:279`) or the commit hash, so stale ones from unrelated sessions do not collide. An orphaned
  checkpoint affects nothing if no `--resume` is called.
- **Testable.** Each tracking step is already a pure function of the checkpointed state. Unit tests can call
  `CommitWorkflow.resume()` directly with a synthesized checkpoint and assert the expected side effects without spinning
  up a real agent.
- **Failure-mode additive.** The fresh-run path is unchanged when there is no conflict; existing callers, existing
  tests, and existing xprompt post-steps keep working. Only the previously-broken case (conflict resolved mid-dispatch)
  gains new behavior.

### Why not the alternatives

- **B** doubles the agent's mental load on the common path to fix a rare path.
- **C** adds an entire YAML workflow on top of what still needs solution A underneath.
- **D** requires sase CLI commands to host agent runtimes, which is a much larger architectural commitment than the
  problem warrants.
- **E** is recoverable-only at the cost of ambiguity. It can be layered on top of A later if the agent turns out to
  forget `--resume` in practice.
- **F** needs most of A's idempotency work without the clean resume contract.
- **G** leaves the PR push and hg-evolve conflict cases unsolved.

### Risks and follow-ups

- **Checkpoint schema evolution.** Bake a `version` field into the checkpoint so future additions do not break older
  resumes.
- **Interrupted mid-tracking.** If the agent is killed between step 4 and step 5 of the post-dispatch tracking, the next
  `--resume` must tolerate partial writes. Make each tracking step idempotent (check for existing COMMITS entry by
  `entry_id` before re-appending; check for existing ChangeSpec by name before recreating; overwrite
  `commit_result.json` unconditionally).
- **Hg `mail`/`upload` in dispatch.** Audit whether these happen before or after the current `append_commits_entry` call
  path; if upload is inside dispatch, the resume must redo it safely — likely by calling `provider.upload(cwd)` when the
  checkpoint shows `upload_done=False`.
- **Skill generation.** Any skill change must follow the `long-generated-skills.md` contract: edit
  `src/sase/xprompts/skills/sase_*_commit.md`, then run `sase init-skills --force` and `chezmoi apply` so the deployed
  SKILL.md files are regenerated.
- **Telemetry.** Emit a `VCS_COMMITS` or `VCS_OPERATIONS` counter for `resume` outcomes so we can measure in production
  how often conflict-resume fires and whether it succeeds, matching the pattern at `_git_commit_dispatch.py:188–191`.
