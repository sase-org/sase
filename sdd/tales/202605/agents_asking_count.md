---
create_time: 2026-05-09 15:34:55
status: done
prompt: sdd/prompts/202605/agents_asking_count.md
---
# Add Agents Tab Asking Count

## Goal

Add an `asking` count to the top metric strip of the `sase ace` Agents tab. The count should represent visible,
top-level agents that are currently paused for human input, matching the existing row-level user-paused marker shown
beside runtime suffixes.

## Current Behavior

- The Agents tab top strip is rendered by `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`.
- The strip currently shows `running`, `waiting`, `unread`, and `read`.
- Counts are computed in `DetailMixin._update_agents_info_panel()` in
  `src/sase/ace/tui/actions/agents/_display_detail.py`.
- The existing `waiting` count is based on `status_bucket_for(agent) == "Waiting"`, so it covers dependency/timer waits
  such as `WAITING`, not human-review waits such as `PLANNING`.
- The row-level human-input visual marker is driven by
  `_USER_PAUSED_STATUSES = {"PLANNING", "QUESTION", "WAITING INPUT"}` in
  `src/sase/ace/tui/widgets/_agent_list_render_layout.py`.
- Query semantics for `needs:input` are separate and currently include `PLAN APPROVED`; the new top-strip count should
  not silently inherit that behavior because the user explicitly asked to match the row marker signal.

## Implementation Plan

1. Introduce a shared human-input predicate or status set for the row marker and top-strip count.
   - Add a small exported helper or constant in a shared semantic module, preferably `src/sase/agent/status_buckets.py`,
     such as `AGENT_ASKING_STATUSES` and `agent_is_asking(status)`.
   - Define it as the row-marker statuses: `PLANNING`, `QUESTION`, and `WAITING INPUT`.
   - Keep it separate from `_NEEDS_INPUT_STATUSES` to avoid changing existing `needs:input` query behavior in this
     change.

2. Update the row runtime suffix marker to use the shared semantic source.
   - Replace the local `_USER_PAUSED_STATUSES` set in `src/sase/ace/tui/widgets/_agent_list_render_layout.py` with the
     shared helper or constant.
   - Preserve existing row rendering behavior and tests.

3. Add an `asking` metric to `AgentInfoPanel`.
   - Store `_asking_count` in `AgentInfoPanel`.
   - Extend `update_agent_counts()` to accept `asking`.
   - Render the metric as `N asking` in the bracketed strip near the front, for example:
     `12 Agents [2 asking · 5 running · 2 waiting · 3 unread · 0 read]`
   - Use a distinct style, likely matching the user-paused marker color family (`#FFAF00`) rather than reusing waiting
     purple.

4. Update count computation in `_update_agents_info_panel()`.
   - Build the count only from visible top-level agents, using the existing `panel_index.non_child_indices` path so
     child workflow steps do not inflate totals.
   - Count `asking` with the shared human-input predicate.
   - Count `waiting` as the existing `Waiting` bucket.
   - Count `running` as active non-dismissable agents that are neither `asking` nor `waiting`.
   - Compute `read_count = total - asking_count - running_count - waiting_count - unread_count`, preserving the existing
     top-level visible total invariant.

5. Update focused tests.
   - Adjust `tests/ace/tui/widgets/test_agent_info_panel.py` expectations for the new text and style.
   - Adjust `tests/ace/tui/test_agent_panel_index_integration.py` for the new `update_agent_counts()` signature and add
     at least one `PLANNING` visible top-level agent to verify the count excludes workflow children.
   - Add or update a row-runtime test only if the shared constant import changes behavior risk; existing tests already
     cover `PLANNING`, `QUESTION`, and `WAITING INPUT` marker rendering.

6. Verify.
   - Run targeted tests for the info panel, panel-index integration, and row runtime rendering.
   - Run `just install` if needed, then `just check` per repo instructions because code files will be changed.

## Non-Goals

- Do not change the Agents tab label counts in the top tab bar unless tests reveal it shares the same metric strip
  contract.
- Do not change `needs:input` query behavior in this change.
- Do not change status bucketing order or rename the existing `Waiting` bucket.
