---
create_time: 2026-04-24 14:34:50
status: done
prompt: sdd/prompts/202604/startup_stopwatch.md
---
# Plan: Startup Stopwatch in `sase ace` Bottom-Right Corner

## Problem

When the `sase ace` TUI first launches, the bottom-right **AXE status indicator** shows `STOPPED` (rendered as
`" STOPPED "` with `bold white on red`) until the first async axe-status load completes — a gap of roughly **3.5
seconds**. This is misleading: the user cannot tell whether axe is _actually_ stopped or whether the TUI is simply still
loading, and the flash of scary red-on-white reads like an error state during what is really a healthy startup.

The user wants the indicator, while startup is in progress, replaced with a **live upward-counting stopwatch** (e.g.
`2.4s`) that updates every 0.1s and is visually prominent. Once startup is complete, the stopwatch vanishes and the
normal AXE status indicator takes over its slot.

## Design Goals

1. **Intuitive** — a user who has never seen the stopwatch should immediately understand it means "TUI is starting up,
   this long so far."
2. **Reliable** — the stopwatch must always terminate. If startup hangs or errors, it must not tick forever; a safety
   timeout falls back to the normal status.
3. **Beautiful** — distinctive, high-contrast, visually "alive." Not a clone of the existing status pills but coherent
   with them (uses the same padded badge style and bold face).
4. **No regressions** — bgcmd badges (`[*R]`, `[✓D]`) and all the non-startup states (`STARTING`, `STOPPING`, `RUNNING`,
   `RESTARTING`, `STOPPED`) keep working exactly as before.

## UX Design

### Visual

**Badge text:** `  ⏱ starting 2.4s  ` (leading + trailing space for padding, matching the other status pills'
convention).

- The `⏱` emoji + the word `starting` make the stopwatch's meaning obvious at a glance. The example the user gave
  (`"2.4s"`) only mentioned the numeric part, so I am intentionally going beyond spec to serve the "intuitive"
  requirement — a bare `2.4s` alone in that corner would be mysterious. If the user prefers a pure-numeric display, the
  label is a one-line change.
- Elapsed time always rendered with **one decimal place**, naturally matching the 0.1s tick cadence (so the display
  visibly ticks at 100ms rather than looking laggy).
- Format: `f"{elapsed:.1f}s"` — so `0.1s`, `2.4s`, `12.7s`, `123.4s`.

**Style:** `bold black on rgb(255,215,0)` — gold/amber.

- High contrast, instantly catches the eye.
- Distinct from the existing palette: green (RUNNING), red (STOPPED), yellow/amber (STARTING), orange (STOPPING), cyan
  (RESTARTING). Gold is close to yellow but clearly different in tone, and picked deliberately because it reads as
  _positive/active_, not _alarming_.
- Consistent padded-badge shape with the other status pills (leading + trailing space around the text, bold face, solid
  background).

**Optional subtle touch (recommended):** after the first 10s the badge shifts to `bold black on rgb(255,140,0)`
(dark-orange) to hint "this is taking longer than usual"; after 30s the safety timeout fires and the stopwatch is
replaced with the normal status. This escalates gracefully rather than leaving the user wondering.

### Lifecycle

