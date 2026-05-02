---
create_time: 2026-05-01 13:49:37
status: done
prompt: sdd/prompts/202605/failed_agents_status_bucket.md
---
# Plan: Separate Failed Agents From Needs Attention

## Goal

When the Agents tab is grouped by status, agents whose displayed status starts with `FAILED` should appear under a
top-level `Failed` bucket instead of `Needs Attention`. `Needs Attention` should still render immediately above
`Failed`, and should continue to mean user-action states such as `PLANNING` and `QUESTION`.

## Current Behavior

The shared status bucketing contract lives in `src/sase/agent/status_buckets.py`.

Today:

- `PLANNING` and `QUESTION` map to `Needs Attention`.
- `WAITING` maps to `Waiting`.
- terminal success/plan handoff statuses map to `Done`.
- `FAILED` without `retried_as_timestamp` maps to `Needs Attention`.
- `FAILED` with `retried_as_timestamp`, including `FAILED (RETRIED)`, maps to `Failed`.

The Agents tab `BY_STATUS` mode consumes this through `src/sase/ace/tui/models/agent_groups/_buckets.py`, which then
uses `AGENT_STATUS_BUCKETS` for deterministic level-0 ordering:

`Needs Attention -> Running -> Waiting -> Failed -> Done`

That order already places `Needs Attention` directly above `Failed` when both buckets are present and
`Running`/`Waiting` are absent. However, if `Running` or `Waiting` are present, they currently sit between
`Needs Attention` and `Failed`.

The same shared mapping is also used by `src/sase/integrations/agent_status_groups.py`, so changing it will align
integration-facing status grouping with the TUI.

## Proposed Behavior

Update the shared bucket semantics so every status string that starts with `FAILED` maps to `Failed`, independent of
retry lineage.

Update bucket display order to keep actionable and failure buckets adjacent:

`Needs Attention -> Failed -> Running -> Waiting -> Done`

This satisfies the requested rendering relationship: in `BY_STATUS`, `Needs Attention` will render immediately above
`Failed` whenever both buckets are present, even if running or waiting agents are also present.

## Implementation Steps

1. Change `AGENT_STATUS_BUCKETS` in `src/sase/agent/status_buckets.py` to place `Failed` immediately after
   `Needs Attention`.
2. Simplify `status_bucket_for_values()` so `status_text.startswith("FAILED")` always returns `Failed`.
3. Update nearby comments/docstrings so `Needs Attention` no longer claims un-retried failures.
4. Update Agents-tab grouping docs/comments in `src/sase/ace/tui/models/agent_groups/_buckets.py` and related help text
   if needed.
5. Update tests that encode old behavior:
   - `tests/ace/tui/models/test_agent_groups_grouping_mode_status.py`
   - `tests/test_agent_status_groups.py`
   - `tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py`
   - `tests/ace/tui/widgets/test_agent_list_grouping_buckets.py`
   - any other grep hits that assert the previous order or old `FAILED` bucket assignment.
6. Add/adjust a focused rendering regression for `BY_STATUS` containing `QUESTION`, `FAILED`, `RUNNING`, `WAITING`, and
   `DONE`, asserting the top-level group order is `Needs Attention`, `Failed`, `Running`, `Waiting`, `Done`.

## Validation

Run targeted tests first:

```bash
pytest tests/ace/tui/models/test_agent_groups_grouping_mode_status.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py \
  tests/ace/tui/widgets/test_agent_list_grouping_buckets.py \
  tests/test_agent_status_groups.py
```

Then, because this repository's instructions require it after edits, run:

```bash
just install
just check
```

## Risks

Because `sase.integrations.agent_status_groups` reuses the shared contract, this changes any integration or CLI surface
that groups agents by status. That is desirable if the product meaning of `Failed` is changing globally, but it is still
a behavioral compatibility change. Tests should make that explicit rather than burying the change in renderer-only
assertions.
