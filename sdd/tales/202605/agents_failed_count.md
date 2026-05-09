---
create_time: 2026-05-09 15:46:07
status: done
prompt: sdd/prompts/202605/agents_failed_count.md
---
# Plan: Agents Failed Count And Zero-Count Noise

## Goal

Add a visible failed-agent count to the top of the `sase ace` Agents tab and reduce count noise by omitting metric types
whose count is zero.

## Product Behavior

- The Agents tab info strip should continue to show the total visible top-level agent count first.
- The bracketed metric strip should include only non-zero metric types.
- Add a `failed` metric type for visible top-level agents whose status buckets as `Failed`, including statuses like
  `FAILED` and `FAILED (RETRIED)`.
- Keep unread completed agents distinct from failed agents:
  - `unread` remains a user-attention/read-state signal.
  - `failed` remains an outcome/status signal.
- Do not show a bracketed metrics section when every metric count is zero.
- Keep loading behavior unchanged: while the first Agents load is in progress, the info strip still renders
  `Agents: ...`.

## Technical Approach

1. Update `AgentInfoPanel`
   - Add a `_failed_count` field and a failed style.
   - Extend `update_agent_counts(...)` to accept `failed`.
   - Render metric chips through a small helper/list so zero-count metric types are skipped uniformly.
   - Preserve the existing order, inserting `failed` near other state/outcome metrics: `asking`, `running`, `waiting`,
     `failed`, `unread`, `read`.

2. Update Agents-tab count derivation
   - In `_update_agents_info_panel`, compute `failed_count` from `status_bucket_for(agent) == "Failed"` over
     `visible_top_level_agents`.
   - Recompute `read_count` so failed agents are not implicitly folded into `read`.
   - Pass the new failed count into `AgentInfoPanel.update_agent_counts(...)`.

3. Keep the tab bar behavior stable unless needed
   - The `TabBar` suffix path already filters keyed zero counts and hides the whole suffix when every count is zero.
   - This request’s “top of the Agents tab” and “visual noise” map most directly to `AgentInfoPanel`; changing the
     global tab label is not required for the main goal.
   - If tests reveal a tab-label count still emits zero-valued types, adjust the shared `TabBar` helper narrowly.

4. Tests
   - Update `tests/ace/tui/widgets/test_agent_info_panel.py` for:
     - failed count rendering,
     - zero-count metric omission,
     - no bracketed metric section when all metric counts are zero,
     - style coverage for the new failed count.
   - Update `tests/ace/tui/test_startup_loading_indicators.py` expectations for the new zero-count suppression.
   - Update `tests/ace/tui/test_agent_panel_index_integration.py` to verify failed agents produce `failed`, not `read`,
     in the info-panel counts.
   - Run the focused tests first, then run `just install` if needed and `just check` before finishing because this repo
     requires it after file changes.

## Risks And Constraints

- The existing `update_agent_counts(...)` method is used by tests and app code; all call sites must be updated together.
- `FAILED (RETRIED)` is not in `DISMISSABLE_STATUSES`, so failed counting should use the shared status bucket semantics
  rather than hard-coded equality.
- Workflow children should remain excluded from top-level counts, matching current info-panel behavior.
- The change is presentation-only and should stay in the Python/Textual TUI layer.
