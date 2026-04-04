---
create_time: 2026-04-04 10:41:58
status: done
---

# Fix: Prompt input freeze caused by synchronous prettier auto-wrap in INSERT mode

## Problem

While typing in the prompt input widget, the UI can appear frozen when auto-wrap/prettier kicks in on large prompts. The
freeze reproduces most readily when editing long multi-line markdown blocks (like `sase ace` snapshots), where each
additional printable character can trigger expensive reflow work.

## Root Cause

In `PromptTextArea._on_key()` (`src/sase/ace/tui/widgets/prompt_text_area.py`), INSERT-mode printable input ends with:

- `await self._format_with_prettier()`

That runs in the key event handler itself, so one key event is not fully handled until prettier subprocess execution and
cursor remapping complete. For large texts this introduces high per-keystroke latency, which feels like a hard freeze.

Two compounding factors make this worse:

1. Reflow runs against the full prompt, not just the edited line.
2. Formatting is triggered repeatedly during active typing once the content is near/over wrap boundaries.

## Fix Strategy

Make prettier reflow **asynchronous and coalesced**:

1. Replace inline `await self._format_with_prettier()` in `_on_key()` with a fire-and-forget scheduler.
2. Add scheduler state to `TextFormattingMixin` so at most one background formatting task runs at a time.
3. Coalesce multiple typing bursts into minimal formatter runs by tracking request generations.
4. Cancel any outstanding formatting task when the widget unmounts.

This preserves current wrap behavior and cursor restoration logic, but removes key-handler blocking.

## Implementation Plan

1. Update `TextFormattingMixin`:
   - Add task/request state fields for scheduling/coalescing.
   - Add `_schedule_prettier_format()` and internal async drain loop.
   - Add `_cancel_pending_prettier_format()` helper.
2. Update `PromptTextArea`:
   - Initialize the new scheduling fields in `__init__`.
   - Switch INSERT-mode auto-wrap trigger to call scheduler instead of awaiting formatter.
   - Cancel pending format tasks on unmount.
3. Add regression tests:
   - Verify scheduler coalesces multiple requests while a format run is active.
   - Verify pending format task is cancellable/cleared.
4. Run repo checks (`just install` if needed, then `just check`) and iterate on failures.

## Validation

- Manual behavior target: typing remains responsive in prompt input even with large markdown content.
- Automated target: existing prompt formatting and vim-mode tests continue to pass; new scheduling tests guard against
  reintroducing blocking behavior.
