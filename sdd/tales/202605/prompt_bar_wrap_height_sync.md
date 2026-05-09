---
create_time: 2026-05-09 11:42:28
status: done
prompt: sdd/prompts/202605/prompt_bar_wrap_height_sync.md
---
# Plan: Prompt Bar Wrapped Height Synchronization

## Problem

GitHub Actions intermittently fails
`tests/ace/tui/widgets/test_prompt_virtual_wrap.py::test_initial_long_prompt_is_preserved_and_bar_grows_to_wrap` with
the prompt bar height one row smaller than the current wrapped document height requires.

The CI assertion shows:

- `PromptTextArea.wrapped_document.height == 7`
- `PromptInputBar._get_visual_line_count() == 7`
- expected bar height is `7 + 2 == 9`
- actual `PromptInputBar.styles.height == 8`

That means the prompt text and the visual-line calculation are correct at assertion time, but the bar's stored height
was last updated while Textual still reported one fewer wrapped row. This is a synchronization issue between Textual's
`TextArea` wrap recalculation and the parent `PromptInputBar` height update.

## Root Cause Hypothesis

`PromptInputBar` currently updates its height on:

- mount, via one `call_after_refresh(self._update_height)`;
- `TextArea.Changed`;
- `PromptInputBar.on_resize`;
- completion panel show/hide.

For initial text, no `TextArea.Changed` message is posted by user input. Textual recalculates a `TextArea`'s wrapped
document during mount/resize and after layout-dependent width changes. On CI, the single mount-time deferred height
update can run before the child `TextArea` has finished its final wrap pass at the real content width. Once Textual
later updates `wrapped_document.height`, nothing notifies `PromptInputBar`, so the bar remains at the stale height.

The bug is therefore in the widget contract: the parent depends on the child's wrapped height, but it does not listen to
the child's layout/resize-driven rewrap events.

## Product Behavior To Preserve

- Initial long prompts must remain byte-for-byte unchanged.
- Long logical lines should soft-wrap visually, not become hard newlines.
- The prompt bar should grow to fit visual rows plus border rows, clamped to available screen height.
- Completion panels should continue adding their reserved rows to the same height calculation.
- Explicit user newlines should remain the only reason line numbers are shown.

## Implementation Plan

1. Add a lightweight notification path from `PromptTextArea` to `PromptInputBar` after layout-driven wrapping changes.
   - Override `PromptTextArea._on_resize()`, keep the existing `super()._on_resize()` and `scroll_cursor_visible`
     behavior, then ask the parent bar to update height after refresh.
   - Use the existing `_find_prompt_bar()` helper so this stays scoped to prompt input and avoids coupling generic
     Textual internals into the parent.

2. Make `PromptInputBar` height updates robust to Textual wrap timing.
   - Add a small helper such as `_schedule_height_update()` that calls `_update_height()` immediately and again
     `call_after_refresh`.
   - Use that helper from mount, text changes, parent resize, and child resize notifications.
   - Keep direct `_update_height()` for completion show/hide where the panel state is already changed and tests expect
     synchronous behavior.

3. Strengthen the regression test without changing product expectations.
   - Add a focused test that simulates the CI stale-height state: manually set the bar height to a one-row-stale value,
     trigger the child text area's resize handler, pause, and assert the bar catches up to the current
     `wrapped_document.height`.
   - Keep the existing failing test as the end-to-end initial prompt coverage.

4. Verify with targeted tests first, then repo checks.
   - Run `just test tests/ace/tui/widgets/test_prompt_virtual_wrap.py`.
   - Because this repo requires it after non-bead changes, run `just check` before final response. If environment setup
     blocks the full check, report the blocker and the targeted test result.

## Risks

- Textual private methods are involved because `PromptTextArea` already overrides `_on_resize()`. Keep the change small
  and preserve the existing call to `super()._on_resize()`.
- Calling height updates too aggressively could cause extra layout passes. The update is cheap and only applies while
  the prompt bar is mounted; scheduling one deferred pass mirrors the existing mount/resize pattern.
- Tests should assert behavior, not a private event order. The new test should only verify that a child wrap/resize
  notification resynchronizes the parent height.
