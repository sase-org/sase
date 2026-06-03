---
create_time: 2026-06-02 21:18:27
status: done
prompt: sdd/prompts/202606/jump_all_scroll.md
---
# Plan: Fix Jump to Entry Ctrl+D/U Scrolling

## Context

The "Jump to Entry" panel is implemented by `JumpAllModal` in `src/sase/ace/tui/modals/jump_all_modal.py`. It renders
its entries inside `#jump-all-scroll`, a `VerticalScroll`, but the modal's `on_key` handler currently intercepts every
key. Recognized hint keys jump to an entry; escape closes; backtick can jump back; every other key is prevented,
stopped, and dismissed.

That catch-all path explains the bug: `ctrl+d` and `ctrl+u` never reach a scroll action while the panel is open. Several
neighboring ACE modals already use modal-local `ctrl+d` / `ctrl+u` bindings or explicit scroll actions, so this is a
TUI/modal input handling fix, not shared backend behavior.

## Implementation Plan

1. Update `JumpAllModal` so `ctrl+d` and `ctrl+u` are handled before the generic non-hint dismissal branch.
   - Scroll `#jump-all-scroll` by half of its visible content region, matching the ACE detail-panel and nearby modal
     behavior.
   - Prevent and stop the key event after scrolling so the underlying app does not also process the same key.
   - Keep escape, hint selection, backtick history, and unknown-key dismissal behavior unchanged.

2. Add modal-local actions/bindings only if they improve consistency with the rest of the modal code.
   - Prefer the smallest change that works reliably with the existing `on_key` catch-all.
   - Do not change `default_config.yml` unless investigation shows a new configurable action is necessary; the existing
     default scroll keymaps already name `ctrl+d` / `ctrl+u`, and other modal-local scroll controls are hard-coded.

3. Add focused tests in `tests/ace/tui/test_jump_to_entry_hints.py`.
   - Verify `ctrl+d` scrolls `#jump-all-scroll` down by half a page and does not dismiss the modal.
   - Verify `ctrl+u` scrolls up by half a page and does not dismiss the modal.
   - Keep the existing uppercase hint-selection test green to guard against breaking jump dispatch.

4. Run targeted tests for the jump-to-entry modal first.
   - `python -m pytest tests/ace/tui/test_jump_to_entry_hints.py`

5. Because source/test files will be changed, run the repository-required final check.
   - If needed, run `just install` first per repo memory.
   - Then run `just check`.

## Risks and Notes

- The main risk is Textual event-order behavior: bindings alone may not fire if `on_key` consumes the key first.
  Handling the scroll keys explicitly inside `on_key` avoids relying on ambiguous ordering.
- This change should not affect inline apostrophe jump mode, notification jump mode, or app-level detail scrolling
  because it is scoped to `JumpAllModal`.
