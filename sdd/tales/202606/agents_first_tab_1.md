---
create_time: 2026-06-30 08:55:46
status: done
prompt: sdd/prompts/202606/agents_first_tab_1.md
---
# Agents First Tab Plan

## Goal

Move the Agents tab from the second position to the first position in the ACE TUI tab list. The behavior should be
coherent across:

- the visible top-bar tab order,
- click hit ranges in the tab bar,
- Tab and Shift-Tab keyboard cycling,
- tests that pin tab order or navigation behavior.

Startup selection should remain unchanged: `AceApp` already defaults to the Agents tab.

## Current Findings

- `src/sase/ace/tui/widgets/tab_bar.py` owns the visible tab labels through `_TAB_LABELS`, currently ordered as `PRs`,
  `Agents`, `AXE`.
- `src/sase/ace/tui/actions/navigation/_basic.py` hard-codes keyboard cycling as
  `changespecs -> agents -> axe -> changespecs` and the reverse direction.
- `AceApp.__init__` already defaults `initial_tab` to `"agents"`, and `actions/_state_init.py` applies that before first
  paint. The requested change is therefore order, not startup focus.
- `TabBar` has its own unmounted default current tab of `"changespecs"`, but the mounted app calls
  `tab_bar.update_tab(self.current_tab)`. If the tab list is made Agents-first, that widget default should be reviewed
  for consistency.
- `src/sase/ace/tui/commands/_tabs.py` defines command applicability scopes such as
  `ALL_TABS = ("changespecs", "agents", "axe")`. Those are not necessarily UI ordering and should not be changed unless
  an implementation pass finds they drive user-visible tab order.
- `memory/tui_perf.md` says TUI navigation changes must avoid adding synchronous work, new refresh paths, or expensive
  rebuilds on the event loop. This tab-order change can stay purely in-memory.

## Proposed Approach

1. Introduce or reuse a single UI tab-order source of truth.
   - Preferred shape: a small shared constant/helper in the TUI layer, for example
     `TAB_ORDER = ("agents", "changespecs", "axe")`.
   - Keep this separate from command-scope constants unless those scopes are confirmed to represent visible tab order.
   - Consider a helper for next/previous tab calculation so keyboard cycling cannot drift from the rendered order again.

2. Update the tab bar rendering.
   - Reorder the visible labels to `Agents`, `PRs`, `AXE`.
   - Ensure click ranges are built from the new order and still map to the right tab names.
   - Align `TabBar`'s default `_current_tab` with the app default or the first UI tab if that keeps standalone widget
     behavior less surprising.

3. Update keyboard tab cycling.
   - `action_next_tab` should follow `agents -> changespecs -> axe -> agents`.
   - `action_prev_tab` should follow `agents <- changespecs <- axe <- agents`.
   - Preserve the existing Agents-tab special case where `next_tab` first focuses a live tracked artifact pane and stays
     on Agents when that focus succeeds.
   - Preserve per-tab index saving and restoration through the existing `_save_current_tab_position()` and
     `_get_clamped_*_idx()` paths.

4. Update focused tests.
   - Add or update a `TabBar` test that asserts the plain label order is `Agents`, `PRs`, `AXE`.
   - Update `tests/ace/tui/test_artifact_pane_tab_navigation.py` so it asserts the new keyboard cycle, including:
     - Agents with live artifact pane focus stays on Agents,
     - Agents without artifact pane focus moves to PRs,
     - PRs moves to AXE on next tab,
     - reverse cycling follows the same new order.
   - Keep `tests/ace/tui/test_app_title.py` asserting the default initial tab is Agents.
   - Update comments in perf/bench tests if they describe the old cycle, without changing benchmark intent.

5. Verify.
   - Run focused tests for tab bar and navigation first.
   - Because this repo requires it after code changes, run `just install` if needed, then `just check`.
   - If any visual snapshot test fails due only to top-bar tab order, inspect the generated artifacts before deciding
     whether snapshots need updating.

## Risks And Guards

- Risk: changing only the visible tab order would leave keyboard navigation inconsistent. Guard by sharing or testing
  the order used by both rendering and actions.
- Risk: changing broad command-scope tuples could cause unrelated command catalog churn. Guard by limiting changes to UI
  tab ordering unless a direct dependency is found.
- Risk: startup behavior could accidentally shift back to PRs. Guard by keeping the existing `AceApp` default and test.
- Risk: event-loop responsiveness regressions. Guard by keeping this as a static ordering/navigation change with no I/O,
  subprocess, or refresh-path additions.
