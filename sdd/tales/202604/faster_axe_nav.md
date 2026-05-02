---
create_time: 2026-04-23 15:57:47
status: done
prompt: sdd/prompts/202604/faster_axe_nav.md
---

# Plan: Make Axe tab navigation in `sase ace` WAY faster

## Problem

Pressing Ctrl+N / Ctrl+P on the Axe tab to move between lumberjacks (or between the `axe` parent and a lumberjack, or
between lumberjacks and bgcmd entries) stalls the TUI for hundreds of milliseconds to seconds per key press. The
navigation feels laggy even though no underlying data has changed.

### Root cause

Every `current_idx` change re-runs `_refresh_axe_display()` synchronously on the event-loop thread, and that method does
**disk I/O per navigation**:

1. **Per-lumberjack view** (`src/sase/ace/tui/actions/axe_display.py:374-375`):
   - `read_lumberjack_log_tail(name, 500)` — scans up to 1000 lines of the log file via a `deque`
     (`src/sase/axe/state.py:541-559`).
   - `read_lumberjack_status(name)` — JSON read (`state.py:453-469`).
   - `read_lumberjack_metrics(name)` — JSON read (`state.py:483-499`) when the main axe view is shown (see below).
2. **Main axe (parent) view** (`axe_display.py:403-413`): loops over every lumberjack and calls
   `read_lumberjack_status()` + `read_lumberjack_metrics()` per lumberjack. This is an N+1 blocking read that runs every
   time the parent row is highlighted.
3. **Bgcmd view** (`axe_display.py:425-434`): calls `get_slot_info(slot)`, `is_slot_running(slot)`, and
   `read_slot_output_tail(slot, 500)` per nav — also blocking.
4. **Tab-bar count refresh** (`axe_display.py:280-304`, `_update_axe_tab_count`): iterates every lumberjack and calls
   `read_lumberjack_status(name)` again to count running lumberjacks. This runs during every apply of collected axe data
   and is an extra N round-trip on top of the collector's own N reads.

The expensive data is already fetched asynchronously by `_collect_axe_status_data()` / `_load_axe_status_async()`
(`axe_display.py:59-108, 201-206`) and by `_on_auto_refresh` (`event_handlers.py:73-78`). But the **lumberjack log
tail** and **per-lumberjack status/metrics** are not part of that collected payload, and the navigation path never uses
the collected payload anyway — it re-reads from disk instead.

Meanwhile the CLs tab has no such stall because changespec data is loaded once into memory and navigation just
re-renders from the in-memory list. The Agents tab hides its own I/O behind `_refresh_agents_display_debounced()`
(`src/sase/ace/tui/actions/agents/_display.py:142-174`), which updates the visible highlight synchronously and defers
the expensive detail panel update by 150 ms, collapsing bursts of navigation into one final render.

Recent work (`fix: Keep ace TUI responsive during y refresh on CLs and Axe tabs`, commit b2915f4c) moved the full axe
status refresh behind `_schedule_axe_async_refresh`, so the `y` keymap and the auto-refresh tick no longer block on the
big collector. But navigation (`watch_current_idx` → `_refresh_axe_display`) still punches straight through to
synchronous disk I/O for the per-lumberjack and per-bgcmd fields.

## Goals

1. Ctrl+N / Ctrl+P between any items on the Axe tab returns control to the user in a single frame (<50 ms) even on cold
   caches. The highlight moves instantly; the info/dashboard panels follow.
2. Navigating across a fleet of many lumberjacks does not regress as the count grows (kill the N+1 in the parent view).
3. The `y` force-refresh keymap still produces fresh on-disk data for the currently selected lumberjack/bgcmd — nothing
   becomes stale past the user's next refresh tick.
4. The periodic auto-refresh (`_on_auto_refresh`) continues to keep the whole fleet's status/metrics/log-tail reasonably
   current without blocking.

## Non-goals

- Changing the lumberjack / bgcmd artifact layout on disk.
- Incremental tail-reads (watching log files for appends). A capped `deque` over the log file, read in a background
  thread, is fast enough.
- Touching the CLs tab navigation path — it is already fast.

## Approach

Use **both** caching and async refresh, because each solves a different part of the pain:

- **Caching** lets `watch_current_idx` render from memory on every key press. This is what the CLs tab does and what
  makes j/k there feel instant. This single change eliminates the dominant stall.
- **Async refresh** keeps the cache fresh without blocking. The periodic tick already uses `asyncio.to_thread`; we
  extend the collected payload so that per-lumberjack status/metrics/log-tail and per-bgcmd info/tail are loaded off the
  event loop in the same pass.
- **Debounced targeted refresh** on the `y` keymap guarantees fresh data for the currently viewed lumberjack without
  forcing the user to wait for a whole-fleet reload.

Caching alone is insufficient (the first paint after launch still needs the data, and stale caches would feel wrong on
`y`). Async alone is insufficient (a 100 ms background read still freezes the next keystroke if we re-fetch on every
nav). The combination matches the pattern already working well for the Agents tab.

