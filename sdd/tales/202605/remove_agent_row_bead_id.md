---
create_time: 2026-05-06 01:27:59
status: done
---
# Remove Redundant Agent Row Bead ID

## Goal

Remove the bead ID text that appears next to the bead indicator on each agent entry in the Agents tab. Keep the bead
indicator itself so bead-launched agents remain visually recognizable, but avoid repeating the ID because bead-work
agents are already named after the bead.

## Context

The Agents tab row rendering is presentation-only TUI code. The relevant path is:

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
- `src/sase/ace/tui/widgets/_agent_list_styling.py`
- `tests/ace/tui/widgets/test_agent_display.py`

Current row behavior derives a bead ID from `agent.agent_name`, appends the bead glyph, then appends the bead ID text.
The row later appends `@{agent.agent_name}`, so for normal bead-work agents the same identifier is shown twice.

Detail-panel metadata is separate:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
- `src/sase/ace/tui/models/agent_bead.py`
- `src/sase/agent/bead_display.py`

Those paths should not change. They still provide useful detail-header context and description lookup.

## Plan

1. Update the Agents-tab row renderer to render only the bead glyph when a bead ID can be derived.
   - Keep the existing `derive_agent_bead_id(agent)` check so ordinary named agents do not get the glyph.
   - Remove only the appended bead ID text from the list-row badge.
   - Leave the later `@agent_name` annotation unchanged.

2. Clean up styling imports/constants if they become unused.
   - `_BEAD_TEXT_STYLE` should be removed if no row-rendering code uses it after the change.
   - `_BEAD_GLYPH` and `_BEAD_GLYPH_STYLE` stay.

3. Update row-rendering regression tests.
   - Bead phase, land, exact epic, and dismissed-agent row tests should assert glyph-only badge output.
   - Ordinary named agents should still omit the glyph.
   - The ordering test should assert the glyph remains between fold annotation and tag, without the bead ID text.

4. Leave cache behavior conservative.
   - The render cache can keep `derive_agent_bead_id(agent)` in the key because the presence/absence of a bead-derived
     badge still affects visible output.
   - Existing cache tests that assert key changes across bead-derived names remain valid.

5. Verify.
   - Run the focused tests for agent display and render cache.
   - Because this repo requires it after changes, run `just check` before reporting completion.
