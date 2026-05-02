---
create_time: 2026-03-31 20:10:34
status: done
prompt: sdd/prompts/202603/agents_enter_query_fix.md
---

# Plan: Fix Enter key on Agents tab to change CLs query when ChangeSpec not matched

## Problem

When pressing `<enter>` on the Agents tab, the intended behavior is to navigate to the CLs tab and select the agent's
ChangeSpec. If the ChangeSpec isn't matched by the current CLs search query, it should change the query to
`project:<project>`. This logic already exists in `navigate_to_changespec_tab()` and is already called by
`action_jump_to_agent_changespec()`, but the Enter key never actually triggers this action.

**Root cause**: The `AgentList` widget extends Textual's `OptionList`, which has a built-in `enter -> select` binding.
In Textual, widget-level bindings take priority over App-level bindings (unless `priority=True` is set). So when Enter
is pressed, `OptionList.action_select` fires and posts an `OptionSelected` event, which the `AgentList` handles by
posting a `SelectionChanged` message. This just updates the current selection index — it never calls
`action_jump_to_agent_changespec`. The App-level `enter -> jump_to_agent_changespec` binding never gets a chance to
fire.

**Evidence**: Tab switching bindings (`tab`, `shift+tab`) have `priority=True` in `bindings.py:49-50`, allowing them to
override widget bindings. The Enter binding at `bindings.py:106` does not.

## Fix

Override `BINDINGS` in the `AgentList` class to exclude the `enter -> select` binding inherited from `OptionList`. This
allows the Enter key event to propagate to the App level, where `jump_to_agent_changespec` handles it.

**File**: `src/sase/ace/tui/widgets/agent_list.py`

Add a `BINDINGS` override to the `AgentList` class that includes all of `OptionList`'s default bindings except
`enter -> select`. Keep `up/down/home/end/pageup/pagedown` for arrow key navigation and accessibility.

**What this preserves**:

- Mouse clicks on agents still trigger `OptionSelected` (click handling is separate from key bindings)
- Arrow key navigation still works via the remaining OptionList bindings
- `j/k` navigation still works via App-level bindings
- The `on_option_list_option_highlighted` handler keeps the detail panel in sync during navigation

**What changes**:

- Enter key now triggers `action_jump_to_agent_changespec` instead of `OptionList.action_select`
- This navigates to the CLs tab and selects the ChangeSpec
- If the ChangeSpec isn't in the current query results, `navigate_to_changespec_tab` changes the query to
  `project:<project>` (reusing existing code from `_notification_navigation.py`)