## Plan

### Phase 1 — Extend the async collector to include per-lumberjack and bgcmd data

Files:

- `src/sase/ace/tui/actions/axe_display.py`

Changes:

1. Expand `_AxeCollectedData` (lines 47-56) with three new fields:
   ```python
   lumberjack_statuses: dict[str, LumberjackStatus | None]
   lumberjack_metrics: dict[str, LumberjackMetrics | None]
   lumberjack_log_tails: dict[str, str]        # capped to e.g. 500 lines each
   bgcmd_details: dict[int, _BgCmdSnapshot]    # info + running + log tail
   ```
   where `_BgCmdSnapshot` is a small dataclass holding `info`, `running: bool`, and `output_tail: str` (500 lines).
2. Inside `_collect_axe_status_data()` (lines 59-108), after building `lumberjack_names`, iterate once and populate
   `lumberjack_statuses`, `lumberjack_metrics`, and `lumberjack_log_tails`. Do this sequentially inside the existing
   `asyncio.to_thread` worker; cost is linear in the number of lumberjacks but happens off the main thread. If the
   number grows, Phase 4 (below) parallelizes it.
3. Inside the same function, populate `bgcmd_details` for every active slot (`read_slot_output_tail(slot, 500)` +
   `get_slot_info` + `is_slot_running`), so navigation to a bgcmd row paints from cache too. This replaces the currently
   inline reads at `axe_display.py:425-434`.

### Phase 2 — Apply cached data to app state, and render from it

Files:

- `src/sase/ace/tui/actions/axe_display.py`

Changes:

1. In `_apply_axe_status_data()` (lines 143-199), copy the new collected maps onto four new app-state attributes:
   ```python
   self._axe_lumberjack_statuses: dict[str, LumberjackStatus | None]
   self._axe_lumberjack_metrics: dict[str, LumberjackMetrics | None]
   self._axe_lumberjack_log_tails: dict[str, str]
   self._axe_bgcmd_details: dict[int, _BgCmdSnapshot]
   ```
   Initialize all four to `{}` alongside the other `_axe_*` attributes in `AceApp.__init__` so they exist before the
   first async load completes.
2. Rewrite `_refresh_axe_display()` (lines 350-487) so it **never performs disk I/O**:
   - Lumberjack view reads `self._axe_lumberjack_log_tails[name]`, `self._axe_lumberjack_statuses[name]` — falls back to
     an empty/`None` placeholder if the key is missing (first paint before the async load lands).
   - Parent-axe view builds `lumberjack_summaries` from the in-memory dicts rather than calling `read_lumberjack_status`
     / `read_lumberjack_metrics` in the loop.
   - Bgcmd view reads `self._axe_bgcmd_details[slot]`; if missing, falls back to `get_slot_info(slot)` +
     `is_slot_running(slot)` but skips `read_slot_output_tail` (the log panel shows a brief "loading…" placeholder that
     clears on next async apply).
3. Change `_update_axe_tab_count()` (lines 280-304) to derive the running lumberjack count from
   `self._axe_lumberjack_statuses` instead of calling `read_lumberjack_status` per name. This eliminates a second,
   redundant N round-trip that currently runs from `_apply_axe_status_data` every time collected data arrives.

### Phase 3 — Debounce navigation, mirror the Agents tab pattern

Files:

- `src/sase/ace/tui/app.py`
- `src/sase/ace/tui/actions/axe_display.py`

Changes:

1. Add `_refresh_axe_display_debounced()` to the `AxeDisplayMixin`, modeled on `_refresh_agents_display_debounced`:
   - Immediately update the side-panel highlight (`bgcmd_list.update_highlight(local_idx)` — add that method on
     `BgCmdList` if not present, similar to `AgentList.update_highlight`) and the info-panel position counter.
   - Cancel any pending `_axe_detail_update_timer` and set a new 150 ms timer whose callback invokes the full
     `_refresh_axe_display()` (now cheap because it reads from cache).
2. In `watch_current_idx()` at `app.py:589-597`, change the `axe` branch from `self._refresh_axe_display()` to
   `self._refresh_axe_display_debounced()`.
3. Keep `_refresh_axe_display()` as the non-debounced entry point that every other caller (`_apply_axe_status_data`,
   `watch_current_tab` at `app.py:647`, exit-of-mode flows in `event_handlers._refresh_current_tab`, etc.) already uses
   — no changes needed there.

After Phase 2, a full `_refresh_axe_display()` is just widget updates from in-memory dicts, so the 150 ms debounce is
arguably optional for axe. Keep it anyway: the widget-query work (`query_one` for five widgets, formatting Rich markup
for the dashboard and log tail, updating the side panel) is still a few milliseconds per call, and the debounce
guarantees rapid j/k bursts render only the final frame.

### Phase 4 — Targeted `y` refresh + parallelization

Files:

- `src/sase/ace/tui/actions/base.py` (`action_refresh` at line 344)
- `src/sase/ace/tui/actions/axe_display.py`

