---
create_time: 2026-03-30 16:22:18
status: done
---

# Move Pinned Agents/Workflows to Dedicated Bottom-Right Panel

## Goals

- Move pinned agent/workflow entries (currently pinned via `P`) out of the main Agents list and into a dedicated panel
  under the right-side agent/workflow detail area.
- Add a new Agents-tab keymap `J` to navigate focus/selection between the main list and the new pinned panel.
- Preserve and improve usability: clear focus indication, predictable keyboard behavior, and no regressions in
  pinning/dismissal actions.

## Product/UX Design

### 1) Layout and information hierarchy

- Keep top-level Agents layout structure intact (info bar + content row), but split right column vertically:
  - Top-right: existing agent/workflow detail panel (unchanged behavior).
  - Bottom-right: new "Pinned" panel showing pinned entries only.
- Keep left column as the primary active feed (non-pinned entries).
- Use visual styling to make panels feel cohesive:
  - Distinct border + title for pinned panel.
  - Active panel highlight state so users can immediately tell which list receives `j/k` navigation.

### 2) Keyboard model

- `P` remains the pin toggle for completed entries.
- New `J` (Agents tab) toggles focus between:
  - Main list (left) and
  - Pinned list (bottom-right).
- `j/k` navigate within the focused list only.
- Mouse/selection in either list should also update active focus.

### 3) Selection behavior

- Keep one canonical selected agent identity for actions/detail rendering.
- Maintain mapping between each panel’s local list index and global selected item.
- If current selection disappears after refresh:
  - Prefer restoring by identity;
  - Then fall back to panel-local nearest valid entry;
  - Then switch panels if needed to keep selection valid.
- If toggling pin/unpin moves an item across panels, keep selection coherent (and panel focus intuitive).

## Technical Design

### 1) Data model and state

- Continue storing full loaded agents in canonical `_agents` (global source of truth).
- Add derived panel index maps:
  - Main panel global indices
  - Pinned panel global indices
- Add focused-panel state (`main` vs `pinned`).
- Keep `current_idx` as global index into `_agents` to minimize cross-feature risk.
- Introduce helper methods to:
  - Build/sync panel index maps
  - Convert global <-> local indices
  - Resolve active panel list length/selection
  - Switch panel focus safely

### 2) Widget/event design

- Reuse `AgentList` widget for both panels.
- Extend `AgentList` messages to include panel identity (`main` or `pinned`) so event handlers can disambiguate
  selection/width events.
- Update app composition to mount second list in the right-bottom pinned container.

### 3) Navigation/action integration

- Update navigation mixin (`j/k`) on Agents tab to iterate only over the focused panel’s mapped indices.
- Implement new action for `J` to toggle panel focus.
- Ensure all existing actions that operate on selected agent continue to work using unchanged global `current_idx`
  semantics.

### 4) Keymap/config/help synchronization

- Add new app action keymap field for panel focus toggle:
  - `focus_pinned_panel: "J"` in `src/sase/default_config.yml`
  - Sync in keymap dataclass + binding metadata + default bindings fallback.
- Update help modal Agents-tab bindings to document the new `J` behavior.
- Update footer behavior to surface panel-switch affordance when relevant (at least when pinned entries exist).

### 5) Styling

- Add CSS for new bottom-right pinned container, title, and list.
- Add focus-state classes (active vs inactive) on both list containers with clear but non-jarring visual
  differentiation.
- Preserve responsiveness for narrow terminal widths.

## Reliability / Edge Cases

- No pinned entries:
  - Pinned panel remains visible but empty; `J` should no-op with a clear notification.
- Pinned list emptied while focused (e.g., unpin/dismiss):
  - Auto-fallback focus to main list.
- Startup on Agents tab with only pinned entries:
  - Focus should select pinned panel by default.
- Auto-refresh updates:
  - Preserve focused panel and selected identity where possible.
- Dismiss-all behavior:
  - Continue dismissing non-pinned completed entries globally, regardless of focused panel.

## Test Plan

- Keymap tests:
  - Validate new `focus_pinned_panel` action is fully wired and binding count updated.
- Widget/message tests:
  - Ensure panel-tagged selection events route correctly.
- Navigation tests (Agents tab):
  - `j/k` constrained to focused panel.
  - `J` toggles focus and selection as expected.
- Pinning workflow tests:
  - Pin moves item to pinned panel; unpin moves back.
  - Selection remains valid through refreshes.
- Dismiss behavior:
  - Dismiss-all ignores pinned entries across split panels.

## Execution Order

1. Add keymap action and docs/help surfaces.
2. Add app layout + styles for pinned panel.
3. Extend `AgentList` events with panel identity.
4. Implement panel index mapping/focus logic in agents core + navigation.
5. Wire event handlers and footer updates.
6. Add/update focused tests.
7. Run install/check cycle and fix any regressions.
