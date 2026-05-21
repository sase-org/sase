---
create_time: 2026-05-21 08:57:57
status: wip
prompt: sdd/prompts/202605/prompt_input_lag_tier2_reconcile.md
---
# Plan: Fix Prompt Input Lag From Startup Tier 2 Agent Reconcile

## Problem

Typing in `PromptInputBar` can randomly freeze for roughly 3 seconds. The current evidence points to agent loading, but
not the normal Tier 1 index-backed load from the `sase-3s` epic. The likely culprit is the startup Tier 2 full-history
reconcile:

- Tier 1 agent loading uses the artifact index when available and marks its `AgentLoadState` as incomplete.
- `_apply_loaded_agents_prepared()` sets `_agents_history_reconcile_pending` and arms a one-shot
  `STARTUP_TIER2_RECONCILE_DELAY_S = 2.0` timer.
- `_fire_startup_tier2_reconcile()` currently schedules a `full_history=True` refresh without checking whether the user
  is typing in the prompt widget or has been recently active.
- Prompt-input protections already exist for watcher and auto-refresh paths, but this startup reconcile bypasses them.

This explains why the lag feels random: it occurs after the first incomplete Tier 1 apply, roughly when the one-shot
timer fires, if the user happens to be typing then. The full-history scan is the known expensive path from the existing
perf docs/tests, and even when disk IO is offloaded, the final load/apply and Python-side conversion can still contend
with the UI loop.

## Design

Make startup Tier 2 reconcile obey the same interaction contract as other background refresh sources:

- Never start the startup full-history reconcile while a prompt-like input surface is mounted.
- Never start it immediately after recent user activity; let the existing idle threshold decide when to run.
- Preserve manual refresh behavior: pressing refresh while the reconcile is pending still explicitly promotes to
  `full_history=True`.
- Preserve eventual convergence: if the prompt closes or the user becomes idle, `_maybe_trigger_idle_tier2_reconcile()`
  should still schedule the Tier 2 pass.
- Keep the change local to TUI refresh scheduling. Do not change the Rust scan/index contract in this fix.

## Implementation Steps

1. Update `_fire_startup_tier2_reconcile()` in `src/sase/ace/tui/actions/agents/_loading_refresh.py` so it only fires
   when the user is genuinely idle.
   - If `_prompt_input_active()` is true, return without clearing `_agents_history_reconcile_pending`.
   - If the idle threshold has not elapsed from the later of `_last_activity_time` and
     `_agents_history_reconcile_armed_mono`, return without clearing the pending flag.
   - Delegate to `_maybe_trigger_idle_tier2_reconcile()` where practical so the two paths cannot drift.

2. Update tests in `tests/ace/tui/test_lazy_tier2_reconcile.py`.
   - Add prompt-active coverage for the startup trigger.
   - Add recently-active coverage for the startup trigger.
   - Keep existing loading/in-flight behavior.
   - Adjust the old “startup trigger fires immediately” expectation to the new idle-gated behavior.

3. Run focused tests:
   - `pytest tests/ace/tui/test_lazy_tier2_reconcile.py`
   - If needed, `pytest tests/ace/tui/test_event_handlers_dirty_flags.py`

4. Run repo validation after code changes, following repo instructions:
   - `just install`
   - `just check`

## Acceptance

- A startup Tier 2 reconcile pending flag no longer starts a full-history load while the prompt input widget is active.
- Recent typing pushes the reconcile out until the established `TIER2_RECONCILE_IDLE_THRESHOLD_S` idle window.
- Manual refresh remains the explicit way to force the pending full-history reconcile.
- Focused tests cover the regression.
