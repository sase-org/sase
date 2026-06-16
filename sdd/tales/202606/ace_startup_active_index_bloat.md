---
create_time: 2026-06-15 21:44:59
status: done
prompt: sdd/prompts/202606/ace_startup_active_index_bloat.md
---
# Plan: Fix the Residual `sase ace` Startup Slowdown (Artifact-Index Active-Tier Bloat)

## Context: Verifying the Prior Fix

The previous change (`94af72277`, plan `sdd/tales/202606/ace_tui_startup_perf.md`) deferred live workspace VCS diff
classification out of the Agents-tab startup loader. **I verified this fix works and is sound:**

- Direct loader timing: `load_agents_from_disk_with_state` is now ~1.4–2.2s (was ~18s); `get_vcs_provider` is never
  called during the loader pass; 0 live hints are set by the loader.
- Real traced tmux startup (`SASE_TUI_TRACE=1`): `agents.load_from_disk` = ~2.24s contains no live diff work; the
  deferred `agents.live_hint_refresh` runs at +4.0s (off the critical path) for only 6 candidates; the loader runs in a
  worker thread (`asyncio.to_thread`), so it never blocks the event loop.
- End-to-end time-to-interactive dropped from ~18s to **~2.7s**.

So the prior diagnosis (live VCS work dominated startup) was correct and the fix landed the big win.

## Problem Summary: The Remaining ~1.1s Is a _Different_ Root Cause

Profiling the **post-fix** warm loader (1.67s) shows the dominant residual cost is a single Rust call,
`sase_core_rs.query_agent_artifact_index`, at **~1.04–1.14s (≈62% of the loader)**. This is not the live-VCS problem; it
is artifact-index **"active"-tier bloat**, and the previous plan did not touch it.

Measured root cause:

- The Tier 1 startup query (`_query_artifact_index_for_loader` in `src/sase/ace/tui/models/agent_loader.py`) requests
  the active set with **`active_limit=None`** — the entire active tier, unbounded.
- The index defines "active" as `has_done_marker = 0 OR workflow_status NOT IN (terminal)`
  (`crates/sase_core/src/agent_scan/index.rs::active_where`). This set has grown to **~4,600 records** — but **0 are
  actually running and only 97 are waiting**. The remaining ~4,500 are abandoned/killed/crashed runs that never wrote a
  done marker and never age out. (4,530 of them are in the `sase` project alone.)
- The Tier 1 query pays for this bloat **twice**, both scaling with the active-record count:
  1. **Active fetch + deserialize** of all ~4,615 no-done-marker records: **~671ms**.
  2. **`repair_stale_rows_for_query`** (runs on every Tier 1 query because `include_recent_completed=True`) SELECTs
     _all_ ~4,600 active rows and **stats the filesystem** for each (`MarkerSignatures::from_artifact_dir`) to detect
     drift: **~628ms**. This pass ignores `active_limit`.
- Only ~416 agents (≈14 visible rows) survive into the UI, so almost all of this work is thrown away.

### Why the Obvious Python-Side Fix Is Unsafe

Simply bounding `active_limit` in the Tier 1 query is **not** acceptable. The active ordering is
`ORDER BY timestamp DESC` with no priority for running/waiting, so the newest records are mostly recently-abandoned
runs. Measured:

| `active_limit`   | query time | waiting agents kept (of 97) |
| ---------------- | ---------- | --------------------------- |
| `None` (current) | ~1137ms    | 97                          |
| 500              | ~681ms     | 19                          |
| 200              | ~646ms     | 14                          |

A naive bound would drop **78–83 of the 97 waiting agents** from first paint — the user's most important inbox (agents
blocked on input) — until the background Tier 2 idle reconcile backfills. That is a real UX regression, so the fix has
to live where the data lives: in `sase-core`.

## Goals

1. Cut the Tier 1 startup query from ~1.1s toward ~0.3s by removing the active-tier bloat at its source, targeting
   end-to-end startup of roughly ~1.8–2.0s (down from ~2.7s).
2. Never drop a running/waiting agent from first paint — full inbox correctness is non-negotiable.
3. Keep the existing Tier 1 (fast subset) → Tier 2 (idle full-history reconcile) architecture intact.
4. Add tests/benches that prevent the active tier from silently re-bloating and that lock the inbox-safety.

