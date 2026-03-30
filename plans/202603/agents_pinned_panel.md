---
create_time: 2026-03-30 14:44:43
status: done
---

# Agents Tab Pinned Panel Redesign Plan

## Problem

Pinned agent/workflow entries currently stay mixed into the primary Agents list with only a pin icon marker. This makes
the list harder to scan and weakens the mental model of "pinned = set aside".

## Goals

- Move all pinned agent/workflow entries (from `P`) into a dedicated panel on the Agents tab.
- Place that panel on the bottom-right, below the existing agent/workflow detail panel.
- Add a new Agents-tab keymap `J` to jump between the main list and the pinned panel.
- Keep behavior intuitive, reliable, and visually cohesive with the existing ace TUI style.

## UX Design

1. Layout

- Keep the current left-side main agent/workflow list.
- Keep the current right-side detail panel as the primary panel.
- Add a new right-bottom panel titled `Pinned` below detail.
- Pinned panel shows only pinned entries; main list excludes them.

2. Navigation model

- `j/k` continues to move within the currently active list panel.
- `J` toggles active panel focus between main list and pinned panel.
- If pinned panel is empty, `J` keeps focus on main and shows a warning toast.
- Mouse selection in either list also sets focus to that panel.

3. Selection + detail behavior

- Detail panel always reflects the currently selected entry from the active panel.
- Existing entry actions (`x`, `P`, `r`, `e`, etc.) apply to selected entry in active panel.
- Unpinning an item in pinned panel removes it from that panel immediately; selection is clamped safely.

4. Visual design

- Use a dedicated bordered container for pinned entries with a compact title row.
- Active panel gets stronger border/accent treatment; inactive panel is subdued.
- Reuse existing AgentList visual language so both panels feel consistent.

## Technical Design

1. State model updates

- Introduce explicit Agents-tab panel state:
  - active panel: `main | pinned`
  - per-panel selected indices (main index, pinned index)
  - derived lists: `main_agents`, `pinned_agents`
- Keep `self._agents` as the active-panel list to minimize churn in existing action handlers.
- Keep a separate "all agents on tab" list for global counts/operations that must span both panels.

2. Agent list widget behavior

- Extend `AgentList` to support:
  - panel identity in `SelectionChanged` messages (`main` vs `pinned`)
  - optional width-change emission (disable for pinned panel)
- Reuse `AgentList` for pinned list (same rendering and selection semantics).

3. Compose/layout changes

- Update `AceApp.compose()` Agents layout:
  - left: existing `agent-list-panel`
  - right top: existing `agent-detail-panel`
  - right bottom: new pinned container + `pinned-agent-list-panel`

4. Refresh pipeline changes

- In `_load_agents()`:
  - load and filter as before
  - split final display set into pinned vs non-pinned
  - restore selection by identity where possible
  - clamp indices and active panel fallback safely
- In `_refresh_agents_display()`:
  - refresh both list widgets
  - refresh detail/footer from active-panel selection
  - refresh info panel with active panel context and counts

5. Input/keymap wiring

- Add new app action `jump_agent_panel` (or equivalent action name used consistently):
  - `bindings.py`
  - `keymaps/types.py` (`_BINDING_META`, `AppKeymaps`)
  - `src/sase/default_config.yml` default key `"J"`
- Implement `action_jump_agent_panel()` in agents interaction/navigation logic.
- Update agents help modal section to document the new key.
- Update keybinding footer to advertise this action when relevant.

6. Global operations that should use all agents

- Ensure these use the all-agents view, not only active-panel list:
  - dismiss-all completed agents
  - notification override scans/jump-to-notification fallback search
  - tab-bar aggregate running/done counts

## Reliability Constraints

- Selection and focus must stay valid across auto-refresh cycles and pin/unpin mutations.
- No crashes when one or both panels are empty.
- Preserve existing keyboard behavior on non-Agents tabs.
- Keep pinned persistence format unchanged (`pinned_agents.json`).

## Testing Plan

1. Keymap/config tests

- Verify new app keymap field is covered by defaults and binding metadata parity tests.
- Verify binding count updates accordingly.

2. Footer/help tests

- Verify agents footer includes panel-jump binding when pinned entries exist.
- Verify help modal agents section includes the new panel-jump key.

3. Agents behavior tests (new)

- Split behavior: pinned entries absent from main list and present in pinned panel.
- `J` toggles active panel and preserves per-panel selection.
- `J` with empty pinned panel leaves focus unchanged and warns.
- Unpin from pinned panel moves entry back to main list without invalid selection.

4. Smoke integration

- Existing navigation/action tests still pass (regression check for `j/k`, `P`, `x`, revive, etc.).

## Rollout Order

1. Add state + layout skeleton + new keymap action.
2. Add split-list refresh logic and focus switching.
3. Route selection events from both lists.
4. Patch global all-agent operations.
5. Update footer/help and styles.
6. Add/adjust tests.
7. Run full checks.
