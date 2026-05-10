---
create_time: 2026-05-10 13:01:32
status: done
prompt: sdd/prompts/202605/file_panel_stale_diff_on_toggle.md
---
# Plan: Fix Stale File Panel Diff on `]` Visibility Toggle

## Problem

In the ace TUI Agents tab, after pressing `]` to toggle the detail-panel mode back to **AUTO** (file panel visible), the
file panel sometimes shows the **diff of a previously-selected agent** instead of the currently-selected one. Pressing
`j` then `k` (navigate to a neighbor row, then back) reliably fixes the display.

## Reproduction Sketch

The bug is most easily reproduced by:

1. Start in **AUTO** mode with agent **A** selected — the file panel correctly shows A's diff.
2. Press `]` to cycle through **THINKING → INFO** (file panel is now hidden).
3. Use `j` / `k` to navigate to a different agent **B**.
4. Press `]` to cycle back to **AUTO**. The file panel becomes visible but still displays A's content (stale render).
   The footer / `[N/M]` indicator has already updated to B, so the visual mismatch is obvious.
5. Press `j` then `k` to navigate away from B and back. The file panel now correctly shows B's diff.

## Root Cause Analysis

The `]` action eventually calls `AgentDetail._apply_panel_mode(AUTO, agent)` (in
`src/sase/ace/tui/widgets/_agent_detail_panels.py:178-192`). That branch:

1. Sets `self._panel_mode = AUTO`.
2. Removes the `hidden` class from `#agent-file-scroll`.
3. Calls `self.update_display(agent)` — i.e. `AgentDetail.update_display(agent)`.

Three independent mechanisms then conspire to leave the file panel visually stale:

### 1. `_update_display_impl` short-circuits in non-AUTO modes

While the user is cycling through THINKING/INFO and navigating with j/k, the debouncer fires
`agent_detail.update_display(new_agent)` for each selection. But `_update_display_impl`
(`src/sase/ace/tui/widgets/agent_detail.py:117-213`) **does not propagate the new agent to the file panel** when:

- `_panel_mode == INFO` — entire body returns at lines 174-179.
- `_panel_mode == THINKING` and the new agent is **not** in `_ACTIVE_STATUSES` — returns at lines 182-188 without
  calling `file_panel.update_display`.

As a result, while the panel is hidden, `AgentFilePanel._current_agent` and the on-screen render get **frozen at
whatever state existed when AUTO was last active** — typically agent A's diff.

### 2. `AgentFilePanel._update_display_body` early-returns on same-agent + fresh cache

When AUTO is finally restored and `_update_display_impl` calls `file_panel.update_display(agent)`, the dispatch
(`src/sase/ace/tui/widgets/file_panel/__init__.py:71-94`) checks
`same_agent and cache_entry is not None and age < stale_threshold`. If true, it **does not re-render** — comment says
"preserve trim state". But this preservation only makes sense when the visible content already matches the agent. If the
file panel's `_current_agent` was already updated to the new agent by some prior code path **without re-rendering**, the
on-screen content is for a different agent than `_current_agent` claims.

### 3. `set_file_list` early-returns when file lists happen to match

For DONE agents, `_update_display_impl` calls `file_panel.set_file_list(agent.all_files)`
(`src/sase/ace/tui/widgets/file_panel/__init__.py:178-221`). It clears `_current_agent = None` (good), then
early-returns when `files == self._file_list`. For two unrelated agents this rarely matches, but it does in real cases:

- Two `.plan` agents that share the same plan path in `extra_files` and have no `diff_path`.
- A `.plan` parent and its `.code` follow-up that propagate the same `extra_files`.
- A NO-CHANGES re-selection where `all_files == []` (the guard `and self._file_list` blocks the empty-list case, so this
  one is safe).

When the lists collide, `set_file_list` returns without re-displaying, and the previously rendered content (for the
previous agent) stays on screen.

### Why j → k fixes it

`j` moves selection to a _different_ identity, so the next `update_display` pass takes the "different agent" branch in
`_update_display_body` / `set_file_list` and does a full reset + re-render. `k` returns to the intended agent and again
hits the "different agent" branch (because the intermediate j step replaced `_current_agent`), forcing another full
reset + re-render. By the time the user is back on the original row, the display has been freshly drawn from the correct
source.

## Goals

- Toggling back to AUTO via `]` always shows the **current** selected agent's diff/files, with no stale-content window.
- Same fix path covers the symmetric `[` (reverse cycle) flow and any other caller that ends in AUTO mode after the file
  panel was hidden.
- No regressions to the user-facing trim state or `<ctrl+n>` / `<ctrl+p>` file selection across normal auto-refresh
  ticks (the original motivation for the early-return code paths).
- Behavior is covered by a regression test driven through the panel mixin / file panel layer, not just visual
  inspection.

## Non-Goals

- Refactor of the panel-mode state machine or the AUTO/THINKING/INFO cycle.
- Eliminating the file_panel diff cache or the same-agent fresh-cache fast path during ordinary auto-refresh — that fast
  path is necessary to avoid flicker on every tick.
