---
create_time: 2026-05-09 10:54:01
status: done
prompt: sdd/prompts/202605/multi_tag_cleanup_selection.md
---
# Multi-Tag Agent Cleanup Selection Plan

## Goal

Add support for selecting more than one tag in the tag selection panel opened by pressing `t` from the `Agent Cleanup`
panel. The user should be able to mark several tag rows, preview the combined cleanup count, and confirm one cleanup
operation covering all agents in the current Agents-tab scope whose effective tag matches any selected tag.

## Current Behavior

- `AgentCleanupModal` routes `t` to `_open_tag_cleanup_selector()`.
- `_open_tag_cleanup_selector()` opens `AgentCleanupTagModal` with known tags from the current Agents-tab list and
  cleanup targets from `_agent_cleanup_current_scope_targets()`.
- `AgentCleanupTagModal` is currently single-select:
  - Each row previews the cleanup plan for one tag.
  - `enter` or option selection dismisses `AgentCleanupTagResult(tag=<single-tag>)`.
- `_present_tag_cleanup(tag)` builds a `CLEANUP_SCOPE_TAG` request and calls `_present_planned_cleanup()`.
- The Rust/Python cleanup wire supports a single `tag` field, but it already supports explicit identity cleanup through
  `CLEANUP_SCOPE_CUSTOM_SELECTION`.

## Design

Keep the backend cleanup contract unchanged. Multi-tag selection is a TUI affordance, and the final cleanup can be
represented as an explicit identity selection that the existing Rust-backed planner already understands.

### Modal UX

- Extend `AgentCleanupTagModal` with internal marked state, likely `self._marked_tags: set[str]`.
- Add bindings:
  - `space` and/or `m`: toggle the highlighted tag row.
  - `enter`: confirm all marked tags when any are marked; otherwise keep the current single-tag behavior for the
    highlighted row.
  - Existing `j/k`, arrows, `q`, and `escape` remain unchanged.
- Disabled rows remain disabled and cannot be marked. Attempting to toggle a disabled row should leave state unchanged
  and may update the hint text.
- Row labels should show an explicit marker such as `[x] @tag` / `[ ] @tag`, matching existing modal marking conventions
  such as `AgentArtifactSelectionModal`.
- The hint line should include the current marked count and combined preview totals when tags are marked.

### Result Shape

- Update `AgentCleanupTagResult` to carry multiple tags, for example:
  - `tags: tuple[str, ...]`
- Preserve the single-select caller path by returning a one-element tuple when the user presses `enter` on an unmarked
  highlighted tag.
- If helpful for compatibility during the edit, add a small `tag` property only for single-tag cases, but prefer
  updating the caller and tests to use `tags`.

### Combined Cleanup Planning

- Add a route in `AgentKillMixin` for multiple selected tags:
  - For one tag, the existing `CLEANUP_SCOPE_TAG` request can remain in place.
  - For multiple tags, compute a deterministic union of selected parent/live identities and present a
    `CLEANUP_SCOPE_CUSTOM_SELECTION` cleanup request.
- The union should be derived from planner results rather than ad hoc status filtering:
  - For each selected tag, run the existing single-tag plan against `_agent_cleanup_current_scope_targets()`.
  - Union `plan.selected_identities`, preserving first-seen order and deduping identities.
  - Build a custom-selection request with the union and `include_pidless_as_dismissable=True`.
- This preserves existing workflow-child cascade behavior because the planner receives parent identities and can cascade
  children through the normal custom-selection path.
- Use a confirmation header such as `Tags: @fix, @review` for multi-tag cleanup.

## Implementation Steps

1. Update `AgentCleanupTagResult` in `src/sase/ace/tui/modals/agent_cleanup_modal.py` to represent one or more tags.
2. Extend `AgentCleanupTagModal` with marked-tag state, mark/toggle bindings, row refresh helpers, and combined
   hint/summary rendering.
3. Keep disabled tag rows non-interactive for both direct selection and marking.
4. Update `_open_tag_cleanup_selector()` in `src/sase/ace/tui/actions/agents/_kill_action.py` so the dismiss callback
   passes `result.tags` to a new or updated presentation helper.
5. Update `_present_tag_cleanup()` or add `_present_tag_cleanup_for_tags()`:
   - Single tag: use the existing tag-scope request.
   - Multiple tags: create a deduped custom-selection request from the per-tag planner union.
6. Add focused tests in `tests/ace/tui/test_agent_cleanup_modal.py`:
   - Marking toggles row state and advances or preserves highlight in a predictable way.
   - Enter returns all marked tags.
   - Enter with no marks still returns the highlighted single tag.
   - Disabled empty tags cannot be marked or confirmed.
7. Add mixin-level tests in `tests/ace/tui/test_panel_scoped_bulk.py`:
   - Multi-tag confirmation includes agents from both selected tags.
   - Duplicate/cascaded workflow identities are not duplicated.
   - Out-of-scope same-tag agents remain excluded.
8. Run targeted tests first:
   - `pytest tests/ace/tui/test_agent_cleanup_modal.py tests/ace/tui/test_panel_scoped_bulk.py`
9. Because this repo requires it after code changes, run `just install` if the workspace is stale, then `just check`
   before final handoff.

## Risks and Tradeoffs

- A true multi-tag backend scope would require changing the Python wire, Rust wire, Rust planner, bindings, and parity
  tests. That is heavier than this request needs because the TUI can express the final target set through existing
  explicit identities.
- Computing the union from per-tag plans avoids duplicating cleanup eligibility rules in the TUI, but it means multi-tag
  cleanup semantics are "the union of selected tag-scope plans at confirmation time." That is the desired behavior and
  remains robust if cleanup eligibility changes in core.
- The modal should avoid using `t` for toggling because users reached this panel from a `t` action and existing
  tag-filter cycling in custom cleanup already uses `t`; `space`/`m` are clearer for marking.
