---
create_time: 2026-06-02 11:51:16
status: done
prompt: sdd/prompts/202606/project_management_active_filter_1.md
---
# Default Project Management Panel To Active Projects

## Objective

Change the ace TUI "Project Management" modal so opening the panel starts with the lifecycle state filter set to
`active` instead of `all`, while preserving access to archived, closed, and all projects through the existing Tab state
filter cycle.

## Current Behavior

`src/sase/ace/tui/modals/project_management_modal.py` initializes `self._state_filter` to `"all"` in
`ProjectManagementModal.__init__()`. `_load_records()` then calls
`list_project_records(root, "all", include_home=False)` and stores all non-home, non-system-managed project records in
`self._records`. `_apply_filters()` narrows `self._filtered_records` based on the current state filter and text filter.

This means the panel currently opens with active, archived, and closed projects visible. The summary correctly shows
counts for all loaded records, and Tab cycles state filters using `_STATE_FILTERS`.

## Proposed Behavior

Make the default visible state filter `active`. Keep the backing record load as `"all"` so the modal can still show
accurate lifecycle counts and switch to archived, closed, or all without another data-model change.

The user-visible result should be:

- Opening Project Management shows only active projects by default.
- The summary starts with `Filter: active` while still showing total active/archived/closed counts.
- Pressing Tab from the initial state advances to `archived`, then `closed`, then `all`, then back to `active`.
- Text search continues to apply inside the currently selected lifecycle state.
- Marked projects remain tracked by project name even when a filter hides them, matching the existing bulk-action model.

## Implementation Plan

1. In `src/sase/ace/tui/modals/project_management_modal.py`, introduce a local default constant such as
   `_DEFAULT_STATE_FILTER: ProjectStateFilter = "active"` or directly initialize `self._state_filter` to `"active"`. A
   constant is preferable because tests can assert the intended default without relying on a magic string.

2. Leave `_load_records()` loading all project records. This is important because `summary_text()` needs all lifecycle
   counts, stale mark pruning needs the full live project set, and filter cycling should not require reloading data just
   to reveal archived or closed projects.

3. Keep `_STATE_FILTERS` cycle compatibility. The current tuple `("all", "active", "archived", "closed")` already makes
   Tab from `active` move to `archived`, but consider reordering it to `("active", "archived", "closed", "all")` if
   readability matters. Either way, add tests for the initial cycle from the new default so the behavior is explicit.

4. Update modal filtering tests in `tests/ace/tui/modals/test_project_management_modal_filtering.py`:
   - Add or adjust an assertion that a fresh modal has `_state_filter == "active"`.
   - Assert the initial filtered rows include active non-system projects only.
   - Assert Tab reveals archived, closed, and all states in the intended order.
   - Assert the all-filter path remains available and still includes active, archived, and closed projects.

5. Update state/action tests whose old expectations depended on archived rows remaining visible under the all filter.
   For active-default behavior, archiving or closing the selected active row should normally remove it from the visible
   list. Tests should either assert that disappearance when it is the product-relevant behavior, or explicitly switch
   the modal to the all filter first when the test is about mutation mechanics rather than filter behavior.

6. Review mark, delete, and edit tests for implicit assumptions about visible row indexes. Most existing fixtures use
   active projects, so they should remain stable, but mixed-state fixtures may need to set the filter deliberately.

7. No backend/Rust core change is needed. This is TUI presentation state, and the existing lifecycle backend already
   exposes all states.

8. No keymap/default config change is expected. The Tab state-filter binding remains the same, and the footer/help text
   describes the action rather than a default value. Still audit the help/footer text while implementing; update it only
   if it contains stale default-filter wording.

## Verification Plan

Run focused tests first:

```bash
python -m pytest tests/ace/tui/modals/test_project_management_modal_filtering.py
python -m pytest tests/ace/tui/modals/test_project_management_modal_states.py
python -m pytest tests/ace/tui/modals/test_project_management_modal_marks.py
python -m pytest tests/ace/tui/modals/test_project_management_modal_delete.py
python -m pytest tests/ace/tui/modals/test_project_management_modal_edit.py
```

After source changes, run the repository check required by project instructions:

```bash
just check
```

If dependencies are stale in the ephemeral workspace, run `just install` first as the project memory recommends.
