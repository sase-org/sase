---
create_time: 2026-06-27 15:59:35
status: done
prompt: sdd/prompts/202606/stuck_starting_agents_orphaned_claims.md
---
# Plan: Fix agents stuck in "starting" (orphaned RUNNING-field workspace claims)

## Problem statement

The `sase ace` TUI status line shows a persistent "starting" count (e.g. `3 starting`) that never clears, and the
affected agents never transition to RUNNING — to the user it looks like "no agents were launched." The condition is not
transient: it persists for many minutes and grows over time.

This plan captures the root-cause diagnosis (backed by live on-disk evidence gathered during investigation) and proposes
a layered fix.

## Background: how an agent reaches "starting" and leaves it

- The TUI builds one agent row per **`RUNNING:` field workspace claim** in each project spec
  (`~/.sase/projects/<project>/<project>.gp`). Every such row is created with `status="STARTING"` in
  `load_agents_from_running_field()` (`src/sase/ace/tui/models/_loaders/_running_loaders.py`).
- A row is promoted out of STARTING only by **metadata enrichment**: the loader reads the claim's artifact dir and looks
  for `run_started_at` / `wait_completed_at` in `agent_meta.json` (→ RUNNING) or a `waiting.json` marker (→ WAITING).
  See `_active_status_for_record()` in `src/sase/agent/running.py` and the `_meta_enrichment_*` loaders.
- `run_started_at` is written by the agent runner only **after** it has finished early setup and is about to start its
  execution loop (`record_run_started_at()` called in `src/sase/axe/run_agent_runner.py`, well into `run()`).
- The agent runner releases its workspace claim only in the `finally` block of `run()`
  (`src/sase/axe/run_agent_runner.py`, `release_workspace(...)`), i.e. a normal Python-level cleanup.

So a claim is shown as "starting" for exactly as long as: the claim exists in the `RUNNING:` field **and** no
`run_started_at`/`waiting.json` has been observed for it.

## Root cause (three interacting defects)

Evidence was collected from the live project spec, agent artifact dirs, process table, and the axe lumberjack logs.
Findings:

1. **Claims are orphaned by runners that die before `run_started_at` and never release them.** Every
   `agent_launch_spawn` event in the durable launch-timing log records `outcome=ok` — the workspace claim is written and
   the detached subprocess is created successfully. The runners then die _after_ spawn but _before_ recording
   `run_started_at`: the affected timestamps have **no artifact directory and no workflow/prompt file**, and their PIDs
   are dead. Because the runner's only claim-release path is the `finally` in `run()`, a runner that is killed (e.g.
   SIGKILL) or that dies during early setup — before reaching/installing that cleanup — leaks its claim.
   `sase bead work` is an explicit **force-reuse / relaunch surface** (`src/sase/bead/cli_work_cleanup.py`):
   re-launching an epic _terminates_ the previously-spawned deterministically-named owners. A relaunch that kills a
   just-spawned runner during its startup window orphans that runner's claim. `rollback_work_launch()` terminates PIDs
   and reverts bead state but does **not** call `release_workspace()`, so claims it abandons are not released.

2. **The only scheduled reaper of dead-process claims runs too infrequently and was not running.**
   `cleanup_stale_running_entries()` (`src/sase/ace/scheduler/stale_running_cleanup.py`) releases any `RUNNING:` claim
   whose PID is dead. It is wired into the **`checks` lumberjack only, at a 300s interval**, sequentially **after**
   `cl_submitted_checks`, which starts 150+ background checks per tick (observed `started=151`). In the captured logs,
   `stale_running_cleanup` produced healthy `released=N` lines until ~14:38, then the `checks` lumberjack log cut off
   mid-write and produced **no further cleanup runs** through the incident window — right before claims began piling up.
   The sibling fast reaper that runs every 5s, `orphan_cleanup` (`src/sase/ace/scheduler/orphan_cleanup.py`), only
   releases claims for **Reverted** CLs, so it never touches dead claims belonging to an active CL. Net effect: when the
   heavy/slow `checks` lumberjack stalls or backs up, nothing reaps dead-process claims, and they accumulate without
   bound. At time of diagnosis the project spec held **53 `RUNNING:` claims, 43 of them dead**, with leaked workspace
   slot numbers climbing monotonically.

3. **The TUI loader renders every claim with no liveness gate.** `load_agents_from_running_field()` creates a STARTING
   row for _every_ claim and never checks `is_process_running(claim.pid)`. By contrast the home-mode loaders in the same
   file (`load_running_home_agents()` and `load_running_home_agents_from_snapshot()`) already gate on
   `is_process_running` and best-effort delete the stale marker. So dead-process project claims are shown as perpetually
   "starting" until (if ever) the scheduler reaps them.

A contributing inconsistency: claims alternate between cl_name `sase` and `sase-org/sase` (derived from `#gh:sase` vs
`#gh:sase-org/sase` ref resolution in `src/sase/agent/launch_cwd_bead_work.py` via `get_ref_patterns()`). The
org-qualified form routes a runner's artifact dir and naming differently from where its claim is recorded, which can
both strand enrichment and make claim/cleanup matching inconsistent.

**Summary:** runners are leaking workspace claims when they die early (defect 1), the safety-net reaper is too
slow/fragile and effectively stopped (defect 2), and the TUI has no liveness gate of its own (defect 3). Together these
make dead claims pile up and show as agents stuck in "starting" that never launch.

