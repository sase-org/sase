---
create_time: 2026-05-06 01:47:23
status: done
---
# Remove Agent Row Tag Badge

## Goal

Agent rows in the Agents tab should stop rendering the user-managed tag name inline (for example `@pinned`), because
tagged agents already live inside a panel whose border title is the tag (`@pinned · N`). Keep the underlying tag data
and all tag-driven behavior intact: panel routing, panel titles, tag editing, cleanup actions, jump targets, and cache
invalidation should continue to work exactly as they do today.

## Current Behavior

The Agents tab uses tag-driven side panels. `AgentPanelGroup` and `AgentPanelIndex` partition agents by effective tag,
and `_refresh_panel_widgets()` titles each panel as `(untagged) · N` or `@<tag> · N`.

Inside each row, `format_agent_option()` currently appends row decorations in this order after status/fold annotation:

1. Derived bead glyph (`◆`) when the agent maps to a bead.
2. User-managed tag badge (`@<tag>`) when `agent.tag` is set.
3. Agent name annotation (`@<agent_name>`) when present.

That makes tagged rows repeat the panel label. Recent bead cleanup already removed redundant bead ID text from this same
row surface, leaving only the glyph.

## Proposed Change

Remove only the inline user-managed tag badge append from agent row formatting:

- In `src/sase/ace/tui/widgets/_agent_list_render_agent.py`, delete the
  `if agent.tag: text.append(f" @{agent.tag}", ...)` rendering block.
- Keep `agent.tag` in the row render cache key for now. Even though the tag text will no longer be visible, tag changes
  still change panel membership and the surrounding list rebuild/highlight behavior. Leaving the cache key conservative
  avoids subtle stale-row risks and keeps this change scoped to presentation.
- Do not change panel titles, `AgentPanelGroup`, `AgentPanelIndex`, tagging persistence, cleanup modal labels, or detail
  panel/header rendering.

Expected row examples after the change:

- Tagged bead agent with fold annotation: `(RUNNING)×3 ◆ @sase-x.3`
- Tagged non-bead agent: no inline `@tag`; still renders the display name/status and any `@agent_name`
- Untagged agent: unchanged

## Test Updates

Update row-level assertions that currently expect inline tag text:

- Replace `test_tag_badge_renders_tag` in `tests/ace/tui/widgets/test_agent_list_bindings.py` with a regression that a
  tagged agent does not render `@release-blockers` in the row prompt.
- Keep/adjust the untagged no-`@` regression so it still verifies a plain agent without `agent_name` does not show an
  annotation.
- Update `TestAgentListBeadBadge.test_bead_badge_renders_between_fold_annotation_and_tag` in
  `tests/ace/tui/widgets/test_agent_display.py` to assert the bead glyph now flows directly into `@agent_name`, e.g.
  `(RUNNING)×3 ◆ @sase-x.3`, and that `@pinned` is absent.

Panel-title tests in `tests/ace/tui/test_agent_panel_titles.py` should remain unchanged; they are the positive coverage
that the tag remains visible at the panel level.

## Verification

Because this workspace may have an old editable install, run:

1. `just install`
2. Focused tests:
   - `.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_list_bindings.py tests/ace/tui/widgets/test_agent_display.py tests/ace/tui/widgets/test_agent_render_cache.py tests/ace/tui/test_agent_panel_titles.py`
3. Required full repo check after implementation changes:
   - `just check`

## Risks And Non-Goals

- This should be a presentation-only TUI change. No Rust core changes are needed.
- Do not remove tags from agent models or persistence; that would break panel grouping and tag workflows.
- Do not remove `agent.tag` from cache keys unless a broader cache audit proves it is safe. The rendering win is not
  worth increasing cache invalidation risk in this narrow change.
- Agent detail panels may still show names/bead metadata as before; this plan only concerns the left-side agent entry
  row.
