---
create_time: 2026-04-23 15:29:00
status: done
prompt: sdd/prompts/202604/ace_loading_indicators.md
---

# Beautiful Startup Loading Indicators for `sase ace` TUI

## Problem

Phases 1+2 of the fast-startup work landed: `on_mount` now returns in ~300ms and agents/axe state loads asynchronously
in background threads (`_run_agents_async_refresh`, `_run_axe_startup_init`). Startup is dramatically snappier, but the
**~3.5 second gap between first paint and first data looks broken**:

- The **Agents tab label** shows `Agents (0)` — indistinguishable from "you have no agents."
- The **Agent list panel** is a blank `OptionList` with a border and nothing inside.
- The **Pinned panel** and **Agent info panel** show zero counts.
- The **Axe info panel** says "AXE: not running" even when axe is running — just nothing loaded yet.
- The **Axe dashboard** shows zero metrics and an empty lumberjack list.

The user sees this as a broken-looking TUI for 3+ seconds. We need clear, polished "loading" state that distinguishes
**"not yet loaded"** from **"loaded, empty"**.

ChangeSpecs do NOT have this problem — they load synchronously in `on_mount` before first paint. This plan does not
touch them.

## Key Insight

Textual 8.0 (installed in this repo — confirmed via `textual.__version__`) ships two features that do the heavy lifting
for us:

1. **`Widget.loading: reactive[bool]`** — setting `widget.loading = True` swaps the widget's content with an animated
   `LoadingIndicator` automatically and reverses when set to `False`. No manual widget juggling, no placeholder widgets
   to add/remove, correct default styling that matches the Textual theme.
2. **`LoadingIndicator`** — a pulsing "braille dot" spinner that inherits theme colors.

This is exactly the idiom we want for the two big panels (agent list, axe dashboard). For the tab-bar text labels (where
we can't swap in a spinner widget because the label is a string), we use a dim `…` ellipsis glyph.

The whole feature is ~100 LoC of state plumbing plus a pinch of TCSS. No widget refactors.

## Scope / Surfaces

From the research, there are three categories of surface that need loading treatment:

**A. Big content panels** (use `Widget.loading = True`):

- `#agent-list-panel` (the `AgentList` OptionList)
- `#pinned-list-panel` (also `AgentList`)
- `#axe-dashboard` (the `AxeDashboard` widget — lumberjacks + metrics + output)

**B. Compact label/status widgets** (use dimmed text):

- Tab bar — Agents tab label
- Agent info panel — the "N agents" count line
- Axe info panel — daemon status line

**C. Deliberately not touched:**

- ChangeSpecs tab, CL list, CL info — synchronous, already populated.
- Any modal / overlay — not shown at startup.

## Design

### Visual language

One cohesive loading vocabulary across the whole TUI:

- **Spinner (`LoadingIndicator`)** for big panels whose content is about to appear. Centered, theme-colored.
- **`…` ellipsis, dim + italic** for text labels whose value is about to appear. Compact, non-jarring, doesn't change
  the widget's geometry (so the tab bar doesn't reflow when counts arrive).
- **No progress bars, no percentages, no "Loading…" sentences.** We don't know a percentage, and 3.5 seconds is short
  enough that prose feels heavy. An ellipsis reads instantly.

### Color / style

Reuse the existing palette — do not invent new colors:

- `color: $text-muted` for dimmed ellipsis text.
- `text-style: italic` for the ellipsis (matches the aesthetic of secondary info elsewhere).
- Spinner inherits `$primary` by default — let it, so it matches the tab accent colors.
- Do **not** add opacity animations or shimmer — the built-in `LoadingIndicator` is already animated; adding a second
  animation on the same screen would fight for attention.

### State model

Add two boolean loaded-flags on `AceApp` — not a tri-state enum. We only need to answer: "have we received the first
result yet?"

```python
# app.py __init__
self._agents_first_load_done: bool = False
self._axe_first_load_done: bool = False
```

They start `False`, flip to `True` when their respective background task completes (once; never reset).

