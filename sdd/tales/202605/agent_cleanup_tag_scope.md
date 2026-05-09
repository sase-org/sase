---
create_time: 2026-05-08 22:04:50
status: done
prompt: sdd/prompts/202605/agent_cleanup_tag_scope.md
---
# Agent Cleanup Tag Scope Plan

## Problem

The `X` Agent Cleanup panel's `Choose tag` flow is showing tag rows and preview counts for agents that are not currently
present on the Agents tab. In the reported snapshot, the Agents tab currently shows only a small set of tag panels, but
the cleanup-by-tag modal includes older persisted tags and large counts from outside the current tab state.

## Root Cause

The tag cleanup flow mixes current UI scope with broader cached/persisted state:

- `_known_agent_cleanup_tags()` in `src/sase/ace/tui/actions/agents/_kill_action.py` reads tags from `self._agents`,
  then also merges persisted `load_agent_tags()` values. Persisted tags can outlive any currently visible Agents-tab
  rows, so they become stale choices.
- `_open_tag_cleanup_selector()` passes `list(self._agents_with_children)` into `AgentCleanupTagModal`. That list is the
  broader cached agent list, not the currently filtered/folded Agents-tab list.
- `_present_tag_cleanup()` ultimately routes through `_present_planned_cleanup()`, which also plans against
  `self._agents_with_children`, so even if the modal list were filtered, the final confirmation/action could still
  include agents outside the current Agents tab.

The core cleanup planner is not the source of the bug; it correctly plans against the targets supplied by the TUI.

## Desired Behavior

For `Choose tag`:

- Show only tags that are present in the current Agents-tab agent set.
- Preview and act only on agents in the current Agents-tab scope.
- Preserve workflow-child cascade behavior for visible workflow parents by allowing hidden child rows from the cached
  child list only when their parent is in the current Agents-tab set.

## Implementation Plan

1. Add a small TUI-scoped helper in `AgentKillMixin` that returns cleanup targets for the current Agents-tab scope:
   - Start from `self._agents`, which is already the current post-filter Agents-tab list.
   - Add workflow children from `self._agents_with_children` only when their parent timestamp belongs to a current
     non-child workflow parent.
   - De-duplicate by agent identity.

2. Change `_known_agent_cleanup_tags()` to derive tags only from the current Agents-tab list:
   - Use the same effective tag logic as tag panels (`effective_tag_per_agent`) so workflow children inherit parent tags
     consistently.
   - Remove persisted `load_agent_tags()` from this path.

3. Change the tag selector and final tag cleanup planning to use the current-scope helper:
   - `AgentCleanupTagModal(tags=..., targets=...)` should receive current-scope targets.
   - `_present_tag_cleanup()` should pass current-scope targets through to `_present_planned_cleanup()`.
   - Keep existing custom-selection behavior unchanged unless tests reveal the same bug there.

4. Add focused tests:
   - Tag discovery excludes persisted/stale tags not present in current `self._agents`.
   - Tag modal preview counts ignore same-tag agents that exist only in `_agents_with_children`.
   - Final tag cleanup confirmation ignores same-tag agents outside the current Agents-tab scope.
   - Workflow child cascade remains available for a current visible workflow parent.

5. Run targeted tests first, then the repo check required by project memory:
   - `pytest tests/ace/tui/test_agent_cleanup_modal.py tests/ace/tui/test_panel_scoped_bulk.py`
   - `just install`
   - `just check`
