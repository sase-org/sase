---
create_time: 2026-05-08 14:00:17
status: done
prompt: sdd/prompts/202605/agent_unread_completion_indicator.md
---
# Plan: Move completed-unread agent indicator into the runtime suffix

## Goal

Replace the leading `✦` unread marker on completed agent rows with a more visible emoji marker in the right-side runtime
suffix. The marker should occupy the same visual slot that the live `🏃‍♂️` marker uses while an agent is running, so a row
naturally changes from "running runtime" to "newly completed runtime" when it finishes unseen.

## Current Behavior

- Completion-read state is already tracked per TUI session in `src/sase/ace/tui/actions/agents/_loading_finalize.py` via
  `_unread_completed_agent_ids`.
- `_sync_unread_completed_agents()` marks rows unread only when they transition from a non-dismissable status to one of
  `DISMISSABLE_STATUSES`, and clears the currently selected row on the agents tab.
- Navigation and selection clear this state in:
  - `src/sase/ace/tui/actions/navigation/_basic.py`
  - `src/sase/ace/tui/actions/event_handlers.py`
- Rendering passes `is_unread` from `AgentList.update_list()` through:
  - `src/sase/ace/tui/widgets/_agent_list_build.py`
  - `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
  - `src/sase/ace/tui/widgets/_agent_list_render_cache.py`
- The visible indicator today is a leading `✦` inserted before the mark checkbox in `format_agent_option()`.
- Runtime suffix rendering is centralized in `src/sase/ace/tui/widgets/_agent_list_render_layout.py`. Active/ticking
  rows already prefix elapsed runtime with `🏃‍♂️`.

## Proposed UX

- Remove the leading `✦` from the left side of the agent row.
- Add an unread-completed marker to the suffix when `is_unread=True`.
- Use a completion-oriented emoji such as `🎉` in the same position as the live marker:
  - running: `🏃‍♂️ 38m45s`
  - unread completed: `20:17:03 · 🎉 6h17m`
  - read completed: `20:17:03 · 6h17m`
- If a terminal unread row has no elapsed runtime suffix, render a marker-only suffix rather than losing the indicator.
  This keeps the behavior robust for sparse artifact rows and unusual workflow-step rows.

## Implementation Steps

1. Update `build_runtime_suffix()` in `_agent_list_render_layout.py` to accept an `is_unread` keyword-only flag.
   - Preserve the existing live marker behavior for ticking rows.
   - For non-ticking unread rows, prefix the elapsed runtime with the new completed-unread emoji.
   - For unread rows without runtime data, return a suffix containing only the completed-unread emoji.
   - Keep styling local to the suffix constants, using a warm accent consistent with the existing runtime marker.

2. Thread the unread flag through row formatting.
   - In `_agent_list_render_agent.py`, stop appending the left-side `✦`.
   - Pass `is_unread=is_unread` into `build_runtime_suffix()`.
   - Keep `is_unread` in the render cache key; it still changes visible output.

3. Keep unread state semantics unchanged.
   - Do not rename `_unread_completed_agent_ids` or alter finalizer/navigation behavior unless tests expose a stale
     patch path.
   - Preserve row patching behavior: clearing unread should update the suffix in place when the new prompt fits the
     existing target width; otherwise the existing full-refresh fallback should handle it.

4. Update tests.
   - Adjust runtime-rendering tests that currently expect `✦` on the left.
   - Add or revise assertions for:
     - unread completed rows show the new emoji in the suffix before elapsed runtime;
     - unread rows no longer show a left-side marker;
     - default/read rows omit the completed-unread emoji;
     - cache invalidation on `is_unread` still changes the rendered suffix;
     - `patch_agent_row(..., unread_agents=set())` removes the suffix marker.
   - Keep existing `_sync_unread_completed_agents()` tests, since the lifecycle semantics are still correct.

5. Verify.
   - Run focused tests:
     - `pytest tests/ace/tui/test_agent_unread_indicator.py`
     - `pytest tests/ace/tui/widgets/test_agent_list_runtime_rendering.py tests/ace/tui/widgets/test_agent_render_cache.py`
   - Because this repo requires it after file changes, run `just install` if needed and then `just check` before the
     final response.

## Risks and Mitigations

- **Terminal unread rows with no runtime**: moving the only indicator to the suffix could hide unread state. The
  marker-only fallback prevents that.
- **Alignment churn**: unread suffixes are wider than read suffixes. Full list rebuild already calculates max suffix
  width, and the single-row patch path falls back to a full refresh if the row grows past `_target_width`.
- **Emoji cell width differences**: tests should assert plain text content rather than exact padding. Existing layout
  uses Rich `Text.cell_len`, so alignment should remain terminal-aware.
- **State naming mismatch**: the term "unread" still describes the state correctly even though the visual marker
  changes; renaming it would add churn without improving behavior.
