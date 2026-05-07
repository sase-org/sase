---
create_time: 2026-05-07 14:50:00
status: wip
prompt: sdd/prompts/202605/agent_cleanup_tag_picker.md
---
# Plan: Limit Agent Cleanup Tag Picker To Visible Agents-Tab Tags

## Problem

On the `sase ace` Agents tab, pressing `X` opens the agent cleanup panel and pressing `t` opens a tag-target picker for
kill/dismiss cleanup. The picker currently shows tags that are not represented by any currently displayed Agents-tab row
or tag panel. This happens because `_known_agent_cleanup_tags()` includes persisted values from
`~/.sase/agent_tags.json` in addition to tags on loaded agents, so stale historical tags remain selectable.

## Desired Behavior

The cleanup tag picker should list only tags used by at least one agent currently represented on the Agents tab. In
split-panel mode, this should match the tag panels users can see. Workflow children should follow the same effective-tag
behavior as the panel model: if a child inherits its parent tag for panel placement, that inherited tag counts as
represented.

## Implementation Approach

1. Change `AgentKillMixin._known_agent_cleanup_tags()` to derive tags from the current Agents-tab agent list instead of
   persisted tag storage.
   - Use the existing panel model helper `effective_tag_per_agent(self._agents)` so the cleanup panel and rendered
     panels share the same definition of tag representation.
   - Filter out `None` and return a case-insensitive sorted tuple.
   - Do not call `load_agent_tags()` here; persisted tags remain useful for tagging autocomplete, but they should not
     drive cleanup scope choices.

2. Keep tag-scoped cleanup execution unchanged.
   - `_open_tag_cleanup_selector()` should still pass the resulting tags to `AgentCleanupTagModal`.
   - `_present_tag_cleanup()` should still use `CLEANUP_SCOPE_TAG` against `self._agents_with_children` so cleanup
     behavior stays planner-backed and keeps existing cascade/side-effect semantics.

3. Keep the modal defensive behavior.
   - `AgentCleanupTagModal` can continue disabling rows with empty cleanup plans. After filtering, those rows should
     rarely exist, but keeping the guard protects against racey refreshes or direct construction in tests.

4. Update tests around the action mixin.
   - Add coverage that stale persisted tags are ignored by `_known_agent_cleanup_tags()`.
   - Add coverage that workflow children inherit parent tags for tag availability, matching the visible panel model.
   - Add coverage that the cleanup panel `tag_count` follows the same filtered tag set.

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/test_panel_scoped_bulk.py tests/ace/tui/test_agent_cleanup_modal.py
```

Because this repo asks for full validation after code changes, run:

```bash
just install
just check
```

## Risks

The main risk is accidentally removing useful tag autocomplete behavior. This plan only changes the cleanup action's
tag-source method, not the tagging modal path, so autocomplete can continue using persisted store tags where that
behavior is intended.
