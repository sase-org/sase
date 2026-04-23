---
create_time: 2026-04-23 17:29:55
status: wip
---
# `sase ace` Startup Stopwatch Splash Screen

## Problem

`sase ace` takes a visible ~3–4 s from invocation to fully-ready interactive state:

- ChangeSpecs load synchronously on `on_mount`
- Agents load asynchronously via `call_after_refresh(_run_agents_async_refresh)` (~2–3 s disk scan)
- AXE daemon/status initialises asynchronously via `call_after_refresh(_run_axe_startup_init)` (~1–2 s)

During that window the user currently sees the partially-populated TUI with small `…` indicators in tab labels
(`TabBar`), info panels (`AgentInfoPanel`, `AxeInfoPanel`), and a spinner in `AgentList`. That works, but it is quiet —
there is no positive signal that startup is actually progressing, and no way to tell from a glance how long it took. The
prior attempt at a “bold centered startup loading banner” (commits `8b355229`, `4546fd27`) was reverted three times
(`95898aa6`, `9fc03240`, `3b625924`) — it was too static and intrusive to justify the cost of covering the UI.

We want a **startup screen** that is worth covering the UI for: an **extra-large, tenth-second-granularity stopwatch**
showing exactly how long `sase ace` took to start, paired with live milestone checks so the user knows what is still
outstanding.

## Goals

1. **Inform** — the user knows at a glance that the TUI is still starting, how long it has taken so far, and what is
   outstanding (ChangeSpecs / Agents / AXE).
2. **Measure honestly** — the stopwatch reflects the true time from process entry to fully-ready, at 0.1 s precision.
3. **Beautiful** — large block-character digits that fit the flexoki theme; centered and unmistakable; no accidental
   flicker on fast paths.
4. **Unobtrusive** — auto-dismisses the moment startup completes; a single keystroke also dismisses early so it never
   blocks a power user.
5. **Reliable & testable** — deterministic rendering (pure function of elapsed-seconds input), dismisses predictably
   under the `AcePage` test harness, and does not regress existing startup-loading-indicator tests.

## Non-goals

- Persisting startup-time history (trends, regressions) — a follow-up.
- Per-milestone elapsed times displayed in the final frame — keep the readout focused on one number; milestones are
  shown as checkmarks only.
- A dependency on `pyfiglet`. The large digits are hand-rolled so we own the exact glyphs and styling.
- Replacing the in-TUI `…` loading indicators. Those stay as the second-line feedback once the splash dismisses.
- Capturing Python interpreter boot time. We start the clock at the top of `src/sase/__main__.py`, which is the earliest
  practical point inside the Python process.

## User experience

1. User runs `sase ace`.
2. Within a frame of the event loop starting, a **full-screen splash** appears over the TUI:
   ```
   ┌───────────────────────── starting sase ace ─────────────────────────┐
   │                                                                     │
   │              ██████  ██████        ██████                           │
   │              ██  ██      ██  ██    ██                               │
   │              ██  ██  ██████        ██████                           │
   │              ██  ██  ██    ██          ██                           │
   │              ██████  ██████        ██████                           │
   │                    (ticks at 10 Hz → “03.4”)                        │
   │                                                                     │
   │                        starting sase ace…                           │
   │                                                                     │
   │                   ✓  ChangeSpecs                                    │
   │                   …  Agents                                         │
   │                   …  AXE                                            │
   │                                                                     │
   │                    press any key to skip                            │
   └─────────────────────────────────────────────────────────────────────┘
   ```
3. Digits tick every 100 ms (`SS.T` format, e.g. `03.4`). If startup exceeds 99.9 s we fall back to `MM:SS.T`
   (`01:42.7`).
4. As each phase completes, its `…` flips to `✓` in `$success`. The `Agents` and `AXE` lines show a subtle animated
   ellipsis (`.` → `..` → `…`) while pending so the list never looks frozen even if the stopwatch is the focal point.
5. When the last phase completes:
   - Stopwatch freezes on its final value.
   - The digits recolor to `$success` and the subtitle swaps to `ready in 3.4s`.
   - After ~450 ms the splash dismisses to reveal the fully-loaded TUI.
6. Any of `Esc`, `q`, `space`, `enter`, or `Ctrl+C` (standard quit) dismisses early. When dismissed early the in-TUI `…`
   indicators remain until the async loads finish — no new behavior there, the existing system just takes over.
7. If startup is very fast (e.g. warm caches finishing in <300 ms), we still show the splash briefly (see _Minimum
   display time_ below) so it does not flash. This is a small, opinionated choice — see tradeoffs.

## Design

### Timing source of truth

