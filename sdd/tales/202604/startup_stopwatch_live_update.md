---
create_time: 2026-04-24 14:56:18
status: done
prompt: sdd/prompts/202604/startup_stopwatch_live_update.md
---
# Plan: Make the `sase ace` Startup Stopwatch Actually Tick

## Problem

The gold `⏱ starting N.Ns` badge added in commit `e7ec227e` is supposed to tick every 0.1s while the TUI is starting up.
In practice it freezes at **`0.2s`** for the whole ~3.5s startup, then vanishes when the real status takes over. From
the user's perspective it looks broken — it is visibly _not_ the "live stopwatch" that was promised.

## Diagnosis (already confirmed — not re-derived in this plan)

The Textual event loop is blocked on the main thread during startup, so `set_interval(0.1, ...)` callbacks cannot fire.
Textual mounts children before parents, so `KeybindingFooter.on_mount` fires first, registers the 0.1s interval, and
gets a tick or two before the parent `AceApp.on_mount` takes over and blocks the loop with synchronous disk I/O for ~3
seconds:

- `_initialize_agent_tracking()` — reads notifications from disk (`app.py:522`)
- `_load_changespecs()` — full filesystem scan for ChangeSpecs (`app.py:525`)
- `_try_startup_fallback()` — iterates saved queries with disk reads (`app.py:530`)
- `_restore_last_selection()` — disk read (`app.py:533`)
- `_save_current_query()` — disk write (`app.py:534`)
- `_apply_startup_loading_state()` — widget queries (`app.py:539`)

Only after all six does `AceApp.on_mount` reach `call_after_refresh(...)` on lines 543 and 546, which is the first point
the loop becomes free. By then the async axe loader fires almost immediately, flips `_axe_first_load_done = True`, and
calls `end_startup_stopwatch()` — which is exactly what the user sees.

## Design Goal

The stopwatch must tick visibly at ~10Hz throughout the full startup gap. The user must perceive a _live_ elapsed-time
display, not a paused snapshot. The AXE-status end signal, the 30s safety timeout, the gold→orange color escalation, and
the overall UX from the prior plan all stay.

## Audit: Which helpers are thread-safe?

Before choosing a strategy, I audited each blocking helper for calls into Textual widgets (`query_one`, `.update()`,
`.refresh()`, `.loading = ...`) — these are **not** safe to run off the main thread. Pure disk I/O + `self` attribute
mutation **is** safe.

| Helper                         | Widget calls?                                                     | Safe to offload whole? |
| ------------------------------ | ----------------------------------------------------------------- | ---------------------- |
| `_initialize_agent_tracking`   | Yes — `query_one(#notification-indicator)` + `.set_count()`       | No                     |
| `_load_changespecs`            | Yes — calls `_refresh_display()` → many `query_one` + `.update()` | No                     |
| `_try_startup_fallback`        | Yes — indirectly via `_load_changespecs`                          | No                     |
| `_restore_last_selection`      | No — pure `self.current_idx = idx`                                | **Yes**                |
| `_save_current_query`          | No — disk write only                                              | **Yes**                |
| `_apply_startup_loading_state` | Yes — sets `.loading`, `.set_loading()` on 6 widgets              | No                     |

Most of the slow work is _mixed_: a disk read followed immediately by a widget update in the same helper. That's what we
need to untangle.

## Strategy

**Option A (recommended): split the helpers into a pure-I/O "read" phase and a widget-touching "apply" phase, convert
`AceApp.on_mount` to `async def`, and `await asyncio.to_thread(...)` only the read phase.**

This is the cleanest fix and matches the project's existing idiom: `_load_axe_status_async` at
`src/sase/ace/tui/actions/axe_display/_loaders.py:156` already does exactly this split —
`data = await asyncio.to_thread(collect_axe_status_data)` followed by a synchronous `self._apply_axe_status_data(data)`
on the main thread.

Every `await` yields the event loop back to Textual, which gives the 0.1s interval room to fire and repaint. As long as
_any_ await happens every ~100-200ms, the stopwatch ticks smoothly.

### Why not the other options?

- **Offload whole helpers (Option A-variant (b) from the brief)**: audit shows they call `query_one` from the worker
  thread, which is not thread-safe in Textual. Rejected.
- **Option B — `run_worker(thread=True)` around the whole `on_mount` body**: same thread-safety problem (worker body
  calls widget APIs), plus it scrambles ordering with `call_after_refresh`. Rejected.
