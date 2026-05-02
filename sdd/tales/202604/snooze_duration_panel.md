---
create_time: 2026-04-29 21:49:01
status: done
prompt: sdd/prompts/202604/snooze_duration_panel.md
---
# Snooze Duration Panel UX Plan

## Product Direction

The current snooze panel works functionally, but it reads like a raw shortcut list. I will turn it into a focused popup
decision panel that feels consistent with the rest of Ace while making the common path obvious: choose a short preset,
choose tomorrow morning, or enter a custom duration.

The same duration-choice interaction should also power Temporary Model Override so users do not have to learn two
different duration pickers. The override flow still needs its special “until cleared” option and its distinct result
handling, but the panel mechanics, custom-duration validation, and visual language should be shared.

## Design Goals

- Make snoozing feel like an intentional, reversible notification action rather than a hidden command side effect.
- Present choices as scannable action rows with clear labels and secondary context, not just terse key/value text.
- Preserve keyboard-first speed: numeric presets, `c` for custom, `esc`/`q` to cancel, and `esc` from custom input to
  return to presets.
- Keep behavior reliable by centralizing duration parsing, custom input state, cancellation semantics, and validation
  messages.
- Keep the implementation small enough to land safely in the current TUI modal architecture.

## Technical Plan

1. Create a reusable duration-choice modal module under `src/sase/ace/tui/modals/`.
   - Define a `DurationChoice` model describing key, title, optional subtitle, return value, and visual tone.
   - Implement a shared `DurationChoiceModal` with preset bindings generated from provided choices, custom input
     support, validation, and cancel/back semantics.
   - Use a cancel sentinel so `None` can remain a legitimate value for Temporary Model Override’s “until cleared”
     option.

2. Rebuild `SnoozeDurationModal` as a thin wrapper around the shared modal.
   - Keep its public result type: `timedelta | datetime | None`.
   - Keep existing presets: 15 minutes, 1 hour, 4 hours, tomorrow morning.
   - Improve copy and layout: title like “Snooze Notification”, action-oriented rows, short secondary descriptions, and
     a visible custom entry area only after `c`.
   - Preserve existing callback behavior in `NotificationModal`.

3. Reuse the same shared modal in `TemporaryLLMOverrideModal`.
   - Replace the private `_DurationPickerModal` implementation with a wrapper around `DurationChoiceModal`.
   - Preserve all current preset values, including `None` for “Until cleared”.
   - Preserve `_on_duration_picked` semantics by using the shared cancel sentinel.

4. Update TUI styles once, in a shared selector block.
   - Give the duration panel a centered popup frame, clear title area, compact rows, subdued secondary text, and error
     styling.
   - Keep existing modal selectors compatible where tests or screenshots may query by id.

5. Strengthen tests.
   - Existing snooze and override tests should continue to pass.
   - Add focused tests for shared cancel sentinel behavior, custom validation, and the “None is a real duration result”
     branch.
   - Update tests only where selector names or presentation internals change.

## Verification

- Run focused tests:
  - `pytest tests/test_notification_snooze_modal.py tests/test_notification_modal.py tests/test_temporary_llm_override_modal.py tests/test_temporary_llm_override_phase5.py`
- Because this repo requires it after changes, run:
  - `just install`
  - `just check`

## Non-Goals

- No changes to notification persistence semantics.
- No keymap changes.
- No new dependency or broad TUI redesign.
