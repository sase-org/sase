---
create_time: 2026-04-24 15:19:44
status: done
---
# Plan: Actually Make the `sase ace` Startup Stopwatch Tick — batch_update Fix

## Problem

After the fix in commit `369ed0c0` (async `on_mount` + `asyncio.to_thread` around disk reads), the stopwatch **still**
freezes at **`0.2s`** for the whole ~3.5s startup. The previous plan's diagnosis — "event loop blocked by disk I/O" —
was only half right. Freeing the event loop didn't free the render pipeline.

## Real Root Cause (verified in Textual 8.0.0 source)

Textual wraps the entire mount dispatch in `batch_update()`:

- `textual/app.py:3356` — `with self.batch_update():` encloses `await self._dispatch_message(events.Mount())`
  (app.py:3365). Our `AceApp.on_mount` async body runs **inside that batch**, across every `await`.
- `textual/app.py:3748-3760` — `_display(...)` short-circuits with `if self._batch_count: return`.
- So while `on_mount` is in flight, the stopwatch timer's `Static.update(...)` writes to the widget's renderable but
  nothing reaches the terminal. The 2 ticks the user sees (`0.0s`, `0.1s`, ending at `0.2s`) are whatever the renderable
  happened to hold at the moment the batch finally exits.

This means `asyncio.to_thread` in `on_mount` is architecturally pointless for solving this bug. The heavy work has to
happen **outside** the mount batch.

### What I confirmed in the Textual source

- `KeybindingFooter.on_mount` fires **before** `AceApp.on_mount`: `widget.py:150` (`AwaitMount.__await__` waits on each
  child's `_mounted_event`) and `app.py:3481` (children Compose+Mount inside `App._on_compose`, which runs before the
  `Mount` dispatch at app.py:3365). So the 0.1s interval IS registered in time. The timer fires; the paints are
  swallowed.
- `call_after_refresh(cb)` posts `InvokeLater(cb)` (message_pump.py:457). That message is handled by
  `MessagePump._on_invoke_later` → `Screen._invoke_later` → the callback is appended to `Screen._callbacks` and later
  drained by `_invoke_and_clear_callbacks`, which does `await invoke(callback)` (screen.py:1257-1265). `invoke` accepts
  both sync and async callables, so scheduling an `async def` via `call_after_refresh` is supported.
- Crucially, `_invoke_and_clear_callbacks` is scheduled via `self.call_next(...)` from `Screen._on_update` (screen.py:
  1254-1255) — i.e. after the first paint, when the original `batch_update` from Mount has already exited. This is
  exactly the window we need.

## Design Goal

The gold `⏱ starting N.Ns` badge must tick visibly at ~10Hz throughout the startup gap — the digit rollover must be
observable by eye, not jump from 0.2s straight to the real status.

## Strategy

**Two-phase mount.**

