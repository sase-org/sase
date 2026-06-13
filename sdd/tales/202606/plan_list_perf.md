---
create_time: 2026-06-13 14:06:06
status: done
prompt: sdd/prompts/202606/plan_list_perf.md
---
# Plan: Make `sase plan list` Fast

## Problem

`sase plan list` (also the default `sase plan`) takes **~10 seconds** to print a small dashboard of proposed / approved
/ rejected plans. It is the CLI surface a user hits constantly while reviewing the plan pipeline, and 10s per invocation
is painful.

Measured on this machine (`~/.sase` with 10 projects, **16,561** `agent_meta.json` files, **2,851** archived plan
files):

```
run 1: 10.04s   run 2: 9.66s   run 3: 10.04s
```

## Root cause (from cProfile)

The command does **TUI-scale work to produce a tiny summary**. cProfile cumulative breakdown of `build_plan_inventory`
(~14.8s under profiler; ~10s wall):

| Stage                                            | Cost       | Why                             |
| ------------------------------------------------ | ---------- | ------------------------------- |
| `_collect_proposed_plans`                        | **~12.5s** | dominant                        |
| └ `_load_live_plan_agents` → `load_all_agents()` | **~9.4s**  | loads the entire agent universe |
| └ `_available_plan_notifications`                | **~2.0s**  | N+1 store reads                 |
| `_collect_approved_plans`                        | **~1.8s**  | reads all 16.5k meta files      |
| `_collect_rejected_plans` / display              | minor      | path resolution                 |

Three independent hotspots:

1. **Proposed plans load the whole TUI agent model (~9.4s).** `_collect_proposed_plans()` →
   `visible_pending_plan_notifications()` → `_load_live_plan_agents()` calls `load_all_agents()` purely to filter agents
   down to "live" status buckets (`Stopped/Starting/Running/Waiting`) and then match them against pending `PlanApproval`
   notifications. `load_all_agents()`:
   - runs the **unbounded** source artifact scan (`_scan_artifacts_for_loader`), walking/parsing the full 16.5k-meta
     artifact tree in Rust (~2.2s) — note this is _worse_ than the TUI's own refresh, which uses the bounded index
     snapshot;
   - runs `apply_status_overrides`, whose `_classify_diff_badges` → `diff_has_real_edits` → `changed_files_from_diff`
     **parses ~470 diffs purely for cosmetic badges (~2.6s)**;
   - runs `_feedback_child_progressed_past_review` over the full agent list (~1.3s, scales ~O(N²) with universe size);
   - expands workflow agent steps (~1.5s) and sweeps every ChangeSpec for HOOKS/MENTORS/COMMENTS agents. None of the
     diff badges, workflow-step rows, or hook/mentor/comment agents affect which proposed plans are shown.

2. **Notification store is re-read once per notification (~2.0s).** `_available_plan_notifications()` calls
   `action_state_for_notification()` for each of the 74 `PlanApproval` notifications, and every call does
   `_load_store(include_legacy=True)`, which re-reads and re-parses **both** the pending-actions store and the legacy
   telegram store from disk. That is 148 file reads/JSON parses for what is one immutable snapshot per command.

3. **Approved plans read every meta file on disk (~1.8s).** `_collect_approved_plans()` globs
   `*/artifacts/**/agent_meta.json` (all 16,561 files) and `json.loads` each one to surface the **10** most-recent
   approved plans. This is O(all history) for a fixed-size display.

## Goals

- Reduce `sase plan list` wall time from ~10s to **well under 1s** on this dataset (target ≥10× faster), and keep it
  roughly flat as agent history grows.
- **No change to output** for proposed / approved / rejected sections in the common case — same rows, same ordering,
  both human and `--json` renderings.

## Non-goals

- No redesign of the plan-approval data model or storage layout.
- No new TUI behavior; this is a read-only CLI speedup.
- Not chasing sub-millisecond perfection on the minor display-path helpers beyond trivial cleanups.

## Design

Three independent fixes, each landable and verifiable on its own. Fix 1 is the overwhelming majority of the win.

### Fix 1 — Stop loading the whole agent universe for proposed-plan liveness

`visible_pending_plan_notifications()` only needs: the set of agents currently in a **live** status bucket, carrying the
identity fields used by `notification_matches_any_agent` (`cl_name`, `agent_name`, `raw_suffix`, `project_file`,
`workspace_dir`, plus `status` for bucketing). Replace the `load_all_agents()` call with a **lightweight live-agent
loader** that:

- **Bounds the artifact set** to active + recently-completed agents via the existing index-backed snapshot path (the
  same `query_agent_artifact_index` "active + recent_completed, not full history" query the TUI already uses for fast
  first paint in `_artifact_snapshot_for_tui_load`), instead of the unbounded `_scan_artifacts_for_loader()`. This
  collapses the Rust walk and shrinks every downstream pass.
- **Skips cosmetic / irrelevant work**: no `_classify_diff_badges` (the ~2.6s diff parsing), no workflow-step expansion,
  no ChangeSpec HOOKS/MENTORS/COMMENTS sweep, no final sort/reorder. These do not affect bucket membership or
  notification matching.
- **Preserves plan-review status semantics** (correctness-critical, see below): retains the status-override that
  surfaces a finished agent whose submitted plan is still awaiting review (`DONE → PLAN`, via
  `_has_unreviewed_submitted_plan`), because that override is what makes such an agent fall into a _live_ bucket.

