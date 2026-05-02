---
create_time: 2026-04-01 14:01:52
status: done
prompt: sdd/prompts/202604/enter_accepts_file_completion.md
---

# Fix Enter Key to Accept File Completion Instead of Launching Agent

## Problem

In `prompt_text_area.py`, the `_on_key()` method handles Enter unconditionally at the top (lines 643-647), always
calling `action_submit_prompt()`. This means pressing Enter while the file completion menu is active submits the prompt
(launching an agent) instead of accepting the selected completion.

## Fix

Modify the Enter handler in `_on_key()` to check if file completion is active first. If active, call
`_accept_file_completion()` instead of `action_submit_prompt()`.

### Changes

**File: `src/sase/ace/tui/widgets/prompt_text_area.py`** (lines 643-647)

Current code:

```python
if event.key == "enter":
    event.stop()
    event.prevent_default()
    self.action_submit_prompt()
    return
```

New code:

```python
if event.key == "enter":
    event.stop()
    event.prevent_default()
    if self._file_completion_active:
        self._accept_file_completion()
    else:
        self.action_submit_prompt()
    return
```

This reuses the existing `_accept_file_completion()` method which already:

- Inserts the selected candidate's `insertion` text at the token position
- Handles directory drill-down (if a directory is selected, re-triggers completion to show its contents)
- Handles file selection (clears the completion menu after inserting)

**File: `tests/ace/tui/widgets/test_prompt_file_completion.py`**

Add a test `test_enter_accepts_completion_instead_of_submitting` that:

1. Sets up a completion menu with multiple candidates
2. Navigates to a candidate
3. Presses Enter
4. Asserts: the selected candidate was inserted into the prompt text
5. Asserts: the completion menu was dismissed
6. Asserts: no `PromptInputBar.Submitted` message was posted (i.e., no agent launch)

### Scope

- 2 files changed
- ~15 lines of code added/modified
- No architectural changes; reuses existing `_accept_file_completion()` logic