Changes:

1. Add `_refresh_selected_axe_item_async()`: given the currently selected view (lumberjack name or bgcmd slot), re-read
   **only** that item's status/metrics/log-tail via `asyncio.to_thread`, merge the result into the in-memory dicts, then
   call `_refresh_axe_display()`. This is what `y` should do — the user explicitly asked for fresh data for what they're
   looking at; they should not wait for a full-fleet reload to see it.
2. Wire `action_refresh` (`base.py:344-355`) to call the new targeted refresh **in addition to** the existing
   `_schedule_axe_async_refresh()`. The targeted refresh finishes first and repaints the focused panels; the full-fleet
   refresh lands whenever it lands.
3. Optionally (if Phase 1's sequential loop is still noticeable for users with many lumberjacks), parallelize the
   per-lumberjack fan-out inside `_collect_axe_status_data()` using a bounded `ThreadPoolExecutor`
   (`max_workers=min(8, os.cpu_count() or 4)`). Keep it as a module-level singleton and reuse across collects. Defer
   this until profiling shows it matters — linear scan over 10–20 lumberjacks is probably fine.

### Phase 5 — Startup and tab-switch polish

Files:

- `src/sase/ace/tui/app.py`
- `src/sase/ace/tui/actions/axe_display.py`

Changes:

1. `watch_current_tab()` axe branch (`app.py:642-648`) already calls `_refresh_axe_display()` then schedules an async
   refresh — now a no-op for stall risk because the first call reads cache. No change beyond verifying behavior after
   Phase 2.
2. Initialize `_axe_lumberjack_log_tails` / `_axe_bgcmd_details` so the very first render shows "loading…" placeholders
   (already in place for Axe info panel via `_axe_first_load_done`). Ensure the log-tail panel shows "loading…" instead
   of an empty box when the relevant key is absent.

## Interaction with the recent `y`-responsiveness work

Commit b2915f4c already routed `y` and auto-refresh through `_schedule_axe_async_refresh()` so neither blocks the event
loop. This plan preserves that contract:

- `_load_axe_status_async` continues to be the sole full-fleet loader; we only grow its returned payload (Phase 1).
- `_schedule_axe_async_refresh` is still the hammer used by `y` — we add a faster lightweight refresh **in parallel**
  rather than replacing it (Phase 4).
- Navigation stops triggering any disk I/O at all (Phase 2), so even if the auto-refresh tick is mid-flight, j/k stays
  snappy.

## Correctness around `y`

- Targeted refresh (Phase 4) always hits disk for the focused item, so `y` guarantees the visible panels are up-to-date
  within one tick even if the full-fleet collector is slow.
- Cache entries are only written from `_apply_axe_status_data` and the targeted refresh, both of which run on the main
  thread. No locking needed.
- If a lumberjack is renamed/removed between the collect call and the apply, the existing `_axe_lumberjack_idx` clamp
  logic (`axe_display.py:181-184`) still fires. The new dicts are authoritative relative to `lumberjack_names`: readers
  look up by name, so stale keys are simply ignored.
- Bgcmd slots that transition from running → finished during a collect call are handled identically to today
  (`_collect_axe_status_data` calls `mark_slot_finished` when needed, lines 95-97). The collected snapshot then carries
  the finalized info.

## Tests

Existing tests to keep green:

- `tests/test_axe_lumberjack.py`
- `tests/test_axe_lumberjack_state.py`
- `tests/test_axe_lumberjack_config.py`

New tests to add:

1. `tests/ace/tui/test_axe_navigation.py` (new): drive the TUI harness with a fixture of N lumberjacks, assert that
   switching with Ctrl+N / Ctrl+P:
   - never calls `read_lumberjack_status` / `read_lumberjack_metrics` / `read_lumberjack_log_tail` (monkeypatch each to
     raise; only the async collector path should touch them).
   - renders the expected lumberjack name / status within one debounce tick.
2. `tests/ace/tui/test_axe_collector.py` (new, or extend existing): assert `_collect_axe_status_data()` populates all
   four new maps for a fixture with two lumberjacks and one bgcmd slot.
3. `tests/ace/tui/test_axe_force_refresh.py` (new): simulate `y` on a selected lumberjack, assert the targeted refresh
   updates the dict entry for that name and the dashboard renders the new status, independent of whether the full-fleet
   refresh has completed.

## Success criteria

- Ctrl+N / Ctrl+P on the Axe tab returns control in a single frame (<50 ms) with 20 lumberjacks + 5 bgcmd slots present
  on the profiled hardware.
- A fresh launch of `sase ace` shows "loading…" placeholders for at most one tick, then fully populates once the first
  async collect completes.
- `y` on a focused lumberjack repaints that lumberjack's panels within one debounce tick even while the full-fleet
  refresh is mid-flight.
- `_refresh_axe_display()` calls made during navigation execute zero disk reads (verified via monkeypatched state.py
  readers in the new navigation test).
