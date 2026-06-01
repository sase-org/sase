---
create_time: 2026-06-01 10:59:25
status: done
prompt: sdd/prompts/202606/agent_refresh_coalescing.md
---
# Agent Refresh Coalescing Plan

## Context

The profiling run for single-agent and fanout launches showed that TUI launch latency is dominated by repeated
`agents.load_from_disk` passes after the launch, not by fanout planning or row patching. The existing code already has a
debounced `request_agents_refresh("launch")` path for fanout launches, but direct calls to
`_schedule_agents_async_refresh()` still exist in notification/completion and related external-update paths. Those calls
can bypass the debounce/min-interval behavior and make trace analysis harder because `agents.load_from_disk` spans do
not identify which trigger caused them.

The audited TUI latency baseline also makes clear that j/k responsiveness is the critical product behavior to preserve:
refresh work should defer while navigation is active, avoid UI-thread disk I/O, and keep post-launch paint latency low.

## Goals

- Coalesce external agent refresh triggers, especially notification/completion-driven triggers, through the same
  debounce path used by launch fanout.
- Preserve immediate user-facing feedback for deliberate actions such as manual refresh, filter changes, kill/dismiss,
  and status override updates where the UI already updates in memory before a disk reconcile.
- Add source metadata to refresh scheduling and `agents.load_from_disk` trace spans so future profiling can distinguish
  `launch`, `notification`, `auto_refresh`, `manual`, `tab_switch`, and other refresh causes without inference.
- Extend focused tests around refresh coalescing, notification-triggered refreshes, and trace fields.

## Design

1. Make agent refresh scheduling source-aware.
   - Add an optional `source: str = "unknown"` keyword to `_schedule_agents_async_refresh()`.
   - Track scheduled and pending source values in `AgentLoadingStateMixin` / `_state_init.py`.
   - When a load actually runs, expose the active source to the loader, and include it on trace spans as something like
     `source=<value>`.
   - When multiple requests coalesce, keep a stable, useful source value. Prefer preserving the already-scheduled source
     for the in-flight pass and recording a pending source for the follow-up pass.

2. Keep `request_agents_refresh()` as the public coalescing entry point.
   - Stop discarding its `source` argument.
   - Have `_fire_debounced_agents_refresh()` call `_schedule_agents_async_refresh(source=<debounced_source>)`.
   - Preserve current defaults: 150 ms debounce, latest-only burst collapse, and the existing navigation gate in
     `_run_agents_async_refresh()`.

3. Route notification/completion refresh triggers through the debounce path.
   - In `_on_auto_refresh()`, replace the direct `new_agent_notification` scheduled refresh with
     `request_agents_refresh("notification", latest_only=True)` when the Agents tab is visible and no full agent load is
     already due.
   - For notification modal/response completion callbacks that currently call `_schedule_agents_async_refresh()` after
     background side effects, use `request_agents_refresh("notification", latest_only=True)` where the visible UI has
     already been updated or where a short debounce is acceptable.
   - Keep immediate direct scheduling for explicit manual refreshes and for error recovery paths that tell the user a
     refresh is recommended.

4. Label remaining direct schedules deliberately.
   - Change launch single/workflow fallback direct schedules to either `request_agents_refresh("launch")` or
     `_schedule_agents_async_refresh(source="launch")`, matching the existing fanout behavior.
   - Label tab-switch, manual refresh, full-history refresh, filter, kill/dismiss, and action-specific refreshes with
     clear source strings when direct scheduling remains appropriate.
   - Avoid changing unrelated behavior in this pass.

5. Add focused regression coverage.
   - Extend the existing coalescing tests to assert that `request_agents_refresh("notification")` arms only one timer
     and forwards the source into the scheduled refresh.
   - Add/update event-refresh tests so `new_agent_notification` calls `request_agents_refresh("notification")` instead
     of scheduling a direct load.
   - Update the `agents.load_from_disk` trace test to assert the new source field, while keeping existing load-state
     fields intact.
   - Update fake app helpers with the new scheduler attributes/signatures.

## Verification

- Run the focused TUI refresh tests first:
  - `pytest tests/ace/tui/test_agents_refresh_coalescing.py`
  - `pytest tests/ace/tui/test_event_handlers_dirty_flags.py tests/ace/tui/test_event_handlers_nav_gate.py`
  - `pytest tests/ace/tui/actions/test_agent_loader_phase5_wiring.py`
  - `pytest tests/ace/tui/test_launch_fan_out_unified.py`
- Because this repo requires it after code changes, run `just install` if needed and then `just check`.
- If time permits after tests, do a short manual trace sanity check with `SASE_TUI_TRACE=1` to confirm
  `agents.load_from_disk` rows include useful `source` values.

## Risks

- Some direct schedules are intentionally immediate for visible user actions. Over-debouncing those could make status
  transitions feel stale, so this pass should route only notification/completion/external burst triggers through
  debounce and label the rest.
- Adding source propagation through coalesced pending refreshes must not break callback semantics. Pending callbacks
  should still fire after the refresh pass that actually executes.
- Tests with minimal fake apps will need careful attribute updates so they keep exercising the same behavior instead of
  masking missing state initialization.
