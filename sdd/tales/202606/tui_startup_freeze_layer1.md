---
create_time: 2026-06-23 14:52:23
status: done
prompt: sdd/prompts/202606/tui_startup_freeze_layer1.md
---
# Plan: TUI startup agents-tab freeze — Layer 1 fix

## Context

When the `sase ace` TUI starts up, the user reported ~1 minute where the agents tab is visible but j/k navigation is
frozen. The consolidated research note `sdd/research/202606/tui_startup_agents_tab_freeze_consolidated_20260623.md`
traced this to **synchronous artifact-index maintenance running on the Textual event loop** during the first
agents-refresh apply:

```
_on_auto_refresh
  -> _load_agents_async
  -> _apply_loaded_agents_prepared            (UI-thread apply continuation)
  -> _apply_loaded_agents_prepared_inner
  -> sync_dismissed_agent_artifact_index(...)
  -> sync_dismissed_agent_artifact_index_report(...)
  -> _run_active_tier_maintenance(...)
  -> terminalize_stale_active_agent_artifact_index_rows(...)   (Rust, multi-second cold)
```

This violates the project's core TUI performance rule (no synchronous disk / JSON / DB / Rust-index work on the event
loop). The terminalizer is expensive on a cold OS page cache: it runs an unindexed `record_json LIKE '%abandoned%'` scan
plus filesystem revalidation of stale no-marker candidates, all under the global artifact-index lock.

This plan implements **Layer 1** from the research note ("remove the event-loop block"). Layers 2 (shrink the
terminalizer) and 3 (reduce the feeding data + retention) are explicitly out of scope.

### Key facts established during investigation

- The **apply path in `src/sase/ace/tui/actions/agents/_loading_apply.py` is the only on-event-loop caller** of
  `sync_dismissed_agent_artifact_index`. Every other TUI caller (`_dismissing.py`, `_marking.py`,
  `_kill_persistence.py`, `_revive*.py`) already invokes it inside worker bodies (off-thread via `_submit_tracked_task`
  / `asyncio.to_thread`). The CLI / axe callers (`agent/running.py`, `axe/run_agent_runner.py`, `agent/names/*`) run
  outside the TUI entirely. So the freeze is specific to the apply continuation.
- `sync_dismissed_agent_artifact_index_report()` **unconditionally** calls `_run_active_tier_maintenance()`
  (terminalization) after the projection sync. The projection sync alone is signature-gated and cheap on the fast path;
  the terminalization is the expensive part.
- The artifact-index lock (`agent_artifact_index_operation_lock`) is a reentrant `RLock`, so a standalone
  terminalization wrapper that re-acquires it is safe.
- A partial startup fix already exists: `startup.py:_run_dismissed_index_startup_sync()` runs the sync (including
  terminalization) off the first-paint path via `asyncio.to_thread`. That is the natural **once-per-session**
  terminalization owner. It does not protect the normal agents-refresh apply path.
- The repo's established background-scheduling pattern is the coalescing loading/pending/scheduled flag set used by
  `_loading_refresh.py:_schedule_agents_async_refresh` / `_run_agents_async_refresh`, including deferral via
  `NavigationGate` (`is_navigating()` / `time_until_idle()`). We mirror this rather than inventing a new path (per the
  TUI perf memory rule "don't add new refresh code paths").

## Goals / non-goals

**Goal:** No synchronous artifact-index projection sync or terminalization on the Textual event loop during the
agents-refresh apply. Navigation is responsive immediately after startup. Maintenance work is preserved (still runs,
just off-thread, coalesced, and throttled).

**Non-goals:** Changing the Rust terminalizer cost model (Layer 2); fixing stopped-without-`done.json` semantics or
adding index/retention compaction (Layer 3); changing the already-off-thread dismiss/kill/revive/mark callers or the
CLI/axe callers (out of scope — they are not the freeze and changing them risks regressions). These remain
default-terminalizing.

## Design

### 1. Make terminalization separable in the lifecycle module

File: `src/sase/core/agent_artifact_index_lifecycle.py`

Add a keyword-only `run_active_tier_maintenance: bool = True` parameter to both
`sync_dismissed_agent_artifact_index_report()` and the bool wrapper `sync_dismissed_agent_artifact_index()`. In
`_report`, gate the call:

