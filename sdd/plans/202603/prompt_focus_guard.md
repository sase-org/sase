---
create_time: 2026-03-31 18:29:36
status: done
prompt: sdd/prompts/202603/prompt_focus_guard.md
---

# Fix: Prompt Input Widget Focus Guard

## Problem

The `PromptTextArea` in the prompt input bar can lose focus during normal usage, even though it should always remain
focused while the prompt bar is mounted (unless a modal is active on top of it).

## Root Cause Analysis

There is **no focus guard mechanism** for the prompt text area. Once focus is lost, nothing brings it back. Focus can be
lost in several scenarios:

1. **After modal dismissal**: When modals like `XPromptSelectModal` or `PromptHistoryModal` are dismissed, Textual's
   built-in focus restoration may not reliably return focus to the `PromptTextArea`. Currently, only the
   `PromptHistoryAction.LOAD` case in `_prompt_bar.py:414` explicitly calls `text_area.focus()`. The cancel cases and
   other callback branches don't restore focus.

2. **Click events**: Clicking on the TUI background or other widgets while the prompt bar is open may clear focus from
   the text area, depending on Textual's click-to-focus behavior.

3. **Background processing**: Timer-driven refreshes, notifications, or agent completion callbacks could potentially
   cause focus shifts.

## Proposed Fix

Add an `on_blur` handler to `PromptTextArea` that automatically refocuses the text area when:

- The widget is still mounted
- No modal screen is currently active (modals legitimately need focus)

Using `call_later` to defer the refocus ensures the check runs after the current event cycle completes (e.g., after a
modal has been fully pushed onto the screen stack).

## Files to Modify

1. `src/sase/ace/tui/widgets/prompt_text_area.py` — Add `on_blur` handler with deferred refocus logic

## Implementation Details

Add two methods to `PromptTextArea`:

- `on_blur()` — Schedules a deferred refocus check via `call_later`
- `_refocus_if_needed()` — Checks if the widget is still mounted and no modal is active, then calls `self.focus()`

The modal check uses `isinstance(self.app.screen, ModalScreen)` to detect whether a modal overlay is currently active.

## Testing

- Run `just check` to verify lint/type/test pass
- Use `sase ace --agent` to verify the prompt bar maintains focus in typical flows
