---
create_time: 2026-06-24 06:46:34
status: done
prompt: sdd/prompts/202606/decouple_kill_dismiss_from_agents_tab.md
---
# Plan: Stop kill/dismiss cleanup from blocking Agents-tab updates

## Problem (user report)

When background tasks are busy dismissing or killing agents, a **newly launched** agent does not appear on the
`sase ace` Agents tab until _all_ of those background dismiss/kill tasks finish. Killing or dismissing agents should not
block updates to the Agents tab.

## Root cause

The Agents tab has two refresh paths:

- **Fast path — exact "artifact delta" reconcile** (`_schedule_agent_artifact_delta_refresh` →
  `_load_agent_artifact_delta_async`): reconciles only a bounded set of named artifact directories. This is the path a
  launch uses to surface a new row in ~tens of ms (`_handle_launch_results_delta` in
  `tui/actions/agent_workflow/_launch_delta.py`).
- **Slow path — broad load** (`_load_agents_async`): re-reads _all_ agents from disk. It is single-flighted through the
  `_agents_loading` flag and throttled to once per `AGENTS_LOAD_MIN_INTERVAL_SECONDS = 5s` in the auto-refresh tick.

Kill/dismiss persistence runs in background worker threads (`run_worker(thread=True)` via `_submit_cleanup_task`). As a
side effect it **deletes the killed/dismissed agents' artifact directories** under each project's watched `artifacts/`
tree (`_dismiss_persistence.persist_*` / `_killing_utils.delete_agent_artifacts` → `try_delete_agent_artifacts`).
Crucially, the in-memory agent rows were _already_ removed optimistically before the worker ran — so on the Agents tab
these deletions carry **no new information**.

The TUI runs an inotify `ArtifactWatcher` (started by default in `tui/actions/startup.py::_start_artifact_watcher`) over
exactly those `artifacts/` directories. **There is no suppression of the TUI's own file-system writes.** So each
self-inflicted deletion feeds back as an external change:

1. `_on_artifact_change` (`tui/actions/_event_refresh.py`) classifies the deleted path as "affects agents" (a suffixless
   / now-missing directory → `_artifact_path_affects_agents` returns True) but **cannot map it to a known marker file**
   (`_artifact_dir_from_known_marker_path` returns `None` for anything that is not `agent_meta.json` / `done.json` /
   `prompt_step_*.json` / etc.).
2. That unmapped-but-agents-relevant path sets `_dirty_agent_artifact_fallback_reason = "unknown_watcher_path"`.
3. While that fallback reason is armed, `_enqueue_agent_artifact_delta_paths` short-circuits — **the fast exact-delta
   path is disabled** and every Agents refresh is forced onto the expensive **broad** load.
4. The launch's own exact-delta refresh is _also_ downgraded to a broad fallback, because
   `_schedule_agent_artifact_delta_refresh` bails to broad whenever `_agents_loading`/`_agents_refresh_scheduled` is set
   (which the watcher-driven broad loads keep set) and the fallback reason is armed.
5. Because the worker keeps deleting directories for the _entire_ lifetime of the kill/dismiss work, the watcher keeps
   re-dirtying agents and re-arming the fallback. The tab is therefore pinned to slow, 5s-debounced, single-flighted
   broad reloads, and the new agent's row does not settle until the deletion event stream stops — i.e. until all
   kill/dismiss persistence tasks complete. This is exactly the reported symptom.

**Secondary aggravator:** the kill/dismiss worker threads run CPU+I/O-bound Python work (per-agent bundle JSON writes,
artifact-index/SQLite updates, rmtree, Rust notification calls) on the _same_ default thread-pool executor that the
broad load's `asyncio.to_thread` calls use, so they also contend for executor slots and the GIL with the refresh —
making each forced broad load slower still.

### Why this is presentation-layer (stays in this repo)

The incremental-refresh + inotify-watcher machinery is a TUI-specific responsiveness optimization, not shared domain
behavior. A web/CLI frontend would not need to mirror it, so by the `rust_core_backend_boundary` litmus test the fix
belongs in `src/sase/ace/tui/`. No `sase-core` wire/API change is required.

## Goal

A newly launched (or otherwise changed) agent surfaces on the Agents tab promptly **regardless of in-flight kill/dismiss
persistence**, and the TUI stops paying for repeated full broad reloads triggered by its own cleanup deletions.

## Design

Two complementary changes. (A) is the general correctness fix; (B) eliminates the wasted work at the source. Recommend
shipping both; (A) alone resolves the reported symptom.

### (A) Treat a deleted artifact directory as an _exact_ delta, not a broad fallback

