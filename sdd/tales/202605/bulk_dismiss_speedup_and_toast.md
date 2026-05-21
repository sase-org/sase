---
create_time: 2026-05-21 15:06:07
status: done
prompt: sdd/prompts/202605/bulk_dismiss_speedup_and_toast.md
---
# Bulk-Dismiss Speedup + Toast Reliability

## Problem

The `X` keymap opens the Agent Cleanup modal on the Agents tab. The dismiss-only branches of that modal
(`dismiss_panel_done`, `dismiss_all_done`) route to `_do_dismiss_all` in
`src/sase/ace/tui/actions/agents/_dismissing.py`. The kill-and-dismiss branches route through `_do_bulk_kill_agents` in
`_killing.py`. Both paths report two distinct symptoms:

1. **Bulk dismiss is slow** (worse than a single dismiss × N expectation).
2. **The "Dismissed N agents" toast only sometimes appears.**

## What's actually happening

### Slowness — the real hot spots

The bulk path is _already_ one batched persistence transaction (not N parallel ones), so the regression isn't an obvious
"loop over agents and re-save". The slowness comes from work that grows with the _total_ dismissed set rather than the
_newly dismissed_ delta:

- **`sync_dismissed_agent_artifact_index(dismissed_snapshot)`** is called at the end of every dismiss transaction
  (`_dismissing.py:295`, `:320`). When the cached projection signature doesn't match (and a bulk dismiss almost always
  invalidates it because both `dismissed_agents.json` _and_ the bundle index signature changed), it calls
  `build_dismissed_agent_projection_inputs()` which:
  - re-runs `verify_dismissed_bundle_index()` and possibly `rebuild_dismissed_bundle_index()` (already a known
    corruption-recovery hot path — see recent commit `0d4e296c2`),
  - reads **every** dismissed bundle summary via `load_dismissed_bundle_summaries(limit=None)`,
  - sorts and ships the _entire_ identity set to the Rust binding `replace_agent_artifact_index_dismissed_agents`, which
    atomically rewrites the SQLite dismissed-identities table.

  That cost is `O(total_dismissed_lifetime)`, paid in full whenever the signature shifts. For a user who has accumulated
  many dismissed agents over time, dismissing even one new agent triggers a full projection rebuild — bulk-dismiss just
  makes it _feel_ worse because the latency lands while the user is staring at a confirmation modal closing.

- **Per-agent fallback in `_persist_bulk_dismiss_transaction`** at `_dismissing.py:307-316`. When
  `persist_cleanup_side_effect_intents()` returns `False` (no Rust-planned intents), the bulk transaction reverts to a
  python loop calling `persist_dismiss_side_effects(agent, …)` for each agent. Each call individually:
  - calls `save_dismissed_bundle(agent)` (one bundle write per agent, plus one per workflow child),
  - calls `delete_agent_artifact_index_artifacts([artifact_dir])` (one SQLite `DELETE` connection per agent rather than
    one batched delete),
  - calls `delete_agent_artifacts(artifacts_dir)` (recursive `rmtree` on artifact directories, one at a time).

  This is currently the _common path_ in many setups, because not every flow populates a Rust-planned cleanup intent set
  (`_dismiss_all_done_agents` and `_dismiss_all_done_agents_global` build the plan via `plan_dismissal_side_effects`,
  but the side-effect intent fields may be empty on agents loaded from disk vs. from ChangeSpecs).

- **The optimistic UI work runs synchronously on the UI tick _before_ the toast paints** (`_dismissing.py:137-138`).
  `notify()` is called, then `_apply_dismissal_in_memory(agents)` runs `_refilter_agents` / `_refresh_agents_display`.
  With many agents that filter/re-render is heavy enough to delay the first paint of the toast widget. On a slow tree
  rebuild the user perceives both "the X keystroke felt slow" and "the toast never appeared" (it may have appeared and
  been replaced before paint, or its timeout elapsed while the UI thread was busy).

### Toast inconsistency — why "only sometimes"

Multiple compounding causes:

1. **Order-of-operations.** Toast `notify()` enqueues a widget on the Textual screen, but the very next line runs a
   heavy in-memory mutation + re-render. Textual's toast widget paints on a future tick; if the UI tick is long enough,
   the auto-dismiss timeout (3 s default) can begin counting before the widget actually paints, and on subsequent
   re-renders the toast container can be detached/reattached during the agents-list refresh.