```python
report = _sync_projection(index, dismissed, added=added, force=force)
if not run_active_tier_maintenance:
    return report
return _run_active_tier_maintenance(index, report)
```

Rationale for **default `True`**: this preserves the behavior of all ~15 existing callers (CLI, axe,
dismiss/kill/mark/revive, and the startup once-per-session sync) with zero blast radius. The fix is achieved by having
the **apply path** explicitly pass `run_active_tier_maintenance=False` (projection-only) through the new scheduler, and
by throttling when the scheduler is allowed to terminalize. Terminalization is no longer _unconditional_ — it is now
controllable, which is what Layer 1 requires. The corruption-heal path (`_heal_corrupt_index_and_resync`) is left
unchanged (it is rare and always already runs off the event loop).

### 2. New coalescing, nav-gate-aware, throttled maintenance scheduler

New file: `src/sase/ace/tui/actions/agents/_index_maintenance.py` defining
`AgentIndexMaintenanceMixin(AgentLoadingStateMixin)` with:

- `_schedule_artifact_index_maintenance(*, dismissed, added, force, source)` — stores the latest request
  (last-request-wins: full dismissed snapshot, added hint, OR-ed force flag), then:
  - if a maintenance run is already in flight, sets a pending flag and returns;
  - otherwise marks running and `call_later(self._run_artifact_index_maintenance)`.
- `_run_artifact_index_maintenance()` (async) —
  - defers while `self._nav_gate.is_navigating()` by re-arming via `set_timer` at the gate boundary (mirrors
    `_run_agents_async_refresh`), so a held j/k burst always wins;
  - consumes the latest pending request;
  - decides terminalization via `_should_run_active_tier_terminalize()`;
  - runs
    `await asyncio.to_thread(sync_dismissed_agent_artifact_index_report, dismissed_snapshot, added=..., force=..., run_active_tier_maintenance=run_terminalize)`;
  - on completion, stamps the throttle timestamp if it terminalized, clears the running flag, and re-schedules itself
    once more if a request arrived while it ran (last-request-wins).
- `_should_run_active_tier_terminalize()` — throttle:
  ```python
  last = self._artifact_index_maintenance_last_mono
  if last <= 0.0:
      return False          # startup owns the first per-session terminalize
  return (time.monotonic() - last) >= _ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S
  ```
  With a module constant `_ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S = 3600.0`. This realizes "at most once per session or
  once per configured interval": the startup sync does the session's first terminalization (already off-thread), and the
  apply-triggered maintenance only terminalizes again after the interval — otherwise it is projection-only.

Wire the mixin into `AgentLoadingMixin`'s bases in `src/sase/ace/tui/actions/agents/_loading.py`.

