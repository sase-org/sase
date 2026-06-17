---
create_time: 2026-06-17 09:57:37
status: done
prompt: sdd/prompts/202606/prompt_stack_ctrl_shift_hl_reorder.md
---
# Migrate Prompt Stack Reorder to Ctrl+Shift+H/L

## Goal

Move the prompt input stack's active-pane reorder shortcuts off the prompt-local comma leader and onto `Ctrl+Shift+H` /
`Ctrl+Shift+L`, so pane focus stays on `Ctrl+Shift+J/K` and pane ordering gets its own adjacent Ctrl+Shift chord pair.

## Mapping

Use semantic direction rather than the order the old keys are named:

- `Ctrl+Shift+H`: move the active pane higher / earlier in the stack. This replaces old `,K`.
- `Ctrl+Shift+L`: move the active pane lower / later in the stack. This replaces old `,J`.

This keeps `H` associated with the higher pane position and `L` with the lower pane position in the vertical prompt
stack. It also mirrors the existing `Ctrl+Shift+K` / `Ctrl+Shift+J` focus-navigation direction without reusing `J/K`.

## Current Behavior

- `PromptTextArea._on_key()` already owns prompt-local Ctrl+Shift pane focus navigation:
  - `Ctrl+Shift+J` focuses the next/lower pane.
  - `Ctrl+Shift+K` focuses the previous/higher pane.
  - The handler is lightweight, exact-match only, available in insert and normal mode, and excludes visual mode.
- Prompt-stack pane reorder still lives in the normal-mode comma leader:
  - `_vim_normal_pending.py` maps `,J` to `PromptInputBar.move_active_pane(1)`.
  - `_vim_normal_pending.py` maps `,K` to `PromptInputBar.move_active_pane(-1)`.
- `PromptInputBar.move_active_pane()` syncs live widget text into the stack model, clears prompt completion state, moves
  the selected stack item, and rebuilds the stack with the moved pane active in normal mode.
- The user-facing hints still advertise `,J` / `,K` in the multi-pane normal subtitle.
- The shared help modal currently documents pane focus navigation (`Ctrl+Shift+J/K`) but does not separately document
  pane reordering.
- App-level leader keymaps also use `,J` in non-prompt contexts; those are separate from the prompt text area's comma
  leader and should not be touched.

## Design

1. Add a prompt-local Ctrl+Shift reorder handler in `PromptTextArea._on_key()`.
   - Handle only exact `event.key` values `ctrl+shift+h` and `ctrl+shift+l`.
   - Put the handler beside the existing `ctrl+shift+j` / `ctrl+shift+k` pane-focus handler, before visual/normal-mode
     dispatch and before insert-mode completion handling.
   - Limit it to insert and normal mode. Visual mode should keep its selection semantics.
   - Always `stop()` and `prevent_default()` for those exact chords when in insert/normal mode, even if the stack has
     one pane or the active pane is already at the edge. This avoids accidental fallthrough to text insertion,
     completion acceptance, or global app bindings.
   - Use `delta = -1` for `ctrl+shift+h` and `delta = 1` for `ctrl+shift+l`.

2. Preserve the user's editing mode after reorder.
   - Extend `PromptInputBar.move_active_pane()` to accept an `enter_mode` / `target_mode` argument, defaulting to
     `"normal"` so legacy behavior remains explicit.
   - The new Ctrl+Shift handler should pass the current prompt text area's `_vim_mode`, so reordering from normal mode
     keeps normal mode and reordering from insert mode returns to insert mode after the rebuild.
   - Keep the operation on the established lightweight path: sync in-memory text, clear local completion state, reorder
     the stack model, rebuild the prompt stack, and schedule the existing post-refresh focus/height update. Do not add
     disk I/O, subprocesses, parsing, or new refresh paths on the keypress path.

3. Retire prompt-local `,J` / `,K`.
   - Remove the uppercase `J` and `K` cases from `_handle_stack_leader_key()`.
   - Leave the remaining prompt comma-leader actions intact: `,s`, `,S`, `,P`, and `,f`.
   - Leave the comma prefix behavior itself intact, because the prompt stack still needs it for stash, restore, and
     frontmatter actions, and because it intentionally wins over vim reverse char-search in multi-pane stacks.
   - Retired `,J` / `,K` should become swallowed no-ops after the comma leader is pending, matching the prior retired
     `,j` / `,k` behavior.

4. Update discoverability text.
   - Change the multi-pane normal subtitle from `[,J ,K] move` to a compact `[^⇧H/L] move` style hint.
   - If reordering is available from insert mode, also add a compact insert-mode hint for `[^⇧H/L] move` if it still
     fits cleanly with the existing send, pane-navigation, cancel, and send-all hints.
   - Update docstrings/comments in prompt-stack modules that currently describe `,J` / `,K` as reorder keys.
   - Add `Ctrl+Shift+H/L` to the shared help modal "Prompt Input" section as "Move prompt pane up/down" or equivalent.
   - Do not change `src/sase/default_config.yml`; these prompt-local text-area keys are hardcoded widget behavior, not
     configurable app keymap entries.
   - Do not rewrite historical SDD/prompts/tales except the submitted plan artifact; update source comments and tests
     only.

5. Update tests.
   - Rewrite existing reorder tests in `tests/ace/tui/widgets/test_prompt_stack_keymaps.py` to use `ctrl+shift+h` /
     `ctrl+shift+l`.
   - Add or update regressions proving:
     - `Ctrl+Shift+H` moves the active pane up/higher.
     - `Ctrl+Shift+L` moves the active pane down/lower.
     - live edits are preserved through reorder.
     - normal-mode reorder keeps the moved pane active in normal mode.
     - insert-mode reorder keeps the moved pane active in insert mode, if the implementation exposes the new chords in
       insert mode.
     - retired `,J` / `,K` no longer reorder while other comma-leader actions still dispatch.
     - plain `J` still joins lines and plain `K` behavior is unchanged.
   - Update subtitle/help assertions in `test_prompt_stack_submit_cancel.py` and `test_keymaps_display_help.py`.

## Verification

Run targeted tests first:

- `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps.py`
- `pytest tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`
- `pytest tests/test_keymaps_display_help.py`

Then run full project validation:

- `just check`

## Risks and Mitigations

- `Ctrl+Shift+H` and `Ctrl+Shift+L` support can vary by terminal. Use Textual's exact key names in the code and tests,
  matching the existing `ctrl+shift+j/k/g` convention already used in this codebase. If a terminal collapses
  `Ctrl+Shift+L` to `Ctrl+L`, the existing completion behavior should remain unchanged because the reorder handler
  matches only the shift chord.
- Reordering rebuilds the prompt stack, unlike focus navigation. Preserve mode deliberately and reuse the existing
  rebuild/focus path so the moved pane remains active and the height update remains coalesced through the current
  machinery.
- The app-level `,J` leader binding appears in Agents-tab behavior and command-catalog tests. Scope removal only to the
  prompt text area's local comma leader so unrelated leader keymaps are unaffected.
- The prompt subtitle is already dense. Prefer a compact `[^⇧H/L] move` hint and avoid adding more prose to the live
  footer.
