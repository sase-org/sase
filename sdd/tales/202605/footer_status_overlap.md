---
create_time: 2026-05-21 12:41:43
status: done
prompt: sdd/prompts/202605/footer_status_overlap.md
---
# Plan: Restore ACE Keybinding Footer Visibility

## Problem

After the footer overflow work, the ACE keybinding footer can disappear in normal one-line states, including the AXE
status badge such as `RUNNING` or `STOPPED`.

The root cause is a layout overlap between two bottom-docked widgets:

- `KeybindingFooter` is `dock: bottom` and now often auto-sizes to two rows: one border row plus one content row.
- The built-in Textual `Footer` is also bottom-docked and is composed after `KeybindingFooter`.
- In the common one-line footer state, `KeybindingFooter` places its actual content/status row on the terminal's last
  line. The built-in `Footer` occupies that same last line and covers it.
- In multi-line mode, only the rows above the built-in `Footer` remain visible, so the final footer row can still be
  clipped.

The previous `min-height: 3` masked the overlap by leaving enough vertical space that the keybinding content did not
land on the row covered by Textual's built-in `Footer`.

## Implementation

1. Preserve the custom `KeybindingFooter` as the source of conditional keybindings and AXE/background-command status.
2. Remove the competing built-in `Footer` from the ACE app composition, since global Textual bindings are intentionally
   not surfaced there and this app already owns the footer UX through `KeybindingFooter`.
3. Keep the custom footer docked at the bottom and retain the border/top-padding behavior introduced by the overflow
   change.
4. Add a focused regression test that runs the real ACE composition and asserts the custom footer content and AXE status
   render into exported output in the ordinary one-line state.
5. Add or adjust a regression for LEADER/grid mode so the final grid row is not hidden by another bottom-docked widget.

## Validation

1. Run focused footer/widget tests.
2. Run focused ACE visual/footer tests, including the leader overflow snapshots.
3. Run `just check` after code changes, per repo instructions.

## Expected Result

The custom footer is visible in normal mode and multi-line modes. AXE status badges render reliably because no second
bottom-docked footer can cover the custom footer's content row.