Note on mechanism choice: the research suggested `_submit_tracked_task` / `_submit_background_task`. We instead mirror
the existing `_schedule_agents_async_refresh` coalescing-worker pattern because it gives true last-request-wins (the
tracked-task path drops duplicates rather than coalescing to the latest snapshot) and keeps routine background
maintenance out of the user-visible task indicator. The core requirement — work runs off the event loop — is satisfied
identically. This is consistent with the TUI perf memory ("route refreshes through the existing fast path; coalesce with
loading/pending flags; don't add new refresh code paths").

### 3. Apply path: schedule instead of calling synchronously

File: `src/sase/ace/tui/actions/agents/_loading_apply.py`

In `_apply_loaded_agents_prepared_inner`, the `persist_dismissed_changes` block keeps updating in-memory dismissed state
and the single `save_dismissed_agents()` write (the small ~2.5 MB file, already on the UI thread today and not the
freeze), then replaces the two synchronous `sync_dismissed_agent_artifact_index(...)` calls with one scheduler call:

```python
if save_dismissed_agents(self._dismissed_agents):
    self._schedule_artifact_index_maintenance(
        dismissed=set(self._dismissed_agents),
        added=added_identities or None,
        force=dismissed_changes_include_removals,
        source="apply",
    )
else:
    record_agents_refresh_trace(... fallback ...)
```

Remove the now-unused `sync_dismissed_agent_artifact_index` import from this file. (`force`/removal correctness is
preserved: `save_dismissed_agents` rewrites the dismissed file, so the projection-sync signature check detects the drift
and does a full rewrite on the next maintenance run even when `added` is dropped by coalescing.)

### 4. Startup throttle coordination

File: `src/sase/ace/tui/actions/startup.py`

After `_run_dismissed_index_startup_sync` completes its `to_thread` sync (which still terminalizes by default), stamp
`self._artifact_index_maintenance_last_mono = time.monotonic()`. This makes the startup sync the canonical
once-per-session terminalization and prevents the first apply-triggered maintenance from redundantly terminalizing.
(`startup.py` already imports `time`.) `_run_agent_index_startup_prepare` and the existing ordering are unchanged.

### 5. State flags

- `src/sase/ace/tui/actions/agents/_loading_state.py`: declare the new attributes —
  `_artifact_index_maintenance_running: bool`, `_artifact_index_maintenance_pending: bool`,
  `_artifact_index_maintenance_pending_request` (typed snapshot tuple, or None),
  `_artifact_index_maintenance_last_mono: float`.
- `src/sase/ace/tui/actions/_state_init.py`: initialize them (`False`, `False`, `None`, `0.0`) alongside the existing
  `_agents_refresh_*` initializers.

## Tests

- `tests/_agent_artifact_marker_audit_helpers.py`: in `_dismissed_save_contexts`, recognize
  `_schedule_artifact_index_maintenance` as valid dismissed-projection coverage (scoped to this audit only — do not
  broaden the shared `_LIFECYCLE_CALL_NAMES` used by the marker-mutation/path-passing audits).
- `tests/test_agent_artifact_dismissed_save_audit.py`: update the expected lifecycle-call entry for
  `_loading_apply.py:_apply_loaded_agents_prepared_inner` to the scheduler call.
- `tests/agent_artifact_index_lifecycle/test_projection_sync.py`: add a case asserting
  `run_active_tier_maintenance=False` performs the projection sync but does **not** invoke the terminalizer (patched
  terminalizer must not be called), and that the existing default-`True` behavior still terminalizes.
- New `tests/ace/tui/test_artifact_index_maintenance_scheduler.py`: drive the new mixin against a minimal harness —
  coalescing (one in-flight, pending re-run), last-request-wins snapshot, nav-gate deferral (re-arm timer when
  navigating), throttle (`last==0` → no terminalize; recent stamp → no terminalize; aged stamp → terminalize), and that
  the heavy call goes through `asyncio.to_thread`.
- New `tests/ace/tui/test_apply_path_index_maintenance_offthread.py`: regression guard — when
  `persist_dismissed_changes=True`, `_apply_loaded_agents_prepared_inner` calls `_schedule_artifact_index_maintenance`
  and does **not** synchronously invoke `sync_dismissed_agent_artifact_index` / the terminalizer (this is the research's
  requested regression test that fails if the apply path ever re-introduces synchronous terminalization).
- Confirm `tests/ace/tui/test_dismissed_index_startup_sync.py` still passes (startup sync still called with one
  positional arg; the added throttle stamp is a plain attribute assignment the harness tolerates).

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + pytest).
2. Manual TUI check per the request: launch `sase ace --tmux` (opens the TUI in a new tmux pane), capture the pane
   contents, and confirm the agent rows from the provided snapshot still render and behave normally — the three tag
   groups (`(untagged)`, `#research`, `#sase-55`) and their agent rows are present, the info/detail panels populate, and
   j/k navigation on the agents tab is responsive right after startup (no multi-second freeze).

## Risks & mitigations

- **Behavior drift for non-apply callers:** avoided by defaulting `run_active_tier_maintenance=True`; only the apply
  path opts out.
- **Dismissed agents briefly not reflected in the SQLite index** between the in-memory apply and the background sync:
  acceptable and already the accepted model for the startup sync; the next Tier-1 load after the background task
  completes picks up the projection. The UI already reflects in-memory state.
- **Long-lived sessions accumulating stale active rows** because terminalization is throttled: intended for Layer 1
  ("once per session/interval"); Layer 3 addresses the underlying data accumulation.
- **Double terminalization race at startup** (first apply maintenance vs. startup sync): prevented by the
  `last <= 0.0 -> False` throttle rule, so the apply path never terminalizes before the startup sync stamps the
  timestamp.
