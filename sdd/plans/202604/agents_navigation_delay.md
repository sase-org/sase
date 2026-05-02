---
create_time: 2026-04-25 09:56:13
status: done
prompt: sdd/prompts/202604/agents_navigation_delay.md
---
# Plan: Fix Agents Tab Navigation Delay After Killing Agents

## Problem

Users still sometimes see a noticeable delay when navigating the Agents tab with `j`/`k` after killing agents in the
TUI. The kill path already removes killed agents from the in-memory list immediately and defers filesystem/project-file
side effects to a background thread, so the remaining delay is likely caused by follow-up UI work rather than the signal
or persistence itself.

## Current Findings

- `j`/`k` on the Agents tab updates `current_idx`, then uses `_refresh_agents_display_debounced()` to move the list
  highlight immediately and defer expensive detail rendering.
- Single-agent and bulk kill paths optimistically remove agents from `_agents`/`_agents_with_children`, rebuild panel
  indices, and call `_refresh_agents_display(list_changed=True, defer_detail=True)`.
- Kill persistence runs in `asyncio.to_thread(...)`, which keeps project-file and artifact cleanup off the event loop.
- However, both `_run_kill_persistence_async()` and `_run_bulk_kill_persistence_async()` unconditionally call
  `_schedule_agents_async_refresh()` in `finally`.
- That scheduled refresh performs a full disk load, then applies the result on the main UI thread with a full list
  rebuild. If it completes while the user is navigating, key events queue behind the apply/list-render phase and the
  deferred detail timer.
- Because the optimistic in-memory kill has already hidden the killed rows, an immediate post-success reload is
  redundant for the interactive path. It is useful only as recovery if persistence fails or if the in-memory state
  cannot be trusted.

## Approach

1. Make kill persistence refresh-on-failure instead of refresh-always.
   - Track whether the background persistence stage raised.
   - On success, do not schedule an immediate full agent reload.
   - On failure, keep the current recovery behavior by scheduling `_schedule_agents_async_refresh()` after notifying the
     user.

2. Preserve correctness of the optimistic kill state.
   - Keep immediate in-memory removal and dismissal unchanged.
   - Keep saving the dismissed-agent set in the single kill persistence path.
   - Keep bulk persistence saving the dismissed snapshot.
   - Rely on normal auto-refresh/manual refresh for later reconciliation after successful cleanup.

3. Add focused regression tests.
   - Verify single kill persistence does not schedule an agent reload on success.
   - Verify single kill persistence still schedules a reload on failure.
   - Verify bulk kill persistence follows the same success/failure behavior.
   - Existing immediate-removal tests should continue to pass.

4. Run targeted tests first, then the repo-required check.
   - Targeted: agent kill tests and agents refresh/coalescing tests.
   - Required after code changes: `just check`.

## Expected Result

Killing an agent still updates the Agents tab immediately, but no redundant full reload competes with follow-up `j`/`k`
navigation after successful cleanup. If cleanup fails, the TUI still schedules a refresh to recover and reconcile with
disk state.
