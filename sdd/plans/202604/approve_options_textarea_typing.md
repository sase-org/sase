---
create_time: 2026-04-02 12:51:11
status: done
prompt: sdd/prompts/202604/approve_options_textarea_typing.md
---

# Fix: Cannot Type in "Additional Prompt" TextArea (ApproveOptionsModal)

## Problem

The user cannot type in the "Additional Prompt" `_PromptTextArea` inside the `ApproveOptionsModal`. The modal opens,
switches are interactive, but character input in the TextArea appears broken.

## Root Cause Analysis

### Textual 8.0.0 Key Event Pipeline (traced from source)

1. `App.on_event` receives each `Key` event
2. **Priority bindings** checked first via `_check_bindings(key, priority=True)`
3. If no priority binding matches, event is forwarded to `focused_widget._forward_event(event)`
4. Focused widget's `_on_key` handler processes the key
5. If event is NOT stopped, it bubbles up the DOM
6. When it reaches `App._on_key`, **non-priority bindings** are checked via `_check_bindings(key, priority=False)`

TextArea's `_on_key` calls `event.stop()` for printable characters, preventing bubbling. And
`TextArea.check_consume_key` returns `True` for printable chars, filtering single-char bindings (like `q`) from the
binding chain. So theoretically, typing should work — but the user reports it doesn't.

### Key Suspects

1. **`q` binding conflict** — The modal defines `("q", "cancel", "Cancel")` as a non-priority binding. While
   `check_consume_key` should filter it, this is the most dangerous binding in a modal with a text input.

2. **`_PromptTextArea._on_key` override** — The `async` override with `# type: ignore[override]` might silently break
   `super()._on_key(event)` in edge cases.

3. **No test coverage for typing** — Existing tests only verify enter/focus/constraints. Zero tests type characters into
   the TextArea. The bug shipped because the gap was never caught.

## Existing Test Gap

All existing tests cover structural behavior (enter triggers approval, ctrl+n cycles focus, constraints lock switches).
**No test verifies that printable characters are actually inserted into the TextArea.** This is the critical gap.

## Plan

### Phase 1: Diagnostic Test

Write and run a targeted async test that:

1. Opens `ApproveOptionsModal` in a minimal test app
2. Navigates focus to the TextArea via `ctrl+n` (x2)
3. Types printable characters (e.g., `"abc"`)
4. Asserts `textarea.text == "abc"`
5. Also tests the `q` key specifically — typing `q` should insert `q`, NOT dismiss the modal

### Phase 2: Root Cause Fix

Based on Phase 1 results:

- **If typing fails**: The `_PromptTextArea._on_key` async override or the modal's `on_key` handler is eating keys. Fix
  the override and/or key interception.
- **If `q` specifically dismisses**: The `q` binding isn't properly filtered by `check_consume_key`. **Remove the `q`
  binding entirely** — `escape` already handles cancel, and `q` is fundamentally incompatible with a text input widget.
- **If typing works in isolation but not in the full app**: Check `AceApp`'s focus management (e.g., the
  `_refocus_if_needed` pattern in `PromptTextArea`) for interference with modal TextArea focus.

### Phase 3: Regression Tests

- Test typing printable chars (including `q`) and verifying insertion
- Test that the modal does NOT dismiss when typing `q` with TextArea focused
- Verify existing tests pass
- Run `just check`