- **Option C — defer the blockers into `call_after_refresh` callbacks**: viable, but would require introducing a new
  "CLs tab is still loading" placeholder state (there isn't one today), plus audit of every keypress handler for "what
  if `self.changespecs` is still empty." Higher surface area for bugs than A. Fall back to this only if A is blocked.
- **Option D — give up and show a static "starting…" label**: defeats the feature. Rejected.

## Concrete Change Set

### 1. `src/sase/ace/tui/app.py` — convert `on_mount` to async

Change signature from `def on_mount(self) -> None:` to `async def on_mount(self) -> None:`. Textual natively supports
async mount handlers.

Inside the body, replace each blocking call with the split version (see below). The order of effects on `self` state
stays byte-identical; only the threading boundary changes. The existing `self._mounting = True` /
`finally: self._mounting = False` guard still works because `finally` in an `async def` runs after the final `await`.

### 2. Split the four blocking helpers into read-phase / apply-phase

**`_initialize_agent_tracking`** (`src/sase/ace/tui/actions/lifecycle.py:30`)

- Extract a pure function `_read_unread_notification_ids() -> set[str]` (or similar) that only touches disk.
- Keep the existing method as the apply phase: `set_count()` + `self._...` attribute writes, taking the pre-loaded ids
  as an argument.
- In `on_mount`: `ids = await asyncio.to_thread(self._read_unread_notification_ids)` then
  `self._initialize_agent_tracking(ids)` synchronously.

**`_load_changespecs`** (`src/sase/ace/tui/actions/changespec.py:56`)

- This is the big one. Split into:
  - `_read_changespecs_from_disk(query) -> list[ChangeSpec]` — pure disk + filter, no widget calls.
  - `_apply_changespecs(specs) -> None` — assigns `self.changespecs`, fixes indices, calls `_update_cls_tab_count()` and
    `_refresh_display()`.
- In `on_mount`: `specs = await asyncio.to_thread(self._read_changespecs_from_disk, self.query)` then
  `self._apply_changespecs(specs)` synchronously. The existing `_load_changespecs()` becomes a thin wrapper
  `self._apply_changespecs(self._read_changespecs_from_disk(self.query))` so non-startup callers (refresh, query change)
  don't need to change.

**`_try_startup_fallback`** (`src/sase/ace/tui/actions/changespec.py:277`)

- Currently calls `_load_changespecs()` in a loop over saved queries. Convert to async
  `async def _try_startup_fallback_async(self) -> bool` that does the disk read for each query via `asyncio.to_thread`,
  then applies the first hit synchronously.
- Keep the sync version as a thin wrapper for any non-startup callers (there may be none — if so, delete it to avoid
  dead code).

**`_restore_last_selection`** (`src/sase/ace/tui/actions/lifecycle.py:60`)

- Pure disk read + `self.current_idx = ...`. Simplest case: just `await asyncio.to_thread(self._restore_last_selection)`
  with no split needed. Touching `self.current_idx` from a worker thread is safe here because nothing else reads it
  until the await resumes.
- **Audit note**: if `_restore_last_selection` ever grows widget calls, this becomes unsafe. Add a comment at the
  definition to forbid that.

**`_save_current_query`** (`src/sase/ace/tui/actions/changespec.py:231`)

- Pure disk write. `await asyncio.to_thread(self._save_current_query)` directly.

**`_apply_startup_loading_state`** — no change; stays on the main thread. Already fast (in-memory widget property
flips).

### 3. No changes to the stopwatch widget itself

`src/sase/ace/tui/widgets/keybinding_footer.py` is correct as-is. The `set_interval(0.1, ...)` and `_on_stopwatch_tick`
logic work fine — they just need the event loop to be free, which this plan provides.

### 4. No changes to `AceApp.__init__`

`__init__` also does synchronous disk I/O (config/keymap loads on lines 310, 312, 317, 375, 380, 390, 414), but
`__init__` runs before `run()` is called, i.e. before the event loop even exists. The stopwatch timer starts later (in
`KeybindingFooter.on_mount`), so `__init__` cost is pre-paid and does not contribute to the freeze. **Out of scope** for
this plan.

## What If a Helper Is Subtly Not Thread-Safe?

If the audit missed something — e.g., `_read_changespecs_from_disk` turns out to import a module that uses a
non-thread-safe singleton, or `find_all_changespecs` internally touches something shared — the symptom would be a race,
exception, or garbled state at startup.

**Fallback plan** — Option C: keep `on_mount` synchronous and move the heavy loaders into `call_after_refresh`
callbacks, mirroring `_run_axe_startup_init`. Introduce a CLs-tab loading placeholder so the tab doesn't flash empty.
This is more code but dodges the threading question entirely.

Run the manual smoke test below with `-X faulthandler` / extra logging before deciding we're safe.

## Test Plan

**Manual smoke tests (required — these verify the actual fix):**

1. Run `sase ace` in a terminal with axe stopped. The bottom-right badge should show `⏱ starting 0.0s`, tick at ~10Hz
   visibly up to ~3s, then transition smoothly to red `STOPPED` or yellow `STARTING`/green `RUNNING` depending on axe
   state. The digit-count changes every 100ms should be obvious to the eye.
2. Run `sase ace` with axe already running. The stopwatch should tick briefly (even <1s) then transition to green
   `RUNNING`. No flicker.
3. Simulate a slow load: temporarily make `collect_axe_status_data` `time.sleep(35)`. The stopwatch should tick past 10s
   (color shifts to dark-orange), keep ticking, and at 30s the safety timeout fires and the badge falls back to the
   normal status.
4. Confirm no regression in the CLs tab: the startup query's results should appear at the same time they do today;
   saved-query fallback still works; last-selection restoration still lands on the right row.
5. Confirm no regression in the Agents tab: the existing agent loading spinners still appear and clear at the expected
   moment.

**Unit / integration tests:**

- Add a test that `AceApp.on_mount` is a coroutine (`inspect.iscoroutinefunction`) — locks in the contract.
- Add a test for the new `_read_changespecs_from_disk` pure function: given a fixture directory, it returns the expected
  list with no widget context.
- The existing keybinding-footer stopwatch tests do not need changes.
- Textual has a `Pilot` harness for integration testing; if feasible, add a test that mounts `AceApp` with a mocked slow
  changespec loader and verifies `KeybindingFooter._startup_elapsed` advances past 0.5s while the loader is still
  pending. This is the direct regression test for this bug.

## Risk Analysis

- **Keypress during the startup gap**: keypress handlers fire on the event loop, same as before. The gap becomes _more_
  interactive now (the loop is free), so handlers that assume `self.changespecs` is populated may now fire with an empty
  list. Audit: the current `on_mount` already runs `_apply_startup_loading_state` _before_ the `call_after_refresh`
  yields, so handlers already have to tolerate partially-loaded state (e.g., agents not yet loaded). The new gap for
  changespecs is analogous; existing guards in handlers (like "if no selection, return") should cover it. **Action
  item**: spot-check the top 5 most common keypress handlers (quit, refresh, tab switch, j/k, enter) for
  `self.changespecs`-empty safety.
- **Ordering dependencies**: `_apply_startup_loading_state` today runs after changespecs are loaded; if we keep that
  order across awaits, nothing changes. Preserve exactly: `await read_notifications → apply` →
  `await read_changespecs → apply` → `await try_fallback_async` → `await save_current_query` →
  `await restore_last_selection` → `_apply_startup_loading_state` → `call_after_refresh(...)` yields.
- **`_mounting` flag lifetime**: currently `True` for the whole body. With awaits added, other event-loop handlers may
  observe `_mounting = True` mid-startup. Check all readers of `self._mounting` and confirm they behave correctly (the
  flag exists to suppress certain events during mount; a _longer_ `_mounting=True` window is generally safer, not
  riskier).
- **Exception paths**: an exception during any `await` must still run `self._mounting = False`. `try / finally` in
  `async def` handles this; no extra work needed.
- **30s safety timeout still applies**: if the split loaders fail or hang, the stopwatch self-terminates at 30s and
  shows whatever the real status is. No change to that logic.

## Rollout

Single commit. Pure TUI polish — no CLI surface, no config, no migration. Ship the split helpers and the async
`on_mount` together so no intermediate state is broken.

## Deliberately Out of Scope

- Parallelizing the four disk reads (they're sequential today and this plan keeps them sequential — parallelizing would
  shave ~1s off startup but is a separate optimization).
- Moving `AceApp.__init__` disk I/O off the main thread (see above — doesn't affect stopwatch).
- Any UX change to the stopwatch itself (color, label, cadence) — the prior plan's UX stands.