1. **Start:** the stopwatch activates the moment the `KeybindingFooter` widget mounts (Textual mounts children before
   parents, so this is before the app's `on_mount` body runs — earliest possible point at which the footer is visible).
   We capture `time.monotonic()` as the anchor and spawn a 0.1s `set_interval` tick.
2. **Tick (every 0.1s):** recompute `elapsed = monotonic() - start`, re-render the `#keybinding-status` Static via the
   existing `_update_status()` path.
3. **End:** triggered the first time `_apply_axe_status_data` flips `_axe_first_load_done` to `True` in
   `src/sase/ace/tui/actions/axe_display/_loaders.py`. The loader reaches into the footer and calls
   `footer.end_startup_stopwatch()`, which stops the interval, clears the active flag, and re-renders the status (so the
   real AXE status — `RUNNING`/`STOPPED`/`STARTING`/etc. — appears immediately).
4. **Safety timeout:** 30s after start, if the stopwatch is still active, it self-terminates the same way. The user is
   never stuck staring at a runaway counter if the first load errors or hangs.

### Why `_axe_first_load_done` is the correct end signal

The AXE status reflects axe daemon state. The footer shows stale/default state (`STOPPED`) until the first axe-status
disk read completes in `_apply_axe_status_data`. That is exactly the point at which the status becomes _meaningful_.
Tying stopwatch end to `_axe_first_load_done` means the stopwatch hides exactly when (and only when) the normal
indicator starts telling the truth.

We deliberately do **not** tie it to `_agents_first_load_done` — that flag governs the Agents tab's loading spinners,
not the footer's right-hand status.

## Implementation Overview

### Files touched

1. **`src/sase/ace/tui/widgets/keybinding_footer.py`** — the widget that owns the status slot.
   - Add state fields: `_startup_stopwatch_active: bool` (default `True`), `_startup_start_time: float`,
     `_startup_elapsed: float = 0.0`, `_startup_stopwatch_timer: Timer | None`.
   - Add `on_mount()` hook: capture start time, call
     `self.set_interval(0.1, self._on_stopwatch_tick, name="startup-stopwatch")`, immediately re-render status.
   - Add `_on_stopwatch_tick()`: update elapsed, call `_update_status()`; if elapsed > 30s, call
     `end_startup_stopwatch()`.
   - Add public `end_startup_stopwatch()`: idempotent — stop the timer, flip flag to False, re-render status.
   - Modify `_get_status_text()`: when `_startup_stopwatch_active` is True, return a gold badge `  ⏱ starting 2.4s  `;
     otherwise fall through to the existing status cascade. The bgcmd badges still append below the status (keeps
     existing behavior — bgcmds during startup are rare but possible, and showing them is strictly better than hiding
     them).

2. **`src/sase/ace/tui/actions/axe_display/_loaders.py`** — the first-load trigger point.
   - Inside `_apply_axe_status_data`, in the existing `if not self._axe_first_load_done:` block (lines 86–102), after
     clearing the dashboard/info-panel loading flags, also fetch the `KeybindingFooter` via
     `self.query_one("#keybinding-footer", KeybindingFooter)` and call `footer.end_startup_stopwatch()`. Wrap in
     `try/except` mirroring the existing defensive style in that block.

### What does NOT change

- Status cascade logic (`_axe_restarting`/`_axe_starting`/`_axe_stopping`/`_axe_running` → pill text and color) stays
  byte-identical.
- bgcmd badge appending stays as-is.
- All other status setters (`set_axe_running`, `set_axe_starting`, etc.) stay as-is — they operate on the underlying
  state and call `_update_status()`, which continues to pass through `_get_status_text()`. While the stopwatch is active
  these state mutations are effectively invisible, but they still update the backing fields — so the moment the
  stopwatch ends, the correct pill appears with zero flicker.
- No changes to `on_mount` in `AceApp`, no changes to other mixins, no new reactive properties.

### Edge cases handled

- **Rapid end:** if `_apply_axe_status_data` fires before the first 0.1s tick, the stopwatch simply never paints — the
  default `_get_status_text` path handles the first render. Safe.
- **Timer already stopped:** `end_startup_stopwatch()` is idempotent (checks the flag and timer before acting), so a
  safety-timeout and a real end that race are both fine.
- **Exception inside `collect_axe_status_data`:** `_axe_first_load_done` never flips, so the safety timeout takes over
  at 30s and the stopwatch falls back to the normal status. The user then sees `STOPPED` (which at that point is likely
  accurate, since the load failed).
- **App quit during startup:** Textual tears down intervals on unmount automatically; no leak.
- **Clock precision:** `time.monotonic()` is immune to wall-clock adjustments, so a DST change or ntp slew mid-startup
  cannot produce a negative elapsed or a jump.

## Test Plan

Add unit tests to a new `tests/ace/tui/widgets/test_keybinding_footer_stopwatch.py`:

1. **Default state shows stopwatch:** freshly instantiated `KeybindingFooter` has `_startup_stopwatch_active=True`;
   `_get_status_text()` returns a `Text` containing `⏱` and `starting` with the gold background style.
2. **Elapsed formatting:** given `_startup_elapsed=2.4`, rendered text contains `"2.4s"`; given
   `_startup_elapsed=12.75`, text contains `"12.8s"` (one-decimal rounding).
3. **End transitions to real status:** after `end_startup_stopwatch()`, `_get_status_text()` no longer contains `⏱`;
   with `_axe_running=True` it renders the green `RUNNING` pill; with all flags False it renders the red `STOPPED` pill.
4. **Idempotence:** calling `end_startup_stopwatch()` twice is safe and does not raise.
5. **bgcmd badges appear alongside the stopwatch:** setting `set_bgcmd_count(running_count=2, done_count=1)` while the
   stopwatch is active produces text containing both the stopwatch and the `[*2]` / `[✓1]` badges.

Manual smoke test after implementation:

- Run `sase ace` in a terminal with axe stopped; verify the bottom-right corner shows a ticking gold `⏱ starting N.Ns`
  badge for ~3.5s, then transitions smoothly to the normal AXE status.
- Run `sase ace` with axe already running; verify the stopwatch appears briefly (even <1s is visible) and transitions to
  green `RUNNING`.
- Simulate a slow/hung load (e.g. make `collect_axe_status_data` sleep 35s); verify the safety timeout kicks in and the
  badge falls back to the normal pill at 30s.

## Rollout

This is a pure TUI polish change — no CLI surface, no config, no migration, no external state. Ship in a single commit.

## Deliberately Out of Scope

- Generalizing the stopwatch to any other first-load gap (e.g. agents tab). The agents tab already has its own dedicated
  loading spinners/ellipses in `_apply_startup_loading_state`, so this would be duplicative.
- User-configurable precision, label text, or color. Can be added later if anyone asks.
- Animation beyond the 0.1s number tick (pulse, spinner character rotation). Keeps things simple and avoids fighting
  Textual's repaint batching.
