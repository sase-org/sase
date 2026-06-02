---
create_time: 2026-06-02 12:00:55
status: done
prompt: sdd/prompts/202606/project_management_shift_tab_filter.md
---
# Add Shift+Tab Reverse Filter Cycling To Project Management

## Objective

Add `<shift+tab>` support to the ace TUI Project Management modal so users can move to the previous lifecycle filter,
mirroring the existing `<tab>` behavior that moves to the next lifecycle filter.

## Current Behavior

`src/sase/ace/tui/modals/project_management_modal.py` defines a modal-local binding:

```python
Binding("tab", "cycle_state_filter", "Cycle State", priority=True)
```

`action_cycle_state_filter()` advances through `_STATE_FILTERS`, which is currently ordered as:

```python
("active", "archived", "closed", "all")
```

This means the panel opens on `active` and `<tab>` cycles forward through `archived`, `closed`, `all`, and back to
`active`. There is no matching modal binding for `shift+tab`, so Shift+Tab currently falls through to the app-level
`prev_tab` keybinding instead of changing the Project Management filter while the modal is open.

The visible footer currently says `Tab state`, so it only advertises the forward direction.

## Proposed Behavior

While the Project Management modal is open:

- `<tab>` continues to cycle forward: `active -> archived -> closed -> all -> active`.
- `<shift+tab>` cycles backward: `active -> all -> closed -> archived -> active`.
- The selected row, summary, detail panel, pending force state, and filtering behavior update exactly as they do after
  the existing forward cycle.
- The footer advertises both directions clearly enough for users to discover the reverse key.
- Global app tab switching remains unchanged outside this modal.

## Implementation Plan

1. Update `ProjectManagementModal.BINDINGS` in `src/sase/ace/tui/modals/project_management_modal.py` to add a
   modal-local `Binding("shift+tab", ...)` with `priority=True`. This should intentionally override the app-level
   previous-tab binding while the modal is active, just as the current modal-local Tab binding overrides app-level
   next-tab behavior.

2. Refactor state-filter cycling into one small helper that takes a direction or step. Keep
   `action_cycle_state_filter()` as the forward action and add a new reverse action, likely
   `action_cycle_state_filter_reverse()`, that calls the same helper with a negative step. This avoids duplicating the
   `_pending_force` reset, `_apply_filters()`, and `_refresh_options()` sequence.

3. Preserve `_STATE_FILTERS` order and `_DEFAULT_STATE_FILTER`. The new reverse behavior should be derived from the same
   tuple as forward cycling so future filter-order changes automatically affect both directions.

4. Update `src/sase/ace/tui/modals/project_management_rendering.py` so `footer_text()` mentions both `Tab` and
   `Shift+Tab` for state filtering. Keep the wording compact because this footer already contains many commands.

5. Extend `tests/ace/tui/modals/test_project_management_modal_filtering.py`:
   - Keep existing assertions for the default `active` filter and the full forward Tab cycle.
   - Add assertions that `await pilot.press("shift+tab")` from `active` wraps to `all`, then another Shift+Tab moves to
     `closed`.
   - Assert the visible filtered records match each state after reverse cycling, not just the `_state_filter` string.

6. Extend the existing footer test in the same test file to assert the footer includes the reverse-state affordance.
   This gives a cheap regression check for user-facing key help.

7. Audit mixed-state mark/state/delete tests after the code change. They mostly use forward Tab intentionally, so no
   expectation changes should be needed beyond any fallout from the shared helper or footer wording.

8. Do not update `src/sase/default_config.yml`. The relevant `shift+tab` entry already exists for global tab switching,
   and this Project Management behavior is currently implemented as modal-local Textual bindings rather than through the
   configurable app keymap registry.

## Verification Plan

Run the focused modal tests first:

```bash
.venv/bin/python -m pytest tests/ace/tui/modals/test_project_management_modal_filtering.py
.venv/bin/python -m pytest tests/ace/tui/modals/test_project_management_modal_states.py
.venv/bin/python -m pytest tests/ace/tui/modals/test_project_management_modal_marks.py
```

Then run the repository check required after source/test changes:

```bash
just check
```

If the ephemeral workspace dependencies are stale, run `just install` before `just check`, as the project instructions
recommend.