- Add `PROCESS_START_PERF_COUNTER: float = time.perf_counter()` at the top of `src/sase/__main__.py` (before any `sase`
  imports). This is the **earliest practical timestamp** in the Python process and what the stopwatch reads from.
- Expose it via a tiny new module `src/sase/main/startup_timing.py` (`get_process_start()` + a settable override for
  tests). `__main__.py` writes into that module so there is no circular-import risk.
- Every elapsed reading is `time.perf_counter() - PROCESS_START_PERF_COUNTER`. We never trust wall-clock time for this.

### Ready signal

The splash considers startup complete when **all three** milestone flags are true:

- `changespecs_ready` — set at the end of `AceApp._load_changespecs()` on `on_mount` (always true by the first frame).
- `agents_ready` — set when `AceApp._agents_first_load_done` flips to `True` (see `actions/agents/_loading.py`).
- `axe_ready` — set when `AceApp._axe_first_load_done` flips to `True` (see `actions/axe_display.py`).

Rather than polling, `AceApp` calls `splash.mark_<phase>_ready()` from the same code paths that flip the flags today.
The splash screen exposes those methods as no-ops if the screen has already been dismissed (so an early skip cannot
crash late-arriving async callbacks).

### Component breakdown

New files:

| Path                                            | Purpose                                                                                      |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `src/sase/main/startup_timing.py`               | Shared start-timestamp accessor (pure, no Textual deps).                                     |
| `src/sase/ace/tui/widgets/_big_digits.py`       | Pure renderer: `render_big_digits(text: str) -> str` for digits `0-9`, `:`, `.`.             |
| `src/sase/ace/tui/widgets/startup_stopwatch.py` | `StartupStopwatch(Static)` — owns the 10 Hz tick, reads start timestamp, renders big digits. |
| `src/sase/ace/tui/modals/startup_splash.py`     | `StartupSplashScreen(ModalScreen[None])` — composes title, stopwatch, subtitle, milestones.  |
| `tests/ace/tui/test_big_digits.py`              | Unit tests for `render_big_digits` (per digit, format, edge cases).                          |
| `tests/ace/tui/test_startup_stopwatch.py`       | Unit tests for the tick/format behavior using a fake-clock seam.                             |
| `tests/ace/tui/test_startup_splash.py`          | Screen-level tests: milestone checks, dismissal, skip keybinding.                            |

Edits:

| Path                                          | Change                                                                                       |
| --------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `src/sase/__main__.py`                        | Capture process-start perf counter before any other import.                                  |
| `src/sase/ace/tui/app.py`                     | On `on_mount`, push splash first; call `mark_changespecs_ready` after `_load_changespecs()`. |
| `src/sase/ace/tui/actions/agents/_loading.py` | After flipping `_agents_first_load_done`, notify splash (if present).                        |
| `src/sase/ace/tui/actions/axe_display.py`     | After flipping `_axe_first_load_done`, notify splash (if present).                           |
| `src/sase/ace/tui/widgets/__init__.py`        | Export `StartupStopwatch`.                                                                   |
| `src/sase/ace/tui/styles.tcss`                | Splash screen layout + color rules using flexoki theme variables.                            |
| `src/sase/ace/testing.py` (`AcePage`)         | `AcePage(..., skip_splash: bool = True)` default so existing tests don’t have to change.     |

### Big-digit rendering

Each glyph is a 5-row × 6-column grid rendered with `█` (full block) on a blank background. Example for `3`:

```
██████
    ██
██████
    ██
██████
```

`.` is two `█` in the bottom-right corner of a 2-column cell; `:` is two `█` stacked mid-height in a 2-column cell.
Column/row counts are constants so tests can assert exact output. `render_big_digits(text)` joins glyphs with a 1-column
gap and returns a single `\n`-separated `str`. The `StartupStopwatch` wraps that in a Rich `Text` with `style=$primary`
(recoloring to `$success` on completion).

This hand-rolled approach is well under 200 LOC, has zero runtime deps, and lets us stylize via Textual CSS instead of a
figlet font.

### Tick loop

`StartupStopwatch.on_mount`:

```python
self._update_timer = self.set_interval(0.1, self._tick)
self._tick()  # paint immediately so the user sees digits in the first frame
```

`_tick` reads the elapsed seconds, formats to `SS.T` (or `MM:SS.T` past 99.9 s), and calls `self.update(rendered)`. When
the splash is told to freeze, it stops the timer and records the final value so the last frame is stable.

### Minimum display time

If all three `mark_*_ready()` calls fire before the splash has been visible for **300 ms**, defer the final freeze until
the 300 ms mark, then do the freeze+recolor → auto-dismiss after 450 ms (so total minimum on-screen time is ~750 ms).
This prevents a jarring single-frame flash on warm-cache runs and still keeps total overhead under a second for fast
paths. The 300 ms minimum is configurable via a module-level constant in `startup_splash.py` so we can tune it based on
dogfooding.

