---
create_time: 2026-04-27 08:50:16
status: done
prompt: sdd/prompts/202604/jk_banner_highlight_refresh.md
---
# Plan: Refresh Agent-List Highlight on j/k Navigation Across Folded-Group Banners

## Background and Bug Statement

On the Agents tab, the side-panel's selectable rows include both visible agent rows and banner rows for collapsed
(folded) groups. Pressing `j` / `k` is intended to walk through every such stop in tree order, regardless of how many
groups are folded.

The walk itself is correct (`_panel_navigation_stops` in `src/sase/ace/tui/actions/agents/_core.py:144-187` enumerates
banner+agent stops in render order, and `_navigate_agents_panel` in
`src/sase/ace/tui/actions/navigation/_basic.py:15-54` cycles through them). But the highlight in the rendered widget
only moves when the agents-display _refresh_ runs, and the refresh only runs when `current_idx` actually changes value:

- `current_idx` is a property on `AceApp` (`src/sase/ace/tui/app.py:130-144`); its setter calls `watch_current_idx` only
  when `old != value`.
- `watch_current_idx` (`src/sase/ace/tui/app.py:262-272`) is the sole caller of `_refresh_agents_display_debounced` on
  the agents tab.
- `_current_group_key` is a **plain attribute** (declared in `src/sase/ace/tui/actions/agents/_panels.py:24,54` and
  initialized in `src/sase/ace/tui/actions/startup.py:232`). Writing to it does not run any watcher.

In `_navigate_agents_panel`, when the new stop is a banner the code only mutates `_current_group_key` — `current_idx` is
intentionally left at the previously selected agent. As a result no refresh is fired and the rendered highlight stays on
the previous row.

This explains the user's symptom exactly:

- All groups unfolded → every stop in `_panel_navigation_stops` is `("agent", idx)` → `current_idx` always changes
  between stops → watcher fires → highlight moves. ✅
- One or more groups folded → some stops are `("banner", key)` → `current_idx` does not change → no watcher → highlight
  does not move. ❌

Failure sub-cases:

1. `agent → banner`: only `_current_group_key` is set; no refresh.
2. `banner → banner` (adjacent folded groups): only `_current_group_key` flips; no refresh.
3. `banner → agent` where the new agent index happens to equal the prior `current_idx`: the setter's `old != value`
   short-circuits the watcher; no refresh.

The downstream highlight code is already correct — `AgentList.update_highlight`
(`src/sase/ace/tui/widgets/agent_list.py:343-378`) prefers a banner search keyed by `group_key` and only falls through
to the agent-row search when no banner matches; collapsed banners are populated into `self._banner_at_row` at
`src/sase/ace/tui/widgets/agent_list.py:293-294`. And `_refresh_panel_highlights`
(`src/sase/ace/tui/actions/agents/_display.py:461-490`) already passes `group_key=self._current_group_key`. The only
missing piece is _triggering_ the refresh.

## Design

### Constraint: do not refactor `_current_group_key` into a reactive

`_current_group_key` is set in many places that are part of larger batch operations that already drive their own refresh
— `actions/agents/_folding.py` (multiple sites including 142, 152, 156, 232, 238, 242, 286, 298, 352),
`actions/agents/_grouping.py:90`, `actions/agents/_panels.py:54`, `actions/event_handlers.py:373`. Promoting the field
to a property/reactive that auto-fires a refresh would risk redundant refreshes and ordering hazards in those flows.
Keep the fix localized to the navigation path that's actually broken.

### Fix: explicit refresh in `_navigate_agents_panel`

Snapshot `(current_idx, _current_group_key)` before mutation, perform the existing mutation, then explicitly call
`_refresh_agents_display_debounced()` only when the `current_idx` setter would not already have fired it — i.e. when
`current_idx` did not change but the state did change.

Concretely, the condition for a manual refresh is:

```python
self.current_idx == old_idx and self._current_group_key != old_key
```

This handles all three failure sub-cases (agent→banner, banner→banner, banner→agent-with-equal-idx) without
double-firing in the common agent→agent case where the setter's watcher already fires the refresh.

### Patch

File: `src/sase/ace/tui/actions/navigation/_basic.py`

Replace the existing body of `_navigate_agents_panel` (lines 15-54) with the version below. The change:

1. Snapshots `old_idx` and `old_key` before mutation (the existing `cur_idx` / `cur_key` are reused from the snapshot
   since they are read before any mutation).
2. After mutation, explicitly calls `_refresh_agents_display_debounced()` when the `current_idx` setter would not have
   triggered it.