## Goals

- Dead-process `RUNNING:` claims are reaped within seconds, not minutes, and never accumulate without bound.
- The TUI never shows a dead-process claim as a live "starting" agent.
- Early/forced runner death releases the workspace claim instead of leaking it.
- Project/CL naming is consistent so claims and artifacts do not diverge.

## Proposed changes

### 1. Make dead-claim reaping prompt and independent (primary)

- Decouple `stale_running_cleanup` from the slow, heavy `checks` lumberjack so a stall or backlog in
  `cl_submitted_checks` can never starve it. Options (pick during implementation):
  - Run `cleanup_stale_running_entries` as its own chop in the high-frequency `hooks` lumberjack (interval 5s), or as a
    dedicated short-interval lumberjack, alongside keeping a periodic run in `checks` as a backstop.
  - Ensure cleanup ordering/independence so a long-running `cl_submitted_checks` cannot block the cleanup chop within a
    tick.
- Update `src/sase/default_config.yml` (and any default-config docs) accordingly. Per repo conventions, keep the
  lumberjack/chop config and its documentation in sync.
- Confirm `cleanup_stale_running_entries` correctly releases every dead claim even when several claims share one
  (possibly reused) PID — release must key on the claim's identity (workspace number + workflow + cl_name), not PID
  alone, to avoid both missed releases and releasing a slot that a live, PID-reusing process now holds.

### 2. Add a liveness gate to the project RUNNING-field loader (immediate + self-healing)

- In `load_agents_from_running_field()`, skip claims whose PID is not running, mirroring the existing home-mode loaders
  in the same module. Do **not** skip alive claims, deferred (`#0`) claims with a live PID, or claims that are
  legitimately still in early startup.
- Best-effort release the stale claim on encounter (same as the home-mode path cleans its stale marker), so the TUI
  itself contributes to self-healing without waiting for the scheduler.
- Preserve the module's intent that _lifecycle_ filtering is not applied here — this is _liveness_ filtering only,
  consistent with how home-mode rows already behave.

### 3. Release claims on early/forced runner exit (root-cause hardening)

- Install a signal handler (at minimum SIGTERM) early in `run_agent_runner.py` — before/around the point the claim
  becomes the runner's responsibility — that releases the workspace claim before the process exits, covering the window
  before `run_started_at`. (SIGKILL cannot be caught; that case is covered by the prompt reaping in change 1.)
- Make the bead-work force-reuse / `rollback_work_launch()` path (`src/sase/bead/cli_work_cleanup.py`) release the
  `RUNNING:` workspace claims of any agents it terminates, instead of only sending SIGTERM and reverting bead state.

### 4. Normalize project/CL naming (contributing)

- Make ref resolution in the bead-work launch path canonicalize the org-qualified slug (`sase-org/sase`) to the
  project's canonical name (`sase`) so a claim and its runner's artifacts share one identity. Verify
  `get_ref_patterns()` consumers and the project-alias canonicalization already in `launch_cwd_bead_work.py` cover this.

### 5. Investigate the relaunch churn that generates the leak (scoped investigation)

The leak rate observed (dozens of dead claims in minutes, in repeating bursts with escalating slot numbers) suggests
agents are being relaunched far more often than expected, not just occasionally force-reused. As part of this work,
reproduce a single bead-work relaunch and confirm whether the churn originates from repeated `sase bead work <epic>`
invocations, an auto-approve/wait loop re-triggering launches, or a scheduler path. Fixes 1–4 make the system resilient
regardless, but the churn source should be identified and, if it is a true relaunch loop, fixed or rate-limited.

## Verification

- **Unit:** tests for `cleanup_stale_running_entries` releasing multiple dead claims (including shared/reused PIDs) and
  never releasing a live claim; a test that `load_agents_from_running_field` drops dead-PID claims while keeping live
  and deferred-but-live ones; a test that `rollback_work_launch` releases claims for the PIDs it terminates.
- **Behavioral / repro:** drive a launch that writes a claim then kills the runner before `run_started_at`; assert the
  claim is reaped within one fast-reaper interval and never appears as a "starting" row.
- **Live smoke:** after the fix, confirm the `RUNNING:` field does not accumulate dead-PID claims across several
  relaunch cycles and that leaked workspace slot numbers stop climbing.
- Run `just check` (after `just install`) before completing, per repo policy.

## Risks and considerations

- **PID reuse:** liveness checks and claim release must be robust to a dead claim's PID having been reused by an
  unrelated live process. Key release on claim identity, not bare PID, and prefer releasing only claims the
  scheduler/loader can positively identify as stale.
- **Frequency vs. cost:** running the reaper every few seconds touches all project specs; keep it cheap (it already only
  reads claims and releases dead ones) and avoid contention with concurrent claim writers (respect the existing
  project-spec locking).
- **Don't just hide the symptom:** the loader liveness gate (change 2) alone would visually clear "starting" while
  leaving the workspace-slot leak in place; changes 1, 3, and 5 are what actually stop claims from leaking and slots
  from being exhausted.
- **One-time cleanup:** the already-leaked dead claims in the current project spec will be released automatically once
  the prompt reaper (change 1) ships and runs; no manual edit of the spec file is required as part of the fix.

## Out of scope

- Redesigning the agent launch/spawn architecture or the lumberjack scheduler model.
- Changing how `run_started_at` / `waiting.json` enrichment determines status.