### Integration into `AceApp.on_mount`

```python
# new: push splash first, hold a ref
self._startup_splash = StartupSplashScreen(process_start=get_process_start())
self.push_screen(self._startup_splash)

# existing body unchanged…
self._load_changespecs()
self._startup_splash.mark_changespecs_ready()
# …
self.call_after_refresh(self._run_agents_async_refresh)
self.call_after_refresh(self._run_axe_startup_init)
```

Agents and AXE notifications live in the action modules that already flip the first-load flags — so the splash is
updated from the same code path as the existing `…` → populated UI transition, and the two stay in sync by construction.

Suppression hook for tests: if `self._suppress_startup_splash` is set (wired via `AcePage(skip_splash=True)`), skip the
`push_screen` call entirely and let the `mark_*` calls no-op.

### Styling (TCSS)

New section in `styles.tcss`:

```
StartupSplashScreen {
    align: center middle;
    background: $surface 75%;   /* subtle scrim over the still-building TUI */
}

StartupSplashScreen > #splash-body {
    width: auto;
    height: auto;
    padding: 2 4;
    border: round $primary;
    background: $surface;
}

StartupSplashScreen > #splash-body > StartupStopwatch {
    content-align: center middle;
    color: $primary;
    text-style: bold;
}

StartupSplashScreen.-ready > #splash-body > StartupStopwatch {
    color: $success;
}
```

A single CSS class (`-ready`) toggles the completion look so the freeze + recolor is declarative.

## Testing strategy

- **Pure renderer tests** (`test_big_digits.py`): For each supported glyph, assert the exact 5×6 string. Assert that
  `render_big_digits("03.4")` produces the expected concatenation with one-column gaps. Assert that unsupported
  characters raise.
- **Stopwatch tests** (`test_startup_stopwatch.py`): Inject a fake `perf_counter` via the `startup_timing` override
  seam, call `_tick` at known timestamps, assert rendered content. No sleeps.
- **Splash screen tests** (`test_startup_splash.py`): Using `AcePage(skip_splash=False)`, assert:
  - Splash is on top after mount.
  - `mark_changespecs_ready` flips the `…` on the first milestone to `✓`.
  - Once all three mark-calls fire, the screen is removed within the expected window (use `AcePage.wait_for(...)` rather
    than sleeps).
  - Pressing `esc` dismisses early and the splash is no longer in the screen stack.
- **Regression**: existing `test_startup_loading_indicators.py` continues to pass unchanged (AcePage suppresses the
  splash by default).
- **Smoke**: manual `sase ace` run before and after; `just check` green; no new lint warnings.

## Risks and tradeoffs

- **Prior reverts**: three earlier splash attempts were reverted. The failure mode there was “static banner adds no
  information, covers the UI.” This design earns its screen real estate: the stopwatch is novel information (not
  available anywhere else), milestones are live, and the screen auto-dismisses. Still — we should review the revert
  commits (`3b625924`, `95898aa6`, `9fc03240`) before implementing to confirm there isn’t a blocker we missed.
- **Minimum-display-time vs. feels-fast**: Holding the splash for 750 ms even when startup completes in 200 ms is a
  deliberate choice (beauty over raw speed). If dogfooding says it feels sluggish, we can drop to 0 ms — all that
  changes is a constant.
- **Modal covers everything**: Users cannot interact with the TUI while the splash is up. The early-skip keybindings
  mitigate this, and total splash time is bounded by the existing async loads (~3–4 s) which are themselves the reason
  startup feels slow today.
- **Timing accuracy**: Start-time is from `src/sase/__main__.py` top, so Python interpreter boot (tens of ms) is not
  counted. That matches the practical “how long did `sase ace` take to become usable” question.
- **Hand-rolled digits**: We own the font. Adding new glyphs later is trivial, and we avoid a `pyfiglet` dependency.
- **AcePage default**: Defaulting `skip_splash=True` in tests is a maintenance shortcut. A more principled alternative
  is to make every test go through the splash path — we prefer the shortcut because the splash is purely cosmetic and
  adds deterministic-but-unproductive latency to hundreds of tests.

## Rollout

1. Land pure renderer + unit tests.
2. Land stopwatch widget + unit tests.
3. Land splash screen + screen tests (AcePage-based).
4. Wire into `AceApp.on_mount` + `_loading.py` + `axe_display.py`. Manual verification on a real `sase ace`.
5. `just check` green; dogfood for a day; tune `MINIMUM_DISPLAY_SECONDS` if needed.