```python
def _navigate_agents_panel(self, direction: int) -> None:
    """Navigate within the agents panel.

    Walks the same row sequence the renderer is showing: cycles
    through every selectable stop (collapsed banners + visible
    agents) in tree order so the user can step in and out of
    collapsed groups with ``j`` / ``k`` regardless of how many
    groups are folded.

    Args:
        direction: +1 for next, -1 for previous.
    """
    stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
    if not stops:
        return
    old_key = self._current_group_key
    old_idx = self.current_idx
    pos: int | None = None
    # Prefer a banner match when the user is explicitly focused on
    # one; otherwise fall through to an agent match by current_idx.
    if old_key is not None:
        for i, (kind, payload) in enumerate(stops):
            if kind == "banner" and payload == old_key:
                pos = i
                break
    if pos is None:
        for i, (kind, payload) in enumerate(stops):
            if kind == "agent" and payload == old_idx:
                pos = i
                break
    if pos is None:
        new_pos = 0 if direction > 0 else len(stops) - 1
    else:
        new_pos = (pos + direction) % len(stops)
    kind, payload = stops[new_pos]
    if kind == "banner":
        self._current_group_key = payload
    else:
        self._current_group_key = None
        self.current_idx = payload
    # The ``current_idx`` setter only fires ``watch_current_idx``
    # (the refresh trigger) when the index actually changes.
    # Banner-targeted stops leave ``current_idx`` untouched, and
    # banner→agent transitions can land on the same index — in
    # both cases nothing fires a refresh, so the highlight stays
    # stale on the previously selected row.  Drive it explicitly
    # whenever only ``_current_group_key`` changed.
    if self.current_idx == old_idx and self._current_group_key != old_key:
        self._refresh_agents_display_debounced()  # type: ignore[attr-defined]
```

Notes:

- The `_refresh_agents_display_debounced` method lives on the agents-display mixin
  (`src/sase/ace/tui/actions/agents/_display.py:220-229`); other sites in `_basic.py` already call sibling-mixin methods
  through `# type: ignore[attr-defined]`, so the convention is consistent.
- The renamed locals `old_key` / `old_idx` (was `cur_key` / `cur_idx`) make the snapshot semantics explicit and align
  with how the setter+watcher pattern is described elsewhere in the codebase.

## Test Plan

### Manual TUI repro (primary verification)

1. `just install` in the workspace.
2. Launch `sase ace` against a project with multiple agent groups.
3. Collapse at least two adjacent groups (and ideally one at the start and one at the end so cycle-wrap is exercised).
4. Press `j` / `k` repeatedly through the side panel.
5. Expected: the highlight visibly lands on each collapsed-group banner as it is traversed, and on each visible agent
   row, with no apparent stalls or "skipped" frames. Across cycle boundaries (last → first) the highlight wraps cleanly.
6. Expand all groups (`zR` or equivalent) and re-verify j/k still moves the highlight one agent at a time (regression
   check that the agent→agent path still works without double refresh; visually it should be identical to today).

### Unit test (regression guard)

The existing harness in `tests/ace/tui/test_agent_jk_navigation.py` exercises `_navigate_agents_panel` against a
`_StubApp` (no Textual app instance), which is why it never noticed the missing refresh. Extend the harness with a spy
and add focused tests for the three failure cases:

1. Add a `_refresh_agents_display_debounced` spy to `_StubApp` (count of calls).
2. New test `test_jk_banner_to_banner_refreshes_highlight`:
   - Build agents producing at least two adjacent collapsed banners.
   - Navigate from one banner to the next via `_navigate_agents_panel(1)`.
   - Assert `_current_group_key` changed AND `_refresh_agents_display_debounced` was called exactly once.
3. New test `test_jk_agent_to_banner_refreshes_highlight`:
   - Start on an agent, navigate to a stop that is a banner.
   - Assert `_current_group_key` is now the banner's key, `current_idx` unchanged, and the spy was called exactly once.
4. New test `test_jk_banner_to_agent_with_same_idx_refreshes_highlight`:
   - Construct the case where the banner stop is followed by an agent stop whose index equals the pre-navigation
     `current_idx`.
   - Navigate; assert `_current_group_key` cleared to `None` and the spy was called exactly once even though
     `current_idx` did not change.
5. New test `test_jk_agent_to_agent_does_not_double_refresh`:
   - All groups expanded; `current_idx` changes between distinct agents.
   - Assert the spy is **not** called by `_navigate_agents_panel` itself (in the harness the `current_idx` watcher is
     not wired, so any spy hit would be a duplicate from our manual call). This guards against a future regression that
     would double-fire the refresh.

The existing tests (lines 116-239) continue to pass unchanged — they only assert post-navigation `_current_group_key` /
`current_idx`, which are unaffected by the new refresh call.

### Whole-suite verification

Run `just check` in the workspace before reporting back to the user. It chains `lint` + `test` and is the gate required
by `memory/short/build_and_run.md`.

## Out of Scope

- Refactoring `_current_group_key` into a property or `reactive` — explicitly avoided per the constraint above.
- Changes to `update_highlight`, `_refresh_panel_highlights`, or banner-row population logic — these are already correct
  and verified.
- Changes to the click handler (`actions/event_handlers.py:373`) which also writes `_current_group_key` directly. Mouse
  selection visually highlights the clicked row through Textual's own OptionList event flow, so the missing-refresh
  symptom does not manifest there. If a related defect surfaces later it can be addressed in a follow-up.
