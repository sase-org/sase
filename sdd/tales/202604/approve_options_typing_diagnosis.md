---
create_time: 2026-04-02 13:21:55
status: done
prompt: sdd/prompts/202604/approve_options_typing_diagnosis.md
---

# Fix: Cannot Type in ApproveOptionsModal TextArea (Root Cause Diagnosis)

## Problem

After removing the `q` binding from `ApproveOptionsModal`, typing in the "Additional Prompt" `_PromptTextArea` still
doesn't work in the real `sase ace` application. The existing tests pass, but they use a minimal `_TestApp` that doesn't
replicate the real AceApp environment.

## Deep Analysis of the Textual 8.0.0 Key Event Pipeline

I traced the complete key event pipeline in Textual 8.0.0:

1. **`App.on_event`** receives the raw Key event (with `is_forwarded=False`)
2. **Priority binding check**: `_check_bindings(key, priority=True)` using `reversed(screen._binding_chain)` — walks
   from App down to focused widget, filtering bindings via `check_consume_key` on the focused widget
3. **Forward to focused widget**: `forward_target._forward_event(event)` — sets `is_forwarded=True`, posts to widget's
   message queue
4. **Widget processes**: `_on_key` handler called — TextArea inserts character, calls `event.stop()` +
   `event.prevent_default()`
5. **Bubbling**: If stopped, stops here. Otherwise bubbles: widget → parent → ... → ModalScreen → App
6. **App receives bubbled event**: `App.on_event` catches it (forwarded), falls to
   `else → super().on_event() → _on_message()`
7. **`App._on_key`**: Non-priority binding check via `_modal_binding_chain` (truncated at first ModalScreen — excludes
   App-level bindings)
8. **`App.on_key`** (EventHandlersMixin): Mode handling (fold, checkout, copy, ancestry, leader, bang, custom modes)

### Key findings from `_binding_chain`

- `check_consume_key` is applied during chain construction — TextArea's implementation returns True for printable chars,
  deleting matching bindings from the chain copies
- `_modal_binding_chain` truncates at the first `is_modal` node — when ApproveOptionsModal is active, App-level bindings
  (a, b, c, j, k, q, etc.) are **excluded** from non-priority checks
- `_no_default_action` flag (set by `event.prevent_default()`) breaks MRO traversal in `_get_dispatch_methods`,
  preventing double-dispatch of `_on_key` handlers

### Theoretical conclusion

With the TextArea focused, typing SHOULD work — TextArea.\_on_key inserts the character, stops the event, and no
app-level binding interferes thanks to modal truncation + check_consume_key filtering.

**Yet the user reports typing doesn't work.** This means the failure is in an assumption, not the pipeline.

## Hypotheses (Ranked by Likelihood)

### H1: Tests don't reproduce the real environment

The existing tests use `_TestApp(App)` with zero bindings and no EventHandlersMixin. The real `AceApp` has:

- 108+ app-level bindings (every printable character)
- `EventHandlersMixin.on_key` with mode handling and `_custom_mode_prefixes` check
- `PromptTextArea._refocus_if_needed` (with ModalScreen guard, but worth verifying)
- Multiple screen stacking (PlanApprovalModal → ApproveOptionsModal)

The bug only manifests in the real app because of something the minimal test app doesn't have.

### H2: Focus never reaches the TextArea

`on_mount` focuses the first Switch. The user must press `ctrl+n` twice to reach the TextArea. But what if:

- `focus_next()` skips the TextArea (e.g., CSS `display: none` or `disabled` state issue)
- Focus reaches the TextArea but is immediately stolen (by a timer, callback, or the main PromptTextArea)
- The user clicks the TextArea expecting mouse-based focus, but ModalScreen intercepts clicks

### H3: EventHandlersMixin.on_key interferes from the App level

When an event bubbles from the modal to the App, `EventHandlersMixin.on_key` fires. It checks:

```python
elif event.key in self._custom_mode_prefixes:
    self._custom_mode_active = self._custom_mode_prefixes[event.key]
    event.prevent_default()
    event.stop()
```

If any printable character is a custom mode prefix, it would be consumed at the App level when focus is on a Switch
(where TextArea.check_consume_key doesn't filter it).

### H4: The `_on_key` async override has a subtle runtime issue

The `# type: ignore[override]` on `_PromptTextArea._on_key` suppresses a mypy error. While both TextArea.\_on_key and
the override are async, there might be a subtle dispatch issue in how Textual's `_get_dispatch_methods` resolves the
override chain.

## Plan

### Phase 1: Reproduce the failure with a realistic test

Write a diagnostic async test that uses the **real AceApp** (or a close approximation) to reproduce the typing failure.
This is the critical step — once we can reproduce it, fixing it is straightforward.

**Test A — App-level bindings interference:** Create a test app with the same single-character bindings as AceApp. Push
ApproveOptionsModal. Navigate to TextArea. Type. Assert insertion.

**Test B — Double-stacked modals:** Push PlanApprovalModal first, then trigger action_approve_options to push
ApproveOptionsModal on top. Navigate to TextArea. Type. Assert insertion.

**Test C — EventHandlersMixin.on_key:** Create a test app with EventHandlersMixin (or a mock of it). Push
ApproveOptionsModal. Type with focus on Switch vs TextArea. Check if any events leak to the mixin's on_key.

### Phase 2: Fix based on diagnosis

Depending on which test(s) fail:

**If H1/H3 confirmed (app-level interference):**

- Add explicit key interception in `ApproveOptionsModal.on_key` that stops printable chars when TextArea is focused
  (preventing them from bubbling to App)
- Or: override `check_consume_key` at the modal level to claim printable chars when TextArea is a child

**If H2 confirmed (focus issue):**

- Auto-focus the TextArea when modal opens (instead of the first Switch)
- Or: add click-to-focus support for the TextArea within the modal
- Or: fix whatever is stealing focus

**If H4 confirmed (async override issue):**

- Replace the `_on_key` override with a different approach:
  - Use `on_key` message handler instead
  - Or: use Textual's binding system for enter interception
  - Or: make the override synchronous if that's what Textual expects

### Phase 3: Update tests and verify

- Update the existing test suite to use a more realistic app environment
- Ensure all 3560+ tests pass
- Run `just check`
