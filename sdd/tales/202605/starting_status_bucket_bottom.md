---
create_time: 2026-05-12 20:20:36
status: done
prompt: sdd/prompts/202605/starting_status_bucket_bottom.md
---
# Plan: Move Agents BY_STATUS Starting Bucket To Bottom

## Goal

When the `sase ace` TUI Agents tab is grouped `by status`, render the `Starting` status group after the other status
groups instead of between `Failed` and `Running`.

Desired Agents-tab L0 bucket order:

1. `Stopped`
2. `Failed`
3. `Running`
4. `Waiting`
5. `Done`
6. `Starting`

Empty buckets should still be omitted, and the change should affect only the Agents-tab status-group presentation unless
explicitly broadened.

## Current Shape

The Agents grouping model lives under `src/sase/ace/tui/models/agent_groups/`. Status bucketing itself is already
centralized in `src/sase/agent/status_buckets.py` via `status_bucket_for_values()`.

For the TUI tree, `GroupingMode.BY_STATUS` stores the status bucket label in the existing L0 `project` slot, then sorts
L0 groups through:

- `src/sase/ace/tui/models/agent_groups/_buckets.py`
  - `_STATUS_BUCKETS`
  - `bucket_sort_index()`
- `src/sase/ace/tui/models/agent_groups/_keys.py`
  - `_project_sort_key()`
  - `walk_order()`

Right now `_STATUS_BUCKETS` is copied directly from the shared `AGENT_STATUS_BUCKETS` tuple, whose order is also used by
`src/sase/integrations/agent_status_groups.py`. Changing that shared tuple would also reorder integration-facing status
groups, so the safer scope is a TUI-specific ordering constant.

## Implementation Plan

1. Add an Agents-TUI-specific status bucket order in `src/sase/ace/tui/models/agent_groups/_buckets.py`.
   - Keep `status_bucket_for()` mapped through `status_bucket_for_values()` so bucket classification remains shared.
   - Use the new local tuple only for `GroupingMode.BY_STATUS` L0 sort order.
   - Remove the no-longer-needed import of `AGENT_STATUS_BUCKETS` from this TUI module.

2. Update local comments/docstrings that describe BY_STATUS order.
   - `GroupingMode` docstring currently lists `Starting` before `Running`.
   - `bucket_sort_index()` can continue to describe this as fixed bucket order, but comments should not imply the old
     order.

3. Update focused tests for the TUI order.
   - In `tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py`, change the BY_STATUS order assertion to expect
     `Starting` last when a starting agent is present.
   - In `tests/ace/tui/widgets/test_agent_list_grouping_buckets.py`, change the rendered banner-label assertion to
     expect `Starting` last.
   - Add or adjust a focused assertion that includes every status bucket so a future reorder cannot pass accidentally.

4. Leave integration tests unchanged unless they fail for a legitimate reason.
   - `tests/test_agent_status_groups.py` currently documents the shared integration helper order. Since this request is
     specifically for the ACE TUI Agents tab, those helpers should keep their current behavior.

5. Verify with targeted tests first, then the repo check.
   - Run:
     `pytest tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py tests/ace/tui/widgets/test_agent_list_grouping_buckets.py tests/test_agent_status_groups.py`
   - Because this repo memory requires it after code changes, run: `just check`

## Risks And Notes

- The main risk is accidentally changing the shared `AGENT_STATUS_BUCKETS` contract used by integrations. The plan
  avoids that by introducing a TUI-only order for sorting, not for classification.
- Fold state keys use bucket labels, not numeric positions, so moving the bucket should not invalidate existing
  folded/collapsed state.
- Navigation and rendering walk the same `build_agent_tree()` result, so a model-level order fix should propagate to
  visible rows, banner focus, and j/k navigation without separate navigation changes.
