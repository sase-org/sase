---
create_time: 2026-05-12 20:15:50
status: done
prompt: sdd/prompts/202605/agent_revival_keymaps.md
---
# Agent Revival Panel Keymaps Plan

## Goal

Make the agent revival modal use `ctrl+n` and `ctrl+p` to move the selected revival entry down and up, matching the
generic modal navigation behavior and the command palette convention. Preserve the archive pagination affordance by
moving the existing `ctrl+n` “load more” binding to a different trigger.

## Current Behavior

- `DismissedAgentSelectModal` includes `OptionListNavigationMixin.NAVIGATION_BINDINGS`, which already defines:
  - `ctrl+n` -> `next_option`
  - `ctrl+p` -> `prev_option`
- The same modal then adds a priority binding:
  - `ctrl+n` -> `load_more`
- Because the “load more” binding is priority-bound on the same key, `ctrl+n` loads the next archive page instead of
  moving the highlighted revival entry.
- The modal hint currently advertises `^n: more` when another archive page is available.

## Design

Use `pagedown` as the new “load more” trigger.

Rationale:

- It maps naturally to loading the next page of archive-backed results.
- It is non-printing, so it will not interfere with typing structured archive queries into the focused filter input.
- It does not conflict with the inherited `ctrl+n`/`ctrl+p` row navigation pair.
- It keeps `ctrl+d`/`ctrl+u` available for preview scrolling, which the modal already advertises and implements.

## Implementation Steps

1. Update `src/sase/ace/tui/modals/revive_agent_modal.py`.
   - Change the `load_more` binding from `ctrl+n` to `pagedown`.
   - Leave `OptionListNavigationMixin.NAVIGATION_BINDINGS` intact so `ctrl+n` and `ctrl+p` control the highlighted
     revival entry.
   - Update the hints text from `^n: more` to a PageDown label.

2. Add focused regression coverage in `tests/ace/tui/modals/test_revive_agent_modal.py`.
   - Cover `ctrl+n` moving the highlighted row down and `ctrl+p` moving it back up in the revival modal.
   - Include an archive cursor in that test or a companion test so the old conflict would have been observable.
   - Cover the new `pagedown` trigger invoking `load_more` with the current archive cursor, and assert `ctrl+n` does not
     perform pagination.

3. Verify locally.
   - Run the focused revive modal tests first: `python -m pytest tests/ace/tui/modals/test_revive_agent_modal.py`
   - Because this repo requires it after code changes, run `just install` if needed and then `just check` before
     finishing.

## Risks

- `pagedown` may have default list-scroll behavior in some Textual widgets, so the modal binding should remain
  priority-bound for the pagination action.
- Archive loading is asynchronous in the mounted modal path; tests should wait for the initial empty query page before
  checking cursor-sensitive behavior.
