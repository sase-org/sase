---
create_time: 2026-03-31 23:52:21
status: done
prompt: sdd/prompts/202603/fix_enter_keymap_approve_options.md
---

# Fix broken `<enter>` keymap in ApproveOptionsModal

## Problem

The `<enter>` key binding in `ApproveOptionsModal` doesn't fire when the `TextArea` widget (`#coder-prompt-input`) has
focus. The footer advertises `enter=Approve` unconditionally, but pressing enter while the TextArea is focused inserts a
newline instead of approving.

## Root Cause

Commit `b02f236e` changed the coder prompt widget from `Input` to `TextArea` for multi-line support. Textual's built-in
`TextArea` consumes the `enter` key event to insert a newline _before_ it bubbles up to the modal's `BINDINGS`. The
modal-level `("enter", "approve", "Approve")` binding only fires when a `Switch` has focus.

## Approach

Add an `on_key()` handler to `ApproveOptionsModal` that intercepts `enter` regardless of which child widget has focus,
and routes it to `action_approve()`. This is the established pattern in this codebase — `prompt_history_modal.py` and
`user_question_modal.py` both use `on_key()` to intercept keys that child widgets would otherwise swallow.

## Changes

### 1. `src/sase/ace/tui/modals/approve_options_modal.py`

- Import `events` from `textual`.
- Add `on_key(self, event: events.Key)` method:
  - If `event.key == "enter"`: call `event.prevent_default()`, `event.stop()`, then `self.action_approve()`.
  - This ensures `enter` always means "approve", matching the footer hint.

### 2. Tests

- Test that `enter` triggers approval when the `TextArea` is focused (the bug scenario).
- Test that `enter` still works when a `Switch` is focused (regression check).