## Non-Goals

- Do not revisit the live-VCS deferral — it is correct and already deferred off the critical path.
- Do not change the Tier 2 reconcile semantics or the `recent_completed` window.
- Do not reduce visible history or change which agents are _eventually_ shown; only what first paint must scan.

## Implementation Approach

This is primarily a `sase-core` change (the artifact index and its query semantics are core backend logic per the
Rust-core boundary rule), with a small safe cleanup in this repo.

### 1. Shrink the active working set at the source (sase-core — primary)

Add an index-maintenance step that **terminalizes genuinely-dead active records** so they leave the "active" tier and
fall into recent-completed/history. A record is a safe terminalization candidate when it has no done marker, no live
running claim (no `running.json` / workspace claim), is not waiting, and is conservatively stale (artifact dir untouched
beyond a threshold). Mark such rows with a synthetic terminal/abandoned state.

- Run it from the existing **background** maintenance path (the startup dismissed-index sync worker, which already runs
  off the paint thread), never on the hot query.
- Make it idempotent and incremental so the first run drains the ~4,600-record backlog and subsequent runs are cheap.
- This single change shrinks `active` from ~4,600 to the true live set (low hundreds), which cuts **both** the active
  fetch and the `repair_stale_rows` scan — even an unbounded fetch becomes cheap afterward.

This is correctness-sensitive (a momentarily-missing running marker must not hide a live agent), so the threshold must
be conservative and covered by `sase-core` tests for the race cases.

### 2. Make the active query inbox-safe and boundable (sase-core — supporting)

Change `active_where`'s `ORDER BY timestamp DESC` to prioritize the live inbox first, e.g.
`ORDER BY (running OR waiting) DESC, timestamp DESC`. With this ordering, applying a bounded `active_limit` becomes safe
(running/waiting are kept first), enabling the Python Tier 1 loader to set a defensive bound as belt-and-suspenders
against future bloat without risking the inbox.

### 3. Take the stale-repair scan off the hot query (sase-core — supporting)

`repair_stale_rows_for_query` currently does O(active rows) filesystem signature reads on _every_ Tier 1 query. With the
inotify artifact watcher already driving incremental index updates, scope this down: repair only the rows actually being
returned (post-limit), or cap/sample it, or move the full sweep into the background maintenance pass from step 1. The
hot startup query should not stat thousands of artifact dirs.

### 4. Eliminate O(N²) status-override scans (this repo — secondary, safe)

`apply_status_overrides` calls `_feedback_child_progressed_past_review` and `_has_unreviewed_submitted_plan`, each doing
`any(... for child in all_agents)` per agent — ~362K genexpr iterations for 416 agents (~0.08–0.11s). Prebuild a
`parent_timestamp -> children` index once per load and have these helpers consult it. Small, low-risk, in-repo win that
also stops this cost from growing with agent count.

## Verification

- Re-run direct loader timing and the `query_agent_artifact_index` micro-benchmark; confirm the Tier 1 query drops from
  ~1.1s toward ~0.3s and the active record count reflects the true live set.
- Assert first-paint inbox safety: the number of running/waiting agents in the Tier 1 snapshot must equal the
  unbounded-query count (all 97 waiting preserved).
- Real `SASE_TUI_TRACE=1 sase ace --tmux` startup: confirm `agents.load_from_disk` shrinks and the startup stopwatch
  ends sooner, with no regression to the deferred `live_hint_refresh`.
- `sase-core`: unit tests for the terminalization thresholds (including the missing-running-marker race) and the new
  active ordering. `sase` repo: a guard test that the Tier 1 query/loader preserves waiting agents and that the
  status-override pass is no longer O(N²).
- Run `just check` in this repo, and the `sase-core` test suite for the Rust changes.

## Expected Result

After draining the abandoned-active backlog and keeping the active tier bounded to the real live set, the Tier 1
artifact-index query stops being dominated by thousands of dead records scanned twice. The Agents first-load path should
fall from ~1.1s of index work to a few hundred ms, taking end-to-end startup from ~2.7s to roughly ~1.8–2.0s, while
every running/waiting agent still appears on first paint.
