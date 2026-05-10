---
create_time: 2026-05-10 01:03:04
status: wip
prompt: sdd/prompts/202605/agents_stopped_status.md
---
# Plan: Rename Agents Status Presentation to Stopped

## Goal

Update the `sase ace` TUI presentation so agent statuses that are currently shown as `Needs Attention` in the Agents tab
status grouping appear as `Stopped`, and so the top agent-count strip uses `stopped` instead of `hitl`. The compact
panel-title shorthand for the same count should change from `H` to `S`.

## Context

The by-status grouping is driven by shared bucket helpers in `src/sase/agent/status_buckets.py`. The Agents tab's
`BY_STATUS` tree uses those bucket strings as level-0 group keys and renders the matching glyph from the shared glyph
map. Integration helpers also consume the same shared buckets, so this should be treated as a shared display-label
rename rather than a local string substitution in one renderer.

The top count strip is rendered by `src/sase/ace/tui/widgets/agent_info_panel.py`. It counts agents paused for explicit
human input via the existing `asking` metric and currently labels it as `hitl`. Per-panel border-title counts in
`src/sase/ace/tui/actions/agents/_display_panels.py` use the same `asking` metric with shorthand `H`.

## Implementation Approach

1. Rename the shared bucket label from `Needs Attention` to `Stopped` in the shared status bucket constants and the
   `status_bucket_for_values()` return value. Preserve the existing bucket membership: `PLANNING` and `QUESTION` remain
   in this bucket, and the bucket keeps its priority order ahead of `Failed`, `Running`, `Waiting`, and `Done`.
2. Update consumers that compare or document the bucket label, including banner summary logic, grouping docs/comments,
   help modal status text, and tests.
3. Change the top Agents info strip label mapping from `asking -> hitl` to `asking -> stopped`.
4. Change the panel-title shorthand for the same `asking` metric from `H` to `S`.
5. Update focused unit tests and snapshots/goldens only where they assert these user-visible strings or shorthand
   characters.

## Verification

Run focused tests for the touched behavior first:

- `pytest tests/test_agent_status_groups.py`
- `pytest tests/ace/tui/models/test_agent_groups_grouping_mode_status.py`
- `pytest tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py`
- `pytest tests/ace/tui/widgets/test_agent_list_grouping_buckets.py`
- `pytest tests/ace/tui/widgets/test_agent_info_panel.py`
- `pytest tests/ace/tui/test_agent_panel_titles.py`
- `pytest tests/ace/tui/test_startup_loading_indicators.py`

Because this repo's instructions require it after source changes, run `just install` if the workspace has not been
installed, then `just check` before reporting completion.