2. **Multiple `notify()` calls in the kill+dismiss branch.** `_do_bulk_kill_agents` in `_killing.py` emits _two_
   consecutive `notify()` calls when a single action both killed and dismissed agents (`"Killed N agent(s)"` then
   `"Dismissed M agent(s)"`). Textual stacks notifications, but back-to-back calls on the same tick can collide visually
   or one can be hidden by the modal-close animation.

3. **Error path replaces the success toast.** If `_persist_bulk_dismiss_transaction` raises, the worker emits a
   `severity="error"` toast (`_dismissing.py:173`). Because the success toast was already shown before persistence ran,
   the user can see a momentary "Dismissed N agents" toast that's immediately replaced by an error — easy to misread as
   "the toast didn't appear".

4. **Modal close timing.** The cleanup-modal `on_dismiss` callback runs the bulk action; `notify()` is fired while the
   modal is still being torn down. Toasts emitted during a screen pop can lose their paint pass on some Textual
   versions. (We've hit this before in this repo — see how single-row action toasts get re-emitted after screen pops in
   other actions.)

## Goals

- Bulk dismiss of N agents should feel **at most a small constant factor** slower than dismissing one — the per-agent
  index/bundle work should batch.
- The artifact-index projection rebuild should be **incremental** with respect to a bulk dismiss, not a full rebuild of
  all historic dismissed identities.
- The "Dismissed N agents" toast should appear **every time**, reliably, even while the agents list is re-rendering and
  the cleanup modal is closing.
- No behavioural regressions: revive still works, persistence still recovers on error, artifact index stays consistent.

## Non-goals

- Rewriting the bundle / artifact index storage layout.
- Touching the kill (process-termination) path — only the dismiss bookkeeping/persistence and the toast surface.
- Adding new keybindings or modal UX.

## Approach

Two independent fixes, sequenced so the perf win lands first and the toast fix can be validated on top of a fast path.

### Fix 1 — Make bulk-dismiss persistence actually batched

**1a. Collapse the per-agent fallback loop into a single batched call.** In `_persist_bulk_dismiss_transaction`
(`_dismissing.py:298`), when the intent-driven path is empty, gather _all_ of:

- bundles to save (parents + workflow children) for the whole batch,
- artifact dirs to delete for the whole batch,
- related agents whose notifications need dismissing,

and call:

- one `save_dismissed_bundles([...])` helper (new thin wrapper that calls the existing per-agent `save_dismissed_bundle`
  inside one os walk, no public contract change),
- one `delete_agent_artifact_index_artifacts(all_artifact_dirs)` — this already accepts an iterable, so we just stop
  calling it per-agent,
- one `dismiss_notifications_for_agents(all_related)` call (already single-shot at the Rust binding boundary; we just
  need to dedupe at the Python edge).

The per-agent `delete_agent_artifacts(rmtree)` filesystem deletes can stay in a loop — they're the unavoidable I/O cost
— but we should run them after the SQLite/bundle metadata is consistent so a partial failure leaves a recoverable state.

**1b. Make `sync_dismissed_agent_artifact_index` incremental for bulk dismiss.** The big win is avoiding
`load_dismissed_bundle_summaries(limit=None)` on the hot path. Two options, in order of preference:

- **Preferred:** add an `added: Iterable[AgentIdentity] | None = None` parameter to
  `sync_dismissed_agent_artifact_index` and a sibling Rust binding
  `extend_agent_artifact_index_dismissed_agents(index, added)` that appends rows to the SQLite dismissed-identities
  table without replacing. When the caller knows the delta (which we do — `dismissed_snapshot` minus the pre-dismiss
  snapshot is exactly the new identities), use the extend path and only fall back to full `replace` when the signature
  check shows out-of-band drift.
- **Fallback if the Rust crate isn't easy to extend right now:** keep the Python-side check but skip the bundle-summary
  scan entirely when the caller passes an explicit `dismissed: set[...]` argument — the projection inputs for the new
  identities are trivially derivable without re-reading every bundle file on disk. Cache the projection-source signature
  so the _next_ dismiss in the same session also short-circuits.

Either way, the call site at `_dismissing.py:295` and `:320` becomes
`sync_dismissed_agent_artifact_index(added=new_identities, dismissed=dismissed_snapshot)`.

**1c. Move the in-memory refilter off the toast-emitting tick.** Change `_do_dismiss_all` (`_dismissing.py:117-146`) so
the order is:

1. update `_dismissed_agents` / status overrides (cheap),
2. `self.notify(f"Dismissed {count} agent{s}")` (cheap, ~paints next tick),
3. `self.call_later(self._apply_dismissal_in_memory, agents)` — yields the UI tick so the toast can paint _before_ the
   heavy refilter runs,
4. `self.call_later(self._run_bulk_dismiss_persistence_async, ...)` as today.

