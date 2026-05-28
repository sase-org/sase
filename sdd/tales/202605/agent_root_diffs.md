---
create_time: 2026-05-28 09:18:48
status: done
prompt: sdd/prompts/202605/agent_root_diffs.md
---
# Plan: Root Plan-Agent Rows Should Show Active Coder Diffs

## Problem

When a root plan-agent row is selected while its approved `-code` follow-up is actively implementing, the prompt-panel
`Deltas:` section and file panel can show the wrong diff. Expanding the root row and selecting the `-code` child shows
the expected diff, so the diff source itself is available; the root row is not resolving to the same source.

## Diagnosis

Both the prompt-panel `Deltas:` header and the file panel fetch diffs through
`src/sase/ace/tui/widgets/file_panel/_diff.py:get_agent_diff(agent)`.

Plan-family root rows are normalized in `src/sase/ace/tui/models/_agent_status_overrides.py`:

- follow-up children are attached to `parent.followup_agents`;
- active `-code` children are relabeled to `PLAN APPROVED` or `TALE APPROVED`;
- the root mirrors the newest logical child status;
- only missing root display metadata is backfilled from that child.

That means an active root row can correctly display `PLAN APPROVED`/`TALE APPROVED` while still carrying the planner's
workspace metadata. Since live diffs are derived from the selected agent's workspace, selecting the root row can read
the planner/root workspace, while selecting the `-code` child reads the coder workspace.

## Implementation

1. Add a small diff-source resolver near `get_agent_diff` that detects root plan-family rows with an active `-code`
   follow-up and returns the newest active coder child as the effective diff source.
2. Keep display metadata policy unchanged. This avoids broad changes to model/provider/header behavior and scopes the
   fix to the shared diff path used by both the file panel and prompt-panel `Deltas:`.
3. Use the resolved source for live diff cache-key computation and provider lookup so the root row reads the same
   workspace as the selected coder child.
4. Add regression coverage where a root plan row keeps a stale planner `workspace_num`, has an active `-code` follow-up
   with a different workspace, and `get_agent_diff(root)` reads the coder workspace.
5. Add prompt-panel coverage that `build_detail_header_summary(root)` renders `Deltas:` from the active coder child
   diff.

## Verification

Run the focused tests for file-panel diff resolution and prompt-panel deltas, then run the repository check required by
the workspace instructions:

- `pytest tests/ace/tui/widgets/file_panel/test_diff_cache.py tests/ace/tui/widgets/test_agent_deltas.py`
- `just install`
- `just check`