1. **Phase 1 — `AceApp.on_mount` (minimal, runs inside the batch):**
   - Wire the keymap registry into `KeybindingFooter` and `TabBar` (these two widgets need it before their next render,
     and they're already mounted).
   - Set `self._mounting = True`.
   - Schedule phase 2: `self.call_after_refresh(self._finish_startup)`.
   - Return. Textual exits `batch_update`, pushes the first paint to the terminal (stopwatch visible at ~0.0s), then
     processes the InvokeLater that fires `_finish_startup`.

2. **Phase 2 — `async def _finish_startup` (runs outside the batch):**
   - Exact same body as the current `on_mount` from line 530 onward, wrapped in `try/finally: self._mounting = False`.
   - Every `await asyncio.to_thread(...)` now yields the loop _outside_ the batch, so the stopwatch timer's pending
     `Static.update(...)` calls reach `_display` and actually paint.

3. **Apply-phase breathers.** The synchronous apply phases between awaits can still be slow
   (`_apply_changespecs → _refresh_display` iterates every CL, builds list + detail + ancestors + footer). A 500ms sync
   stretch means a 500ms visible stutter. Mitigation: insert `await asyncio.sleep(0)` _before_ each apply phase so the
   event loop gets an explicit turn to drain the timer-posted Update messages. `sleep(0)` is cheap (~μs) and doesn't
   change behavior — it just lets the loop pump once.

### Why not other options?

- **Put everything in `call_after_refresh` but keep the body sync:** works as well, but we lose the yields that let the
  stopwatch tick through the ~1s disk read. The async variant is strictly better.
- **Use `run_worker(thread=True)`:** same widget-access-from-worker problem the prior audit flagged.
- **Give up and show a static label:** defeats the feature.

## Concrete Change Set

### 1. `src/sase/ace/tui/app.py` — split `on_mount` into two phases

**New `on_mount` (sync — just kick off phase 2):**

```python
def on_mount(self) -> None:
    """Wire up the bits that MUST land inside Textual's mount batch,
    then defer the rest to _finish_startup so the stopwatch can tick
    live outside the batch's render-suppression window.
    """
    self._mounting = True
    footer = self.query_one("#keybinding-footer", KeybindingFooter)
    footer.set_keymap_registry(self._keymap_registry)
    tab_bar = self.query_one("#tab-bar", TabBar)
    tab_bar.set_keymap_registry(self._keymap_registry)
    self.call_after_refresh(self._finish_startup)
```

**New `async def _finish_startup`:** contains everything that is currently in `on_mount` from the "Initialize agent
tracking" block onward (lines 529-598 of current `app.py`). Wrap the body in `try/finally: self._mounting = False`.

Between each `await asyncio.to_thread(...)` and its subsequent sync apply call, insert a small `await asyncio.sleep(0)`
so the timer has a turn to drain its update queue. Specifically:

```python
unread_ids = await asyncio.to_thread(self._read_unread_notification_ids)
await asyncio.sleep(0)
self._initialize_agent_tracking(unread_ids)

all_cs = await asyncio.to_thread(self._read_changespecs_from_disk)
await asyncio.sleep(0)
self._apply_changespecs(all_cs)

# ... same ordering as before: fallback, save_current_query, restore_last_selection,
#     _apply_startup_loading_state, call_after_refresh(_run_agents_async_refresh /
#     _run_axe_startup_init), activity/idle setup, refresh timer setup.
```

### 2. `self._mounting` lifetime

Set to `True` in `on_mount`; cleared at the end of `_finish_startup` inside `try/finally`. Observable window grows from
~3.5s of the old sync mount to ~3.5s of `_finish_startup` — effectively the same window. Readers of `_mounting` behave
the same.

### 3. Preserve exception safety

`_finish_startup` must not swallow exceptions silently (they'd vanish into the Screen callback path). Let them
propagate; Textual will log them. The `try/finally` only handles the `_mounting` reset.

### 4. No changes to split helpers from `369ed0c0`

`_read_unread_notification_ids`, `_read_last_selection_name`, `_read_changespecs_from_disk`, `_apply_changespecs`,
`_try_startup_fallback_async` all stay. They were the right primitives — they just needed to run outside the batch.

### 5. No changes to the stopwatch widget

`keybinding_footer.py` is untouched.

## Test Plan

**Primary — manual smoke tests (this is the real fix verification):**

1. Run `sase ace` with axe stopped. Watch the bottom-right badge. The tenths digit must cycle visibly:
   `0.0 → 0.1 → 0.2 → ... → 3.4` with no multi-second freezes. The color stays gold until 10s.
2. Run `sase ace` with axe already running. Brief (<1s) stopwatch, smooth transition to green `RUNNING`.
3. Simulate a slow load: temporarily add `time.sleep(12)` inside `_read_changespecs_from_disk`. The stopwatch ticks past
   10s (color shifts to pink/red), continues past 12s, and lands on the real status. At ≥30s the safety timeout fires
   even if the load hasn't returned.
4. Confirm no regression in the CLs tab: initial results appear at roughly the same moment as today; saved-query
   fallback still works; last-selection still lands on the right row.
5. Confirm no regression in the Agents tab: loading spinners appear and clear; async refresh schedules.

**Unit / integration tests:**

- `AceApp._finish_startup` is a coroutine (`inspect.iscoroutinefunction`).
- `AceApp.on_mount` is **sync** and contains a `call_after_refresh` call to `_finish_startup` — matches the new
  contract.
- Keep the existing `test_on_mount_is_async_coroutine` test but rename/replace it to target `_finish_startup` (on_mount
  is going back to sync by design).
- Pilot-based integration test: mount `AceApp` with a mocked `_read_changespecs_from_disk` that sleeps 0.5s, drive the
  pilot's event loop, assert `KeybindingFooter._startup_elapsed` advances past 0.3s (at least 3 ticks) and that the
  `#keybinding-status` Static's `renderable` has been updated more than once during that window (confirms the ticks
  aren't just queued).

## Risk Analysis

- **`call_after_refresh` not firing**: if Textual's Screen never issues `_on_update`, callbacks don't drain. But
  `_on_update` fires on every compositor refresh, and one happens immediately after mount exits the batch. Verified.
- **Exceptions in `_finish_startup`**: propagate via `invoke`; Textual logs them. Visible in `textual console` and
  normal stderr. No change in user-visible behavior on error vs. today.
- **Ordering preservation**: the rewrite keeps the current strict order (notifications → changespecs → fallback →
  save*current_query → restore_last_selection → loading state → agents/axe deferral → activity/idle → timers). The only
  architectural change is that the _whole* sequence moves from "inside the mount batch" to "after the first paint,"
  which the user experiences as a slight delay in data appearing (negligible — still gated on the same
  `await asyncio.to_thread(...)` disk reads) in exchange for a live stopwatch.
- **`_mounting` seen as True by a keypress before phase 2 starts**: possible new window of ~one paint frame where the
  user could press a key before `_finish_startup` begins. Existing guards already tolerate empty `self.changespecs`
  during mount; this window is strictly shorter than the mount gap today.
- **`asyncio.sleep(0)` breathers doing nothing useful**: if the apply phases turn out to be fast (<50ms), the breathers
  are cheap no-ops. If they're slow, they're essential. Zero-risk either way.
- **30s safety timeout**: unchanged — still self-terminates.

## Rollout

Single commit. Title: `fix: run sase ace startup I/O after first paint so the stopwatch ticks`. No CLI, no config, no
migration.

## Deliberately Out of Scope

- Parallelizing the four disk reads (still sequential — separate optimization).
- Moving `AceApp.__init__` disk I/O off the main thread (pre-event-loop — doesn't affect stopwatch).
- Any UX change to the stopwatch itself (color, label, cadence).
- Further refactoring of `_refresh_display` for speed — if apply phases are faster than ~100ms, the breathers cover
  them. If they're not, that's a separate UX problem (list/detail rendering lag on navigation too).
