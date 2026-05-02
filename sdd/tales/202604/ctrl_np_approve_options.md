---
create_time: 2026-04-01 10:10:03
status: done
prompt: sdd/prompts/202604/ctrl_np_approve_options.md
---

# Plan: Add ctrl+n / ctrl+p Navigation to ApproveOptionsModal

## Problem

The ApproveOptionsModal currently relies on Textual's built-in `tab`/`shift+tab` for cycling focus between its three
focusable widgets. The user wants `ctrl+n` (next) and `ctrl+p` (prev) as the primary navigation keys, consistent with
standard terminal navigation conventions. The `q` key should remain exclusively a quit/cancel action.

## Current State

- **Navigation**: Tab/Shift+Tab (Textual built-in focus cycling)
- **Cancel**: `q` and `escape` (via BINDINGS → `action_cancel`)
- **Approve**: `enter` (via BINDINGS + `on_key` interceptor for TextArea focus edge case)
- **Footer**: `enter=Approve  space=Toggle  tab=Next  q=Back`

## Design

### Approach: Extend the existing `on_key` handler

The modal already has an `on_key` method that intercepts `enter` to ensure it works regardless of which widget has focus
(particularly the TextArea, which would otherwise consume it). We extend this same pattern for `ctrl+n` and `ctrl+p`,
calling Textual's built-in `focus_next()` and `focus_previous()` methods.

This approach is necessary because:

- `ctrl+n`/`ctrl+p` must work even when the TextArea has focus
- Textual's BINDINGS system wouldn't reliably intercept these before the TextArea consumes them
- The `on_key` pattern is already proven by the `enter` key fix

### What stays the same

- `tab`/`shift+tab` continue to work (Textual built-in) — we're adding, not replacing
- `q` remains bound to cancel via BINDINGS (works when Switch has focus; when TextArea has focus, `q` inserts the
  character, which is correct — `escape` is the universal cancel)
- No changes to `default_config.yml` since this modal's keybindings are self-contained

## Changes

### 1. `src/sase/ace/tui/modals/approve_options_modal.py`

- Extend `on_key` to handle `ctrl+n` → `self.focus_next()` and `ctrl+p` → `self.focus_previous()`, with
  `prevent_default()` + `stop()` to prevent TextArea consumption
- Update footer text: replace `tab=Next` with `ctrl+n=Next  ctrl+p=Prev`

### 2. `tests/test_approve_options_modal.py`

- Add unit tests for `ctrl+n`/`ctrl+p` in `on_key` (verify focus methods are called)
- Add async integration tests verifying focus actually cycles through widgets in both directions
