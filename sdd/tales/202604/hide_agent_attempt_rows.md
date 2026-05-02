---
create_time: 2026-04-27 11:46:22
status: done
prompt: sdd/prompts/202604/hide_agent_attempt_rows.md
---
# Hide Attempt Rows In Agents List

## Goal

Stop rendering prior retry attempt rows as child entries in the left-side agent list on the `sase ace` Agents tab. The
agent list should stay compact: one visible row per agent, plus existing group/banner rows. Attempt history should
remain available to the agent detail panel, retry metadata, search, and the existing `V` attempt-history toggle.

## Current Behavior

`AgentList.update_list()` in `src/sase/ace/tui/widgets/agent_list.py` expands each non-workflow agent's
`attempt_history` into additional selectable rows. These rows are formatted by `format_attempt_option()` in
`src/sase/ace/tui/widgets/_agent_list_rendering.py`, stored in `_row_entries` as `(agent_idx, attempt_number)`, and
drive `current_attempt_number` selection so the detail panel pins to a prior attempt.

This is why the left panel in the snapshot shows lines like:

```text
    ↳ Attempt 1 · 11:22:15 · failed: ...
```

The same `attempt_history` is also used outside the list rows:

- `compute_fold_annotation()` shows the compact `↻N` badge on the agent row.
- `AgentDetail` / prompt panel render retry metadata and merged/current-only attempt views.
- `current_attempt_number` supports pinned attempt display when a prior-attempt row is selected.
- Search includes prior attempt reply files.

The desired change is only to remove the expanded child rows from the list, not to delete attempt data.

## Implementation Plan

1. Update `AgentList.update_list()` so it no longer preformats or emits per-attempt child options.
   - Remove the `attempt_parts` build path from the width precomputation loop.
   - Remove the loop that appends attempt options after each agent row.
   - Keep `_row_entries` as agent rows and banner/spacer rows only.
   - Keep `current_attempt_number` accepted by the public method for compatibility, but it should not create a
     highlighted attempt row.

2. Make highlight behavior robust when stale pinned-attempt state exists.
   - Treat the selected agent row as selected even if `current_attempt_number` is non-`None`, since no attempt row
     exists to receive highlight.
   - In `update_highlight()`, if `(current_idx, current_attempt_number)` is not present, fall back to
     `(current_idx, None)`.
   - This prevents a stale pinned attempt from leaving the list without a highlight after refresh.

3. Preserve non-list attempt affordances.
   - Leave attempt loading, `attempt_history`, `compute_fold_annotation()`, `V` attempt view, retry detail header, and
     search behavior untouched.
   - Leave `format_attempt_option()` available only if tests or future modals still use it; remove it only if no
     remaining references require it.

4. Update tests around list rendering.
   - Change `tests/ace/tui/widgets/test_agent_list_attempts.py` so an agent with attempts renders only the group banners
     plus the agent row.
   - Replace child-row resolution/highlight expectations with fallback-to-agent-row expectations.
   - Keep tests that assert the compact `↻N` annotation remains on agent rows.
   - Remove or rewrite tests that specifically validate attempt option text/IDs/duration if the formatter becomes
     unused.

5. Run focused verification first, then repo verification.
   - Focused: `pytest tests/ace/tui/widgets/test_agent_list_attempts.py`
   - Broader affected surface:
     `pytest tests/ace/tui/widgets/test_agent_list_grouping.py tests/ace/tui/test_agent_jk_navigation.py tests/ace/tui/widgets/test_agent_display_attempts.py`
   - Required repo check after code changes: `just install` if needed, then `just check`.

## Risks And Decisions

- Removing list child rows also removes mouse/keyboard selection of a specific prior attempt from the left list. That is
  acceptable for this request because the visible attempt rows are the problem, and the existing detail panel still
  exposes attempt history through merged/current-only display.
- Keeping `current_attempt_number` compatibility avoids broad churn in event handling and detail rendering. If some path
  still sets a pinned attempt, the detail panel can continue honoring it, while the list simply highlights the parent
  agent.
- The agent row's `↻N` annotation should remain. It is compact and communicates retry history without consuming vertical
  space.
