---
create_time: 2026-04-29 20:21:25
status: done
prompt: sdd/prompts/202604/apostrophe_jump_fallback.md
---
# Apostrophe Jump Fallback Plan

## Goal

When one-key jump mode is active, pressing the special apostrophe key currently jumps back to the last entry jumped
from. If there is no saved jump origin, it exits jump mode without moving. Change that no-history case so apostrophe
behaves like selecting hint `1`.

## Current Behavior

- `jump_to_entry` is bound to `apostrophe` in `src/sase/default_config.yml`.
- `AdvancedNavigationMixin._handle_entry_jump_key()` handles jump-mode input.
- When key `apostrophe` is pressed:
  - agents tab attempts `_restore_agents_jump_anchor()`, then exits even if no anchor exists.
  - changespecs/axe tabs read `_entry_jump_last_index[current_tab]`, then exit even if no saved index exists.
- Normal hint dispatch for key `1` already handles all target types:
  - agents and collapsed agent banners,
  - changespecs and collapsed changespec banners,
  - generic index-based tabs such as AXE.

## Implementation Approach

1. Keep the existing back-jump behavior unchanged when a saved origin exists.
2. In the apostrophe branch, when no saved origin exists, rewrite the dispatch key to `"1"` and continue through the
   existing normal hint handling instead of returning early.
3. Rely on the existing per-tab hint maps for safety. If hint `1` is somehow absent, the existing invalid-hint path will
   exit jump mode cleanly.
4. Update the jump footer so the apostrophe affordance remains visible in jump mode:
   - show `'<back>` semantics when history exists,
   - show apostrophe as a first-entry shortcut when no history exists.
5. Add focused regression tests:
   - changespec tab: apostrophe with no last jump selects hint `1` and records the previous position for the next back
     jump.
   - agents tab: apostrophe with no last jump selects the first visible target through the existing agent/banner
     dispatch.
   - optional footer assertion if the display helper has a low-friction existing test path.

## Verification

- Run the focused jump tests:
  - `pytest tests/ace/tui/test_jump_to_entry_hints.py tests/ace/tui/test_jump_hints_for_folded_banners.py`
- Because this repo memory requires it after edits, run:
  - `just install`
  - `just check`