The refilter must still finish before the next user interaction; deferring it by one tick is invisible to the user but
lets the toast widget reach paint.

### Fix 2 — Make the toast reliable

**2a. Move the toast to fire _after_ the screen pops.** The cleanup modal's `on_dismiss` callback synchronously calls
into `_dismiss_all_done_agents` which (after the confirmation modal) calls `_do_dismiss_all`. Wrap the final `notify()`
in `self.call_after_refresh(...)` (or schedule via `call_later`) so it is emitted after the modal pop has fully
committed. This addresses the "toast lost during screen tear-down" failure mode.

**2b. Coalesce dual toasts in `_do_bulk_kill_agents`.** When both killed and dismissed counts are non-zero, emit a
single combined toast: `"Killed N agent(s) and dismissed M agent(s)"`. One toast = no collision, and the message is more
accurate to the user's single action.

**2c. Avoid silently replacing the success toast on persistence error.** When the worker fails, instead of just
`notify("Bulk dismiss cleanup failed: …", severity="error")`, also re-state what _did_ succeed in-memory so the user
isn't confused: `"Dismissed N agents in memory, but cleanup failed: <exc>. Refresh recommended."` Keep the existing
`_schedule_agents_async_refresh()` call.

**2d. Audit single-agent dismiss notify calls.** Apply the same "`call_after_refresh` the notify" pattern in
`_dismiss_planned_agent` (`_dismissing.py:222-224`) for parity, so rapidly dismissing several agents in succession
produces stacked toasts rather than swallowed ones.

## Files touched

- `src/sase/ace/tui/actions/agents/_dismissing.py` — reorder notify / refilter, route notify through
  `call_after_refresh`, pass `added=` to the artifact-index sync, simplify bulk persistence body.
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py` — add batched helpers for bundle save + notification
  dismissal in the fallback path; no behaviour change in the intent-driven path.
- `src/sase/ace/tui/actions/agents/_killing.py` — combine killed/dismissed toast into one message; route final notify
  through `call_after_refresh`.
- `src/sase/core/agent_artifact_index_lifecycle.py` — add `added=` fast path (and the Rust-extend variant if we land
  1b-preferred); existing full-sync path remains for the signature-mismatch fallback.
- `../sase-core/crates/sase_core/...` (sibling Rust repo) — only if we pick the preferred 1b path: add an append/extend
  binding for the dismissed identities table. Per `memory/short/rust_core_backend_boundary.md`, shared backend behaviour
  belongs in `sase-core`, so the projection logic that decides delta-vs-full lives in Rust if possible, with the Python
  sync function staying thin.

## Tests

Existing coverage to lean on:

- `tests/test_agent_dismiss_persistence.py` — verifies the deferred persistence callback runs and the artifact index
  sync is invoked. Extend with a "bulk dismiss N agents emits one batched index update" assertion.
- `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py` — already exercises per-row dismiss against the real Rust
  notification store; add a bulk variant.

New tests:

- A perf-shape regression test: dismissing 50 agents must call `replace_agent_artifact_index_dismissed_agents` at most
  once (or `extend_agent_artifact_index_dismissed_agents` once) — not 50 times — and must not read every dismissed
  bundle summary when only the delta changed. Assert via spies on the binding-level functions.
- A toast test using Textual's pilot harness: confirm a "Dismissed N agents" toast is present in the notification queue
  after the cleanup modal closes for the dismiss-only branches. Cover the kill+dismiss combined-message branch too.

## Rollout

Single PR, all changes scoped to `src/sase/ace/tui/actions/agents/*` and
`src/sase/core/agent_artifact_index_lifecycle.py` (plus the optional small sase-core wire change). No migration: the
dismissed-agents JSON and the SQLite artifact index schemas are unchanged; we're only changing which _operation_ writes
to them.

## Risks

- **`added=` fast path drift.** If the in-memory `dismissed_snapshot` ever diverges from disk, an append-only path could
  miss identities. Mitigation: the existing signature check is the trusted source-of-truth; on signature-mismatch we
  still fall through to the full replace path. The fast path is a perf optimisation, not a correctness shortcut.
- **`call_after_refresh` timing.** Deferring the toast by a tick could in theory delay it past a subsequent user action
  that closes the screen. Mitigation: anchor on the _app_ (not the closing modal) so the toast outlives the screen pop.
- **Cross-runtime parity** (per `memory/short/gotchas.md` — uniform agent runtimes): none of this is runtime-specific,
  but ensure the Rust-side binding lands in `sase-core` so all frontends benefit, not just the Python TUI.
