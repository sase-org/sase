---
create_time: 2026-05-21 08:51:51
status: done
prompt: sdd/prompts/202605/agents_refresh_on_notifications.md
---
# Plan: Refresh Agents Tab On New Auto-Refresh Notifications

## Goal

When ACE auto-refresh polls the notification store and discovers newly unread, active notifications, refresh the Agents
tab promptly so completion/question/approval status changes appear without waiting for a separate agents-dirty event.
The refresh must remain non-blocking on the UI thread and must preserve the recent `sase-3s` loader optimization: normal
loads should keep using the bounded Tier 1/index-backed path, with the existing async scheduler and coalescing gates.

## Current Shape

- `StartupMixin.on_mount()` configures `_on_auto_refresh` on the configured interval, defaulting to 10 seconds.
- `_on_auto_refresh()` currently treats notifications and agents as separate surfaces:
  - notification polling calls `_poll_agent_completions()` when the watcher is inactive, the notification dirty flag is
    set, or the sanity floor is due;
  - agent loading runs only when `agents_due` is true, gated by tab visibility, navigation/input state, in-flight load
    state, and the `AGENTS_LOAD_MIN_INTERVAL_SECONDS` floor.
- `_poll_agent_completions()` already reads the notification snapshot off the main thread, computes `new_notifications`
  from `_last_unread_ids`, updates the indicator, applies notification status overrides, reconciles visible unread row
  state, and rings/toasts for new active notifications.
- `_schedule_agents_async_refresh()` is the right refresh primitive for this feature: it runs asynchronously, defers
  through the navigation gate, and collapses stampedes into one in-flight load plus one pending follow-up.
- The `sase-3s` epic changed the loader so ordinary refreshes are acceptable more often, but still only if they stay on
  the Tier 1/index-backed path and avoid synchronous full-history scans.

## Design

1. Make notification polling return whether the poll saw any newly active unread notifications.
   - Return `True` only when `new_notifications` is non-empty.
   - Do not count muted notifications as "new" for this feature, matching the existing no-toast/no-bell treatment.
   - Do not count snooze expirations without new unread rows; they should still ring as they do today, but should not
     force an agents reload unless they produce an active unread notification.

2. In `_on_auto_refresh()`, after `_poll_agent_completions()` completes, request an agents refresh when:
   - the poll reported newly active unread notifications;
   - `current_tab == "agents"`;
   - prompt/hint/jump/accept modes are not active;
   - the app is not already in an agents load.

3. Route that request through `_schedule_agents_async_refresh()` instead of directly calling `_load_agents_async()`.
   - This keeps the disk work off-thread through the existing async loader.
   - It preserves last-request-wins coalescing if notification polling, inotify, and user actions all request refreshes
     near the same time.
   - It avoids bypassing the navigation-gate protection in `_run_agents_async_refresh()`.

4. Avoid duplicate same-tick loads.
   - If the auto-refresh tick is already going to load agents via `agents_due`, do not separately schedule another
     refresh from the notification poll.
   - If the notification poll requests a scheduled refresh, avoid also running the direct `agents_due` path in the same
     tick unless the direct path was already due before the notification result.

5. Preserve dirty-flag semantics.
   - Keep `_dirty_notifications = False` after a successful notification poll.
   - Do not require setting `_dirty_agents = True` merely because new notifications arrived; scheduling the async
     refresh is more direct and avoids leaving stale dirty state after the scheduled load completes.
   - Off the Agents tab, do not force an agents refresh from notifications; the existing tab-gated/sanity behavior
     remains the backstop.

## Implementation Steps

1. Update `src/sase/ace/tui/actions/agents/_notification_polling.py`.
   - Change `_poll_agent_completions()` to return `bool`.
   - Return `True` when `new_notifications` is non-empty; otherwise `False`.
   - Keep all current side effects unchanged.

2. Update `src/sase/ace/tui/actions/_event_refresh.py`.
   - Capture the boolean returned by `_poll_agent_completions()`.
   - After transient input-mode checks and before the direct agents load block, call `_schedule_agents_async_refresh()`
     when a new notification arrived on the Agents tab and `agents_due` is false.
   - Keep the existing direct `agents_due` load path intact for watcher/sanity/manual dirty cases.

3. Update tests.
   - Extend `tests/test_notification_toast_polling.py` to assert `_poll_agent_completions()` returns `True` for a new
     active notification and `False` for already-seen, silent, muted-only, and snooze-expiration-only cases.
   - Extend `tests/ace/tui/test_event_handlers_dirty_flags.py` with a fake `_poll_agent_completions()` return value and
     assertions that a new notification schedules an agents refresh on the Agents tab without running a synchronous
     direct agents load.
   - Add coverage that no extra agents refresh is scheduled off the Agents tab or when the tick already performed the
     normal direct agents load.

4. Verify.
   - Run the focused tests:
     - `pytest tests/test_notification_toast_polling.py tests/ace/tui/test_event_handlers_dirty_flags.py`
   - Because this repo requires it after code changes, run `just install` if the workspace environment is stale, then
     `just check`.

## Risks And Mitigations

- Risk: scheduling an agents refresh while a direct auto-refresh load is also due could produce duplicate work.
  Mitigation: gate the notification-triggered schedule on `not agents_due` after the existing due/debounce computation.
- Risk: a fake/test app may still type `_poll_agent_completions()` as returning `None`. Mitigation: treat the return as
  truthy/falsey at call sites and update relevant fake methods where assertions depend on it.
- Risk: new notification polling could trigger a full-history scan. Mitigation: use `_schedule_agents_async_refresh()`
  with default `full_history=False`; the loader will use the Tier 1 optimized path unless an active agent search query
  already intentionally forces full history.
