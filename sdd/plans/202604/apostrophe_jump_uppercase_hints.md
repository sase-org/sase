---
create_time: 2026-04-27 13:22:53
status: done
prompt: sdd/prompts/202604/apostrophe_jump_uppercase_hints.md
---
# Support A-Z Hints for Apostrophe Jump Mode

## Goal

Make the inline `jump_to_entry` flow, activated by the apostrophe keymap (`'` / `apostrophe`), reliably support the full
jump hint alphabet including uppercase `A-Z`, matching the already-supported cross-tab backtick flow
(`jump_to_all_entries` / `` ` ``).

## Current Understanding

- The default keymap already binds:
  - `jump_to_entry: "apostrophe"`
  - `jump_to_all_entries: "grave_accent"`
- Both jump flows use the same hint alphabet in `src/sase/ace/tui/actions/navigation/jump_hints.py`:
  - `1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ`
- The cross-tab backtick modal assigns and handles hints inside `JumpAllModal`.
- The inline apostrophe flow assigns hints via `build_jump_hint_maps()` and renders them through the current tab's left
  panel:
  - ChangeSpecs tab: `ChangeSpecList`
  - Agents tab: `AgentList`, including collapsed banner hints
  - AXE tab: `BgCmdList`
- Existing tests prove the hint alphabet contains uppercase characters and that hint markers can render, but they do not
  fully exercise the inline apostrophe mode with uppercase hint selection after more than 36 visible targets.

## Likely Risk

The implementation may already display uppercase hints for apostrophe mode because it shares `JUMP_HINT_CHARS`. The
practical failure mode to guard against is dispatch: Textual key events expose both `event.key` and `event.character`,
and uppercase printable input may arrive differently across direct tests, pilot tests, or terminal input. If the inline
mode stores hint `"A"` but handles only a normalized or lowercased key value, the UI can show `[A]` while pressing `A`
does not jump.

## Implementation Plan

1. Add focused tests for the inline apostrophe path, not just the shared hint allocator.
   - Cover at least 37 visible entries so the first uppercase hint (`A`) is allocated.
   - Assert `action_jump_to_entry()` populates `_entry_jump_hint_to_index["A"]`.
   - Assert `_entry_jump_index_to_hint[target] == "A"` for the expected target.
   - Assert `_handle_entry_jump_key("A")` jumps to the expected target and exits jump mode.

2. Cover rendering where the apostrophe flow actually paints left-panel hints.
   - For ChangeSpecs, render/update with an `_entry_jump_index_to_hint` map containing an uppercase hint and assert
     `[A]` appears.
   - If the current display helpers make this easier at the widget level, keep this test widget-focused rather than
     launching the whole TUI.

3. Add an event-normalization helper only if the tests or code inspection show a real gap.
   - Prefer a small helper local to jump handling, such as resolving printable `event.character` before falling back to
     `event.key`.
   - Use it for inline apostrophe mode and consider using the same helper in `JumpAllModal` for consistency.
   - Do not change the hint alphabet order or the default keymap.

4. Keep behavior unchanged for non-printable controls.
   - `escape` must still cancel inline jump mode.
   - `apostrophe` must still perform the inline back-jump behavior.
   - `grave_accent` must still perform back-jump inside the cross-tab modal.

5. Verify with targeted tests first.
   - Run the new/changed jump-hint tests.
   - Run keymap tests if key handling or display names change.
   - After any repo file changes, run `just check` as required by repo memory. If dependencies are stale, run
     `just install` first per workspace instructions.

## Expected Files

- `src/sase/ace/tui/actions/event_handlers.py` or a nearby navigation helper, only if event normalization is needed.
- `src/sase/ace/tui/modals/jump_all_modal.py`, only if sharing the normalization helper with the backtick modal is
  appropriate.
- `tests/ace/tui/test_jump_to_entry_hints.py` for focused uppercase coverage.
- Possibly a small helper test module if a new helper is introduced.

## Non-Goals

- Do not change the default keybindings.
- Do not replace the existing single-character hint alphabet with multi-character hints.
- Do not refactor unrelated keymap, footer, or modal behavior.
