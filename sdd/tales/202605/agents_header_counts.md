---
create_time: 2026-05-09 11:36:51
status: done
prompt: sdd/prompts/202605/agents_header_counts.md
---
# Plan: Agents Header Count Format

## Goal

Change the Agents tab info-panel header from:

`Agents: <unread> unread · <running> running · <total> total`

to:

`Agents(<total>): <running> running · <waiting> waiting · <unread> unread · <read> read`

The important semantic fix is that `WAITING` agents should no longer be included in the running count. The header should
also make the read/done split visible: `read = total - running - waiting - unread` over the same visible top-level agent
set the header already uses.

## Current Behavior

The header is rendered by `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`.

`AgentDisplayMixin._update_agents_info_panel()` in `src/sase/ace/tui/actions/agents/_display_detail.py` computes counts
from `panel_index.non_child_indices`, so child/retry rows do not inflate the header. It currently computes:

- `total`: visible top-level agents.
- `unread`: visible top-level agents whose identity is in `_unread_completed_agent_ids`.
- `running`: visible top-level agents whose status is not in `DISMISSABLE_STATUSES`.

That last rule is too broad. It treats `WAITING` as running because waiting agents are active/non-dismissable, but the
UI already presents `WAITING` as its own status bucket in the list.

## Design

Keep the count scope unchanged: count only visible top-level agents from `panel_index.non_child_indices`.

Introduce explicit header-count semantics in the Agents display path:

- `waiting_count`: statuses in the waiting bucket, currently at minimum `status == "WAITING"`.
- `running_count`: active statuses that are not dismissable and not waiting.
- `unread_count`: existing unread completed count.
- `read_count`: `total - running_count - waiting_count - unread_count`.

This preserves the current behavior that only visible top-level rows are counted, while fixing the classification of
waiting rows.

For maintainability, prefer using the existing status-bucket helper (`status_bucket_for()` /
`status_bucket_for_values()`) for waiting classification if it fits cleanly. That avoids duplicating status semantics in
the header. Continue using `DISMISSABLE_STATUSES` or the equivalent existing terminal-status concept for running-vs-done
behavior, so statuses like `PLANNING`, `QUESTION`, and `PLAN APPROVED` remain counted as running unless the existing
domain model says otherwise.

Update `AgentInfoPanel` to store and render the new fields:

`Agents(<total>): <running> running · <waiting> waiting · <unread> unread · <read> read`

Loading state should remain `Agents: …` unless a separate product decision is made; this plan does not change startup
loading behavior.

## Implementation Steps

1. Update `AgentInfoPanel.update_agent_counts()` to accept `unread`, `running`, `waiting`, `read`, and `total` counts.
   Adjust internal fields and the rendered text order/labels accordingly.
2. Update `AgentDisplayMixin._update_agents_info_panel()` to compute `waiting_count` separately from `running_count`.
   Keep the existing top-level visibility filter intact.
3. Update direct callers and test doubles for the new `update_agent_counts()` signature.
4. Update widget tests in `tests/ace/tui/widgets/test_agent_info_panel.py` for the exact new plain-text format.
5. Update integration coverage in `tests/ace/tui/test_agent_panel_index_integration.py` so a visible `WAITING` row
   contributes to waiting, not running, and `read` reflects the remaining visible top-level completed rows.

## Verification

Run focused tests first:

```bash
pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_agent_panel_index_integration.py
```

Because this repo requires it after code changes, run:

```bash
just install
just check
```

If `just check` is too slow or fails for unrelated environmental reasons, report that explicitly with the focused test
results.
