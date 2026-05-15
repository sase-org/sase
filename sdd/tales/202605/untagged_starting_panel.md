---
create_time: 2026-05-15 10:40:10
status: done
prompt: sdd/prompts/202605/untagged_starting_panel.md
---
# Fix Untagged Panel Visibility for Starting Agents

## Problem

The Agents tab can show the `(untagged)` panel even when that panel has no rendered rows. This happens because panel-key
selection currently treats any `STARTING` agent as a reason to include the untagged panel, even though `STARTING` agents
are filtered out of rendered panel slices.

That creates an empty untagged panel when the only untagged evidence is a hidden pre-run row, including cases where the
hidden row actually has a tag and will belong to another panel once it becomes renderable.

## Scope

This is TUI presentation logic. It should stay in this repo and does not need a Rust core/backend change.

## Approach

1. Update `src/sase/ace/tui/models/agent_panels.py` so `_panel_keys_for()` derives `has_untagged` only from agents that
   pass `agent_is_rendered_in_agents_panel()`.
2. Keep tag-panel discovery based on rendered agents only, using the existing workflow-parent inheritance through
   `_panel_key_for_agent()`.
3. Preserve the current truly-empty Agents tab fallback panel for `agents == []`, but avoid treating non-empty
   all-starting lists as having an untagged rendered panel. If the implementation reveals a caller that requires at
   least one panel, handle that explicitly rather than reintroducing the STARTING shortcut.
4. Update focused tests in `tests/ace/tui/models/test_agent_panels.py` and `tests/ace/tui/test_agent_panel_titles.py`:
   - starting-only agents do not create tag or untagged rendered panels;
   - a tagged rendered row plus any starting row shows only the tagged panel;
   - a rendered untagged row still shows the untagged panel;
   - panel titles no longer include an empty `(untagged) · 0` panel for hidden starting agents.
5. Run targeted tests for agent panel model/title behavior first, then run the required repo check sequence:
   `just install` followed by `just check`.

## Expected Result

The starting count can still appear in the info panel, but it no longer causes an empty untagged agent panel. The
untagged panel appears only for the empty initial fallback or when at least one rendered row actually maps to the
untagged panel.