Implementation shape: factor the minimal pieces out of `_load_agents_from_all_sources` / `_normalize_loaded_agents` into
a focused `load_live_plan_agents()` (in the agent_loader module) that runs only the running-field load + bounded index
snapshot + the plan-review status override, and have `plan_candidates._load_live_plan_agents()` call it. Keep the
existing `agents=` injection seam in `visible_pending_plan_notifications` for tests.

**Correctness safeguard (the one real risk).** A `PlanApproval` notification's agent can have base status `DONE`; only
the `_has_unreviewed_submitted_plan` override lifts it into the `Stopped`/`PLAN` (live) bucket. Two requirements:

- the lightweight loader **must** keep that override; and
- the bounded "recent-completed" window **must** include those agents. This is naturally satisfied because available
  `PlanApproval` notifications are already gated to **<24h** (`STALE_THRESHOLD_SECONDS`) by
  `action_state_for_notification`, so their agents are recent. The implementation must verify the recent window
  comfortably covers the 24h staleness horizon; if a bounded snapshot ever proves too small, fall back to the surgical
  alternative below.

**Alternative / escalation (if bounding proves insufficient):** invert the lookup. The available `PlanApproval` set is
tiny; resolve each notification directly to its artifact dir(s) by identity/timestamp and scan only those via
`scan_agent_artifact_dirs`, classifying each in isolation. This is O(available notifications) rather than O(all agents)
and removes any dependence on window size, at the cost of more identity→dir resolution logic. Recommended only if the
bounded-index approach can't guarantee coverage.

### Fix 2 — Load the pending-action store once

Make `_available_plan_notifications()` read the store a single time and reuse it. Add a store-injection path to
`action_state_for_notification` (an optional preloaded-store argument, or a small batch helper in `pending_actions`) so
the per-notification state classification operates on one in-memory snapshot. This turns 148 file reads into 2. Public
single-notification behavior is unchanged.

### Fix 3 — Bound the approved-plan meta scan

`_collect_approved_plans()` only needs the **N most-recent** approved plans. Avoid reading all 16.5k meta files:

- Iterate candidate meta files **newest-first** and **stop early** once `limit` distinct approved `plan_key`s are
  collected within a bounded recent window. Recency is available from the artifact dir's embedded 14-digit timestamp
  (`.../artifacts/<type>/<YYYYMMDDHHMMSS>/agent_meta.json`), so ordering needs no per-file `stat`.
- Document the bounded window with a `log`/comment so truncation is explicit rather than silently "complete".
- Preferred refinement (if the indexed record already carries `plan_approved` + `plan_path` + timestamp): source
  approved rows from the same index query as Fix 1 and skip raw meta reads entirely. Treat this as an optional
  optimization gated on the index schema actually exposing those fields; otherwise the bounded newest-first scan is the
  safe default.

### Fix 4 — Trivial display cleanup

`_display_path()` recomputes `sase_home().resolve()` and `Path.home().resolve()` on every call. Hoist these to
module-level/once-per-build constants. Negligible but free.

## Rust core boundary

This work stays on the Python/CLI presentation side and **reuses existing `sase_core_rs` scan/index APIs**
(`query_agent_artifact_index`, `scan_agent_artifact_dirs`, the `AgentArtifactScanOptionsWire` bounding knobs) — it does
not reimplement scanning in Python. No new Rust API is anticipated. The one place to watch: if the index query does not
already return waiting/active agents with the identity fields the matcher needs, that gap belongs in `../sase-core`
(wire + binding + tests) rather than a Python workaround. Confirm during implementation; the TUI consumes the same data,
so it is expected to be covered already.

## Testing & verification

- **Behavior parity:** add/extend a test that builds the inventory through the old full path and the new lightweight
  path against a fixture `~/.sase` tree and asserts identical `proposed` rows (ids, ordering) — especially a case where
  the plan-approval agent is `DONE` with an unreviewed plan, to lock in the override.
- **Store-load count:** assert `_available_plan_notifications()` reads the store once (e.g. patch
  `_load_store`/`_load_json` and count calls).
- **Approved early-stop:** fixture with many meta files but few approved; assert the correct newest `limit` rows and
  that far fewer files are read.
- **Regression guard:** existing `sase plan list` / `plan_inventory` tests must pass unchanged; `--json` output must be
  byte-stable for a fixed fixture.
- **End-to-end timing:** re-run the 3× wall-clock measurement; expect sub-second.
- Run `just check` before completing.

## Rollout

Land as three commits (Fix 1; Fix 2; Fix 3 + Fix 4) so each speedup is bisectable and independently revertable. Fix 1
alone takes the command from ~10s to roughly ~2s; Fixes 2–3 close most of the remainder.

## Expected outcome

|                        | Before   | After (target) |
| ---------------------- | -------- | -------------- |
| Proposed (load agents) | ~9.4s    | <0.3s          |
| Notification store     | ~2.0s    | ~0.03s         |
| Approved plans         | ~1.8s    | <0.3s          |
| **Total wall**         | **~10s** | **<1s**        |

And the cost stays roughly flat as `~/.sase` history grows, because no stage remains O(all agents) / O(all meta files).