Why not refactor `_agents_with_children` from `[]` to `None`? Because 25+ call-sites iterate it, and most of them only
ever run after a load has completed (e.g. kill / mark / dismiss actions are user-driven post-load). A separate flag is
the localized fix.

### Per-surface behavior

**Agent list panel (`AgentList` — `src/sase/ace/tui/widgets/agent_list.py`)**

- In `on_mount` inside the widget, set `self.loading = True` if the app's `_agents_first_load_done` is False.
- When `_apply_loaded_agents` runs (in `_loading.py`), set `agent_list.loading = False` before calling `update_list()`.
  Same for the pinned panel.
- The pinned panel is an `AgentList` too — same treatment.

**Axe dashboard (`AxeDashboard` — `src/sase/ace/tui/widgets/axe_dashboard.py`)**

- Same pattern: `loading = True` until `_run_axe_startup_init` calls back with real data.
- Flip to `False` inside whatever method `_run_axe_startup_init` uses to apply status (likely `_apply_axe_status` /
  `_load_axe_status_async` finishing).

**Tab bar — Agents tab (`src/sase/ace/tui/widgets/tab_bar.py` `update_agents_count`)**

- Add a `loading: bool = False` kwarg.
- When `loading=True`, render the suffix as a dim italic `…` instead of `(0)` / pinned / done counts.
- Call `tab_bar.update_agents_count(loading=True)` once in `on_mount` (right after compose), then the first call from
  `_apply_loaded_agents` passes `loading=False` with real counts.
- Everywhere else that currently calls `update_agents_count(...)` continues to pass real counts (default
  `loading=False`). No caller changes except the one startup call.

**Agent info panel (count line)**

- When `_agents_first_load_done` is False, render `Agents: …` (dim, italic) instead of `Agents: 0`.
- Single branch where that line is composed. Minimal change.

**Axe info panel (`src/sase/ace/tui/widgets/axe_info_panel.py`)**

- Until axe status has arrived, render a dim `AXE …` line. Do **not** render `AXE: not running` (which is a factual
  claim that may be wrong during the gap).

### ChangeSpecs sanity check

ChangeSpecs load synchronously in `on_mount` before the call-after-refresh dispatches, so they are fully populated at
first paint. Confirm with a one-line manual test: open the TUI and the CLs tab should show correct counts immediately.
No code changes expected.

## File-by-file changes

**`src/sase/ace/tui/app.py`**

- `__init__`: add `self._agents_first_load_done = False` and `self._axe_first_load_done = False`.
- After `compose` / in `on_mount` (before calling `call_after_refresh(...)`): set `loading=True` on the tab bar's Agents
  label, and call a small helper `self._apply_startup_loading_state()` that:
  - finds `#agent-list-panel` and `#pinned-list-panel`, sets `.loading = True` on each,
  - finds `#axe-dashboard` and sets `.loading = True`,
  - triggers the agent-info-panel and axe-info-panel to re-render in their dim-ellipsis state.

**`src/sase/ace/tui/actions/agents/_loading.py`**

- In `_apply_loaded_agents` (the sync callback that runs on the main thread after the background load completes), just
  before updating the lists: set `self._agents_first_load_done = True`, clear `.loading` on the two `AgentList` widgets,
  and call `update_agents_count(loading=False, ...)` (the existing call path already passes real counts — just ensure
  `loading=False` is the default).

**`src/sase/ace/tui/actions/axe_display.py`**

- In the callback that applies axe status (after `_load_axe_status_async`), set `self._axe_first_load_done = True`,
  clear `.loading` on `#axe-dashboard`, and let `AxeInfoPanel` re-render in loaded state.

**`src/sase/ace/tui/widgets/tab_bar.py`**

- Extend `update_agents_count(...)` with `loading: bool = False`. When `loading`, emit the dim italic ellipsis as the
  suffix and skip the pinned/done/hidden count logic.

**`src/sase/ace/tui/widgets/agent_list.py`**

- No widget-code change needed (we flip `self.loading` from the app). Optional: in `on_mount`, if the app flag is False,
  pre-set `self.loading = True` so the spinner appears as early as possible on this widget's first paint rather than
  waiting one tick for the app's startup-loading helper.