A deleted artifact directory is fully self-describing: the path _is_ the agent's artifact dir (or its parent timestamp
dir). The watcher already has enough information to reconcile just that directory — there is no reason to fall back to a
full broad reload.

- In `tui/actions/_event_refresh.py`, teach `_agent_artifact_delta_dir_for_path` /
  `_artifact_dir_from_known_marker_path` to recover the exact artifact dir for a **directory-level** artifact event
  (deletion or move) by parsing the path with the existing `parse_agent_artifact_path` / sharded-`ace-run` helpers,
  instead of returning "unmapped → broad fallback".
- Result: artifact-dir deletions route through the bounded `_load_agent_artifact_delta_async` reconcile, which simply
  drops the (already-gone) row. The `unknown_watcher_path` fallback is no longer armed by deletions, so the fast delta
  path stays enabled and the launch's row appears immediately.
- This also fixes the same stall for **external** kills (Telegram / `sase agent kill` / gchat) that delete artifact dirs
  the TUI did not initiate.

### (B) Suppress the watcher feedback from the TUI's own cleanup deletions

Because the in-memory rows are already removed optimistically, the self-inflicted deletion events are pure waste even as
exact deltas.

- Add a small, thread-safe "expected self-deletions" registry on the app (a set of artifact-dir paths guarded by a lock,
  since it is written from the persistence worker thread and read on the UI thread).
- The kill/dismiss persistence path registers the artifact dirs it is about to delete _before_ calling
  `delete_agent_artifacts`, and the watcher dispatch (`_on_artifact_change` / delta-classification) drops deletion
  events whose path is in the registry (consuming/expiring the entry, with a short TTL so a missed event cannot leak).
- Net effect: the TUI's own dismiss/kill cleanup produces **zero** Agents-tab refresh work.

### (C) Secondary (optional, lower priority)

Reduce executor/GIL contention so any genuinely-needed refresh during heavy cleanup is not starved — e.g. run
kill/dismiss persistence on a dedicated bounded executor distinct from the loader's `asyncio.to_thread` pool, or
chunk/yield inside bulk persistence. Scope this only if (A)+(B) leave residual lag under large bulk kills; it is not
required for the reported symptom.

## Implementation steps

1. **Reproduce / lock in a failing test.** Add a TUI-level test that: marks several agents dismissed/killed (triggering
   artifact-dir deletion events through the watcher dispatch), then drives a launch-delta refresh, and asserts the new
   agent row appears without a forced broad `_load_agents_async`. Assert via the existing refresh-trace hooks
   (`record_agents_refresh_trace`, `data_cost` / `fallback_reason`) that no `unknown_watcher_path` broad fallback is
   emitted for a directory-deletion event.
2. **Implement (A):** directory-deletion → exact artifact-dir mapping in `tui/actions/_event_refresh.py`; keep the broad
   fallback only for genuinely unclassifiable paths.
3. **Implement (B):** expected-self-deletion registry + worker-side registration in the kill/dismiss persistence path +
   watcher-side filtering.
4. **Unit tests** for the new path classification (deleted timestamp dir, deleted sharded `ace-run` dir, deleted legacy
   agent dir, moved dir) and for the self-deletion suppression (registered path is dropped; unregistered external
   deletion still reconciles via exact delta; TTL expiry falls back safely).
5. **Regression checks:** external kill still removes the row on the next refresh; a real new agent under a sibling
   timestamp dir is unaffected; STARTING→RUNNING transition path (`_poll_starting_agent_transitions`) still works.
6. Run `just check` (and `just test-visual` is not needed — no rendering change).

## Risks & mitigations

- **Dropping a real external change as "self".** Mitigate with a short TTL on registry entries and single-consume
  semantics; the 60s sanity broad refresh (`FULL_SANITY_REFRESH_SECONDS`) remains as a backstop.
- **A deletion that should trigger broader reconciliation** (e.g. a whole project artifacts root removed). Keep the
  broad fallback for paths that do not parse to a specific agent artifact dir; only the per-agent timestamp/run dirs
  take the new exact-delta path.
- **Thread-safety of the registry** (written on worker thread, read on UI thread): guard with a lock; keep operations
  O(1).

## Out of scope

- Changing the optimistic-update model or the cleanup task queue itself.
- Any `sase-core` wire/API changes.
- Broader rework of the broad-load debounce/single-flight design (the fix removes the spurious _triggers_; the throttle
  stays as a safety net).

## Acceptance criteria

- Launching an agent while kill/dismiss persistence is in flight shows the new row promptly (single-digit refresh, fast
  delta path), not after all tasks drain.
- Refresh traces show kill/dismiss artifact-dir deletions no longer emit `unknown_watcher_path` broad fallbacks.
- `just check` passes; new and existing Agents-tab refresh tests pass.