- Touching the j/k debouncer or the two-phase immediate/debounced detail flow.

## Proposed Fix

The cleanest fix targets the _transition_ into AUTO rather than the steady state. Two complementary changes:

### A. Force file_panel re-render on AUTO transition

In `AgentDetail._apply_panel_mode` (the AUTO branch at `_agent_detail_panels.py:178-192`), before invoking
`self.update_display(agent)`, **invalidate the file panel's `_current_agent`** so the same-agent fast paths in both
`_update_display_body` and `set_file_list` are skipped on this one call.

Concretely, query the `AgentFilePanel` and assign `_current_agent = None` (and also clear `_file_list` so
`set_file_list` cannot collision-match — or pass an explicit `force=True` flag through `set_file_list` /
`update_display`). This guarantees the next dispatch follows the "different agent" / "no cache match" reset path, which
always re-renders.

The trim-preservation comment on the early return in `_update_display_body` stays accurate for steady-state auto-refresh
ticks; we only bypass it on the explicit visibility-restore transition, which is exactly when the user expects a fresh
view.

### B. Push fresh content while hidden, OR refresh on becoming visible

Pick one of:

- **B1 (preferred):** When `_panel_mode != AUTO`, still let `_update_display_impl` keep `file_panel`'s internal state
  (cache + agent ref) in sync — but mark the panel as "needs visual repaint on un-hide". Then, when the file panel
  transitions from hidden to visible, trigger a single repaint from the cache. Concretely, add a `_dirty` flag on
  `AgentFilePanel` set by `update_display` whenever the dispatch hits an early-return path while the scroll container
  has the `hidden` class, and consume it at the start of the AUTO branch in `_apply_panel_mode`.

- **B2 (smaller change):** Drop the AUTO-mode short-circuits in `_update_display_impl` so the file panel always sees the
  latest agent and decides for itself whether to re-render. This is closer to fix A alone but requires verifying the j/k
  debounced flow doesn't suddenly become more expensive when the panel is hidden (the file panel's own cache should
  still keep workers cheap).

Recommendation: ship **A** first (small, surgical, fixes the user-facing symptom immediately) and follow up with **B1**
if we observe related classes of staleness (e.g. on Tab switches that re-show the file panel).

## Affected Files

| File                                                     | Reason                                                                                                                                                                 |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/_agent_detail_panels.py`       | `_apply_panel_mode` AUTO branch — invalidate file panel state before `update_display`.                                                                                 |
| `src/sase/ace/tui/widgets/file_panel/__init__.py`        | (Optionally) accept a `force` flag on `update_display` / `set_file_list` so the AUTO transition can request a forced re-render without monkey-patching internal state. |
| `src/sase/ace/tui/widgets/agent_detail.py`               | (Only if option B is taken) revisit the early-returns in `_update_display_impl`.                                                                                       |
| `tests/ace/tui/test_panel_mode_cycle_refresh.py` _(new)_ | Regression test: simulate AUTO → THINKING → INFO → j/k → AUTO and assert the file panel re-renders for the new agent.                                                  |

## Test Plan

1. **New unit test** that drives `AgentDetail` through the cycle described in "Reproduction Sketch" using the existing
   test harness pattern (see `tests/ace/tui/test_file_panel_selection_preserved.py` and
   `tests/ace/tui/widgets/file_panel/test_diff_cache.py` for harness conventions). Assert that after the final AUTO
   toggle, the rendered content corresponds to the _current_ agent, not the prior one.

2. **Verify existing tests pass**: especially `test_file_panel_selection_preserved` (ensures the trim/index preservation
   behavior on auto-refresh isn't regressed) and the diff cache tests.

3. **Manual smoke test in TUI**: reproduce the original repro, confirm diff is correct after `]`. Spot-check that fast
   `]` toggles in steady state don't introduce flicker (since we're forcing a re-render only on the AUTO entry path, not
   on every cycle).

4. `just check` before submission per repo policy.

## Risks

- **Flicker on AUTO entry**: forcing a re-render means a brief moment of re-paint when the user toggles back. Acceptable
  trade-off — the panel is already transitioning from hidden to visible, so any paint is part of that transition.
- **Cache thrash**: the fix bypasses the fresh-cache fast path _only_ on AUTO-entry, not on the auto-refresh loop, so
  steady-state cost is unchanged.
- **Same-fix-needed in symmetric paths**: the `[` reverse cycle and any future caller of `_apply_panel_mode(AUTO, ...)`
  must also benefit. The fix lives inside `_apply_panel_mode` itself, which is the single funnel — so this is by
  construction covered.

## Out-of-Scope Followups

- Investigate whether `_has_file_content` checked synchronously at `_agent_detail_panels.py:188` after
  `self.update_display(agent)` is reading a stale value (the message hasn't been processed yet) — this could cause
  `_expand_prompt_only()` to incorrectly hide the panel in the no-content-was-previously-known edge case. Likely a
  separate small fix.
- Audit other call sites that may set `file_panel._current_agent` without triggering a paint, and consider centralizing
  this behind a single `set_current_agent(agent, *, paint=True/False)` helper.
