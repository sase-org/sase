---
create_time: 2026-05-07 00:42:04
status: done
prompt: sdd/prompts/202605/agent_row_unread_indicator.md
---
# Agent Row Unread Indicator Plan

## Goal

Add a tasteful unread indicator to Agents-tab rows when an agent completes, then remove that indicator the first time
the user selects that agent row.

## Product Design

- Render a compact, bright unread marker at the start of a completed agent row, after jump hints and before existing
  mark/approve/type/name adornments.
- Use a small gold sparkle-style glyph (`✦`) with bold warm-gold styling so it reads as "new result" without competing
  with the status color, group banners, tags, retry badges, or runtime suffixes.
- Do not mark the currently selected agent as unread when it completes. If the detail panel is already focused on that
  agent, the user has effectively seen it.
- Only agent rows get the marker. Group banners do not gain aggregate unread chips in this first implementation, because
  the request targets row entries and banner counts already carry other meaning.
- The marker is TUI-session state, not persisted across restarts. This matches "when agents complete" as an observed
  event and avoids introducing cross-frontend read-state semantics into the Rust core/backend boundary.

## Technical Design

- Add an app-level set, `_unread_completed_agent_ids`, keyed by `Agent.identity`.
- Detect newly completed agents inside the Agents-tab finalization pipeline by comparing the previous displayed agent
  list against the newly loaded list after fold/search/status filtering.
- Treat `DISMISSABLE_STATUSES` as completed for this UI purpose so both successful and failed terminal rows get the
  unread marker.
- Ignore workflow child rows for the first pass unless they are rendered as standalone agent rows; the primary
  completion signal is the visible row identity.
- Clear stale unread ids whenever their identities no longer appear in the loaded agent list.
- Clear one unread id when selection changes to that row through `on_agent_list_selection_changed`.
- Also clear when tab switching lands on a saved Agents-tab selection, so a row selected by restoring focus does not
  keep a stale unread badge.

## Rendering Changes

- Thread an `is_unread` boolean through:
  - `AgentList.update_list`
  - `_agent_list_build.build_list`
  - `format_agent_option` / `cached_format_agent_option`
  - `agent_render_key`
  - `AgentList.patch_agent_row`
- Include `is_unread` in the row render cache key so cached prompts do not leak old marker state.
- Store `is_unread` in `_row_render_ctx` so single-row patches can reproduce or clear the badge.

## Refresh/Patch Behavior

- On list rebuilds, pass the unread identity set from the display mixin into each panel's `AgentList.update_list`.
- On selection clear, try `_try_patch_agent_row(agent)` first so the badge disappears immediately without rebuilding the
  whole list.
- Fall back to `_refresh_agents_display(list_changed=True, defer_detail=True)` if the row cannot be patched safely.
- Keep this independent from notification unread/read state; the existing notification indicator and modal continue to
  behave as they do today.

## Tests

- Add widget-level rendering tests proving the marker appears only when `unread_agents` contains the agent identity and
  disappears when absent.
- Add cache-key coverage so toggling unread state changes rendered output.
- Add event-handler tests for clearing unread state on first Agents-tab row selection, including the "same current_idx,
  new row selected" case.
- Add finalization tests for marking a row unread on transition from non-terminal to terminal, not marking the currently
  selected row, and pruning unread ids for agents no longer present.

## Verification

- Run the targeted tests for agent list rendering, event-handler selection, and agent-list finalization.
- Run `just install` if needed, then `just check` before finishing, per repo memory.
