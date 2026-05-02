---
create_time: 2026-04-27 13:51:32
status: done
prompt: sdd/prompts/202604/agent_tag_panel_move.md
---
# Plan: Immediate Agent Panel Move After Tagging

## Context

In the Agents tab, `N` opens the agent tag modal. When marks exist, the action targets the marked set; otherwise it
targets the focused agent. The current tag application path persists the tag, mutates each affected `Agent.tag`, and
then calls `_refresh_agents_display(list_changed=True)`.

Two user-visible problems follow from this path:

1. Agents and workflow entries do not immediately move to their new tag panel.
2. Marked agents remain marked after the tag move completes.

The panel delay is likely caused by cache invalidation, not persistence. `AgentDisplayMixin._agent_panel_index()` caches
`AgentPanelIndex` by `self._agents` list identity. Tagging mutates `Agent.tag` in place, so the `_agents` list object
remains the same. The immediate full refresh therefore reuses stale `keys_per_agent`, stale panel slices, and stale
panel membership. A later loader refresh replaces the list object from disk, which naturally invalidates the cache and
makes the panels catch up a few seconds later.

The retained marks are straightforward: `AgentTaggingMixin._apply_agent_tag_change()` never removes the successfully
affected identities from `_marked_agents`.

## Implementation Plan

1. Add an explicit panel-cache invalidation hook for in-place agent mutations.
   - Prefer a small method on `AgentDisplayMixin`, for example `_invalidate_agent_panel_cache()`.
   - It should clear `_agent_panel_index_cache`, `_panel_keys_cache`, and `_nav_stops_cache` if present.
   - This keeps cache ownership near the display/cache code and avoids reaching into multiple private attributes ad hoc
     from tagging.

2. Call the invalidation hook from `AgentTaggingMixin._apply_agent_tag_change()` whenever the method has applied tag
   results to agent objects.
   - The hook should run before `_refresh_agents_display(list_changed=True)`.
   - This makes `_sync_panel_group()` and `_refresh_panel_widgets()` recompute panel keys from the newly mutated
     `Agent.tag` values in the same UI turn.
   - Because workflow children inherit their parent panel key through `agent_panels.py`, invalidating the panel index
     should also move visible workflow children immediately when their parent agent is tagged.

3. Clear marks for agents moved by a successful bulk tag operation.
   - After a tag write succeeds and before refreshing the display, remove the affected identities from `_marked_agents`.
   - Scope this to identities in `affected`, not an unconditional full mark clear, so unrelated marks are not lost if
     the action is ever reused with a subset.
   - If no tag state changed, keep existing behavior conservative and leave marks alone because no move happened.
   - If the tag file write fails, do not clear marks; the persistent state did not change.

4. Add focused tests around the regression.
   - Extend `tests/ace/tui/test_agent_tagging.py` so its fake app exposes cache fields and records invalidation/refresh
     calls.
   - Add a test proving bulk tag success removes the affected identities from `_marked_agents`.
   - Add a test proving cache invalidation happens before the refresh call. This catches the immediate-panel-move
     regression without needing a full Textual integration test.
   - Optionally add a display-level unit test if the existing fake display app can cheaply prove that stale
     `_agent_panel_index_cache` blocks panel moves and invalidation fixes it.

5. Verify with targeted tests, then repo checks.
   - Run `just install` first if needed for this workspace.
   - Run the targeted tests: `pytest tests/ace/tui/test_agent_tagging.py`.
   - Run the broader relevant tests if targeted coverage suggests display-cache risk:
     `pytest tests/ace/tui/test_agent_panels_display.py tests/ace/tui/test_agent_marking.py`.
   - Run `just check` before finishing, per repo memory.

## Expected Outcome

After tagging marked agents with `N`, the agents and inherited workflow entries should move to the destination tag panel
during the immediate refresh, without waiting for the periodic loader. Agents affected by a successful tag move should
no longer display as marked in their new panel.
