---
create_time: 2026-05-08 14:29:55
status: done
prompt: sdd/prompts/202605/most_recent_unread_done_jump.md
---
# Plan: Jump unread completed agents by completion recency

## Objective

Change the Agents-tab `,j` leader key so it jumps through unread completed agent rows by completion recency rather than
by rendered row order.

Desired behavior:

- First invocation jumps to the visible unread completed agent that completed most recently.
- Repeated invocations advance to the next most recently completed visible unread agent.
- After the least recent visible unread completed agent, the command wraps back to the most recent.
- The jump still preserves the target row's unread marker. Normal row selection remains the path that
  acknowledges/clears unread state.

## Current State

The current implementation lives in `src/sase/ace/tui/actions/agents/_core.py` as `_jump_to_next_unread_done_agent()`.

It currently:

- Builds candidates from `_agents_visible_order()`.
- Starts just after the current visible row, or after a focused banner's row in `_panel_navigation_stops()`.
- Picks the next `DONE` or `FAILED` agent whose identity is in `_unread_completed_agent_ids`.
- Clears banner focus, updates `current_idx`, clears pinned attempt state, and patches or refreshes the list.
- Re-adds the target identity to `_unread_completed_agent_ids` so jumping does not mark it read.

Unread state is populated by `_sync_unread_completed_agents()` in
`src/sase/ace/tui/actions/agents/_loading_finalize.py`, which tracks newly terminal dismissable rows. The command and
footer currently gate availability through visible `DONE` / `FAILED` unread rows.

## Semantics

Use completion recency as the navigation order, while still limiting candidates to currently visible Agents-tab rows.

Candidate set:

- Indexes from `_agents_visible_order()`.
- Valid indexes into `self._agents`.
- Agent status remains the current command scope: `DONE` or `FAILED`.
- Agent identity is present in `_unread_completed_agent_ids`.

Ordering:

- Sort candidates by completion timestamp descending.
- Use `agent.stop_time` as the authoritative completion timestamp.
- Fall back to `agent.start_time` when `stop_time` is missing, matching existing date-group fallback behavior for
  terminal rows.
- Keep the sort deterministic for missing/equal timestamps by preserving visible order as a stable tiebreaker.

Repeated invocation cursor:

- Do not add new persistent queue state unless implementation proves it necessary.
- Because the target remains unread, "newest unread" alone would repeatedly select the same agent.
- Instead, use the current focused row as the recency cursor:
  - If the current focused agent is in the recency-ordered unread candidate list, select the next candidate in that
    list, wrapping at the end.
  - If focus is on a banner, a running/read row, an invalid index, or otherwise outside the candidate list, select the
    first candidate in recency order.
- This makes the first invocation from ordinary focus jump to the most recent unread completion, and each subsequent
  invocation naturally advances because focus is now on the previously jumped unread row.

Banner behavior:

- A focused banner should no longer determine the starting row by rendered position.
- From banner focus, start at the most recent unread completed candidate.
- Preserve the existing outcome that successful jump clears `_current_group_key` and refreshes/patches the highlight as
  needed.

## Implementation Plan

1. Update `_jump_to_next_unread_done_agent()` in `src/sase/ace/tui/actions/agents/_core.py`.
   - Replace the rendered-order scan with a recency-ordered candidate list.
   - Keep `_agents_visible_order()` as the source of visibility and stable tie order.
   - Compute candidate tuples containing `(agent_idx, visible_pos, completion_time)`.
   - Sort newest first. Treat missing completion/start timestamps as oldest.
   - Determine the next target from `self.current_idx` only when `_current_group_key` is `None` and the current index is
     in the sorted candidate list.
   - Otherwise target sorted candidate position `0`.

2. Preserve existing side effects.
   - Return `False` when there are no visible unread `DONE` / `FAILED` candidates.
   - Set `_current_group_key = None`.
   - Set `current_idx` to the target index.
   - Clear `current_attempt_number` when present.
   - Preserve the target unread marker.
   - Use `_try_patch_agent_row()` and fall back to `_refresh_agents_display(list_changed=True, defer_detail=True)`
     exactly as today.
   - Keep the debounced refresh path for clearing banner focus when the target row is already selected.

3. Update focused tests in `tests/ace/tui/test_agent_unread_indicator.py`.
   - Replace the visible-order/wrap expectation with recency-order/wrap expectation.
   - Add or adapt coverage showing:
     - First invocation chooses newest completion even when visible order differs.
     - Repeated invocations advance from newest to next-newest while preserving unread state.
     - Wrap returns from least recent to newest.
     - Read/running rows are ignored.
     - Missing `stop_time` falls back to `start_time`.
     - Banner focus starts at newest and still clears banner focus.
   - Keep existing tests for patch fallback and unread preservation.

4. Leave command metadata and availability unchanged unless tests reveal drift.
   - The command id, keymap, help text, footer text, and availability predicate already describe and expose the same
     command.
   - Availability only needs to know whether at least one unread completed candidate exists, not its order.

5. Verification.
   - Run the focused unread tests:
     - `pytest tests/ace/tui/test_agent_unread_indicator.py`
   - Run command/keymap focused coverage if touched indirectly or if imports change:
     - `pytest tests/test_command_availability.py tests/test_keymaps.py tests/ace/tui/test_show_agent_run_log_keymap.py`
   - Because this repo requires it after code changes, run:
     - `just check`

## Risks and Edge Cases

- If many unread agents lack `stop_time`, fallback ordering by `start_time` is only an approximation of completion
  recency. This matches existing terminal-row date grouping behavior and avoids adding filesystem reads to a keypress
  path.
- If a refresh changes the visible unread set between keypresses, the next invocation recomputes the sorted list from
  current state. If the current row is no longer an unread candidate, navigation restarts at the newest visible unread
  candidate.
- The implementation intentionally remains TUI-local. This is presentation/navigation behavior, not shared backend
  behavior, so it does not need a Rust core change.