**`src/sase/ace/tui/widgets/axe_info_panel.py`**

- Accept a `loaded: bool` reactive (or look up the app flag). When not loaded, render `AXE …` (dim italic) instead of
  the running/not-running line.

**`src/sase/ace/tui/widgets/axe_dashboard.py`**

- No widget-code change needed — flipped externally via `.loading`.

**`src/sase/ace/tui/styles.tcss`**

- Add one class, e.g. `.startup-loading-ellipsis { color: $text-muted; text-style: italic; }`. Re-use wherever the dim
  ellipsis is rendered (tab bar suffix, agent info panel, axe info panel).
- Do **not** globally style `LoadingIndicator` — Textual's defaults already look good with our theme. Only add a
  selector if the spinner visibly clashes (verify manually first).

## Test strategy

### Manual

1. `sase ace` on a machine with a cold JSON cache (delete `~/.sase/home/tmp/sase/_json_cache/` if it exists):
   - Within ~300ms: first paint.
   - For ~3s: agents list + pinned panel + axe dashboard show pulsing spinners; tab bar Agents label shows dim `…`;
     agent/axe info panels show dim `…`.
   - On load completion: spinners disappear, counts appear — no flicker, no geometry reflow.
2. `sase ace` on a warm cache: loading spinners should appear _briefly_ (a frame or two) or not at all. Either is
   acceptable — what we must not see is a "loaded, empty" state followed by spinners (wrong ordering).
3. `sase ace '!!!'` forcing no matches → fallback to agents tab. The agents tab should open with spinner, not with "no
   agents" messaging, until the background load finishes.
4. Tab-switch during loading: switch to CLs (instant), back to agents (spinner continues until load completes). No
   crash, no re-trigger of the load.
5. `sase ace --profile`: loading spinners should still be visible in the video; `_run_agents_async_refresh` runs off the
   main thread as before.
6. Post-load user actions (dismiss, kill, mark) work identically — the flags are startup-only and never reset.

### Automated

- `just check` must pass.
- Add a focused test under `tests/ace/tui/` that instantiates `AceApp`, asserts `_agents_first_load_done is False` and
  the relevant widgets have `loading=True` immediately after `on_mount`, then simulates the async callback and asserts
  the flags flip and `loading=False`.

### Perf

- `on_mount` timing unchanged (~300ms). Verify via `sase ace --profile` median of 3 runs.
- No new blocking I/O introduced — flags are pure booleans.

## Don't Do

- **Don't invent a tri-state enum (`"not_loaded" | "loading" | "loaded"`)** unless the research shows concrete
  call-sites that need all three. Two flags (`_agents_first_load_done`, `_axe_first_load_done`) are enough and simpler
  to reason about.
- **Don't refactor `_agents_with_children` to `None` to signal loading.** 25+ call-sites in `_core.py` / `_killing.py` /
  `_marking.py` / `_dismissing.py` iterate it; changing the sentinel invites null crashes in paths unrelated to startup.
  Use the separate flag.
- **Don't render "Loading agents…" prose.** A dim ellipsis + spinner is faster to parse and doesn't reflow geometry when
  it's replaced by a count.
- **Don't animate opacity or add a custom shimmer.** Textual's `LoadingIndicator` is already animated; a second
  animation on the same screen is noise.
- **Don't reset the flags on tab-switch or refresh.** They represent "has the very first load ever completed?" and must
  stay `True` once flipped. Auto-refresh cycles should never flash the spinner.
- **Don't set `.loading` inside a reactive watcher.** Set it from `on_mount` / the post-compose helper so the spinner
  appears on the same frame as first paint, not one tick later.
- **Don't touch `ChangeSpec` or `CLList` rendering.** They load synchronously; introducing a loading state would just
  add a one-frame flash and an unneeded code path.
- **Don't style `LoadingIndicator` globally** until you've verified with a manual run that the default spinner color
  clashes with the theme. It probably won't.
- **Don't remove the `_mounting` guard from Phase 1.** The double-load protection is independent of this work; combining
  them courts regressions.
