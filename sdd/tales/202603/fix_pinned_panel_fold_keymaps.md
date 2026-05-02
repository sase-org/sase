---
create_time: 2026-03-31 09:20:18
status: done
prompt: sdd/prompts/202603/fix_pinned_panel_fold_keymaps.md
---

# Fix Pinned Panel Fold Keymaps (`l`, `L`, `h`, `H`)

## Problem

When the Pinned panel is focused, pressing `l`/`L`/`h`/`H` to expand/collapse workflow sub-steps visually affects the
main (unpinned) panel instead of the pinned panel. The selected pinned workflow's children should appear in the pinned
panel, not the main panel.

## Root Cause

Two interrelated bugs:

### Bug 1: Workflow children of pinned parents are placed in the main panel

`_build_panel_indices()` in `_core.py:92-112` classifies each agent independently — checking if its OWN identity is in
`_pinned_agents`. Workflow children have different identities from their parent and are never individually added to
`_pinned_agents`, so they always land in the main panel even when their parent workflow is pinned.

When the user expands a pinned workflow (`l`), the fold state updates correctly, but the newly visible children get
routed to the main panel by `_build_panel_indices()`. The visual result: children appear in the main panel, making it
look like the main panel's agent was expanded instead.

### Bug 2: `L`/`H` (expand/collapse ALL) are not scoped to the focused panel

`_expand_all_folds()` and `_collapse_all_folds()` use `_get_all_workflow_keys()` which returns ALL workflow keys from
`_fold_counts`, affecting workflows in both panels regardless of which panel has focus.

## Plan

### Change 1: Route workflow children to their parent's panel (`_core.py`)

In `_build_panel_indices()`:

1. **Pre-pass**: Collect `raw_suffix` values of pinned parent workflows (identity in `_pinned_agents`, status in
   `DISMISSABLE_STATUSES`, not a workflow child, has `raw_suffix`).
2. **Classification loop**: Add an `elif` branch — if an agent `is_workflow_child` and its `parent_timestamp` is in the
   pinned parent suffix set, route it to the pinned panel.

### Change 2: Scope expand/collapse-all to focused panel (`_folding.py`)

1. Add `_get_focused_panel_workflow_keys()` helper — iterates `_active_panel_indices()`, collects unique workflow keys
   via `_get_workflow_key_for_agent()`.
2. Update `_expand_all_folds()` and `_collapse_all_folds()` to call the new helper instead of
   `_get_all_workflow_keys()`.
