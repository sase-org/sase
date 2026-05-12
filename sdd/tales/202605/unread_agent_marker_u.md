---
create_time: 2026-05-12 09:47:51
status: wip
prompt: sdd/prompts/202605/unread_agent_marker_u.md
---
# Unread Agent Marker U Plan

## Goal

Replace the small mailbox glyph used in unread completed agent rows with a capital `U` badge that visually matches the
existing unread agent count highlight: black foreground on yellow background. The change should be scoped to Agents-tab
row rendering and should keep unread state behavior unchanged.

## Current Behavior

- Completed unread agent rows render the unread marker in the right-aligned runtime suffix.
- The marker is defined in `src/sase/ace/tui/widgets/_agent_list_render_layout.py` as
  `_RUNTIME_UNREAD_COMPLETED_MARKER = "📬 "`.
- Its current style is `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE = "#5FD7FF"`.
- The requested yellow/black highlight already exists for unread counts:
  - `src/sase/ace/tui/widgets/agent_info_panel.py` uses `bold #1a1a1a on #FFD700`.
  - `src/sase/ace/tui/actions/agents/_display_panels.py` uses the same style for compact panel metrics.
  - `src/sase/ace/tui/widgets/notification_indicator.py` uses the same black/yellow treatment for regular unread
    notification counts.
- Unit tests currently assert the mailbox glyph in runtime suffixes and cache invalidation tests.
- PNG coverage includes `tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_unread_highlight_png_snapshot`,
  backed by `tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png`.

## Design

Use a text marker instead of an emoji:

- Change `_RUNTIME_UNREAD_COMPLETED_MARKER` from `"📬 "` to `"U "`.
- Change `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE` to `bold #1a1a1a on #FFD700`, matching unread agent count styling.
- Keep the marker in the existing suffix slot so row structure, right alignment, and unread navigation semantics remain
  unchanged.
- Preserve the existing spacing rules:
  - Marker-only suffix should render as plain `"U"`, because the code strips trailing whitespace when no runtime exists.
  - Marker-with-elapsed suffix should render as `"U 15m"` or `"20:17:03 · U 6h17m"`.

## Implementation Steps

1. Update the unread completed runtime marker constants in `_agent_list_render_layout.py`.
2. Update focused unit tests that assert mailbox text:
   - `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
   - `tests/ace/tui/widgets/test_agent_render_cache.py`
3. Search for remaining `📬` references in source and tests and remove any stale expectations tied to agent unread row
   rendering.
4. Run the focused non-PNG tests for runtime rendering and render cache behavior.
5. Run the unread PNG snapshot test. Since this is an intentional visual change, regenerate only
   `agents_unread_highlight_120x40.png` if the focused visual test reports the expected drift, then re-run it without
   update mode.
6. Run the full PNG visual snapshot suite to satisfy the requirement that all PNG snapshot tests pass.
7. Run `just check` because this repo requires it after file changes, unless blocked by environment issues.

## Risks And Checks

- The `U` marker has different cell width from the emoji, so the unread row suffix alignment will shift. This is
  intended, but the PNG golden must be updated deliberately and only for the affected snapshot.
- Rich background styling may expose spacing differences around `U`. The existing suffix construction should keep the
  highlighted badge compact and consistent with count styling.
- The render cache key already includes `is_unread`, so the visual swap should not require cache key changes.
- This is presentation-only TUI behavior, so it should remain in this Python repo and does not cross the Rust core
  boundary.
