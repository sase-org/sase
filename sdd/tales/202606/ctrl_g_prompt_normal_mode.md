---
create_time: 2026-06-21 10:15:51
status: done
prompt: sdd/prompts/202606/ctrl_g_prompt_normal_mode.md
---
# Plan: Enable Ctrl+G Prompt Prefix in Normal Mode

## Goal

Make `Ctrl+G` inside the ace TUI prompt input widget behave like the prompt-local prefix in both INSERT and NORMAL mode.
Today INSERT-mode `Ctrl+G` opens the same prompt-local keymap table as NORMAL-mode `g`, including the hint panel, while
NORMAL-mode `Ctrl+G` is only swallowed to prevent the app-level `Ctrl+G` binding from firing. The change should make
NORMAL-mode `Ctrl+G` activate the same continuation keymaps and show the same hint content shown by INSERT-mode
`Ctrl+G`.

## Current Shape

- `PromptTextArea._on_key()` routes keypresses before Textual's default `TextArea` handling.
- INSERT-mode `Ctrl+G` is handled by `_handle_insert_g_prefix_key()`, which sets `_insert_g_prefix_pending`, calls
  `_show_insert_g_prefix_hints()`, and dispatches the continuation through
  `PromptInputBar.dispatch_g_prefix_key(..., target_mode="insert")`.
- NORMAL-mode `g` is handled by the vim normal-mode path. `_handle_normal_motion_key()` sets `_pending_keys = "g"`,
  `_update_count_display()` shows prompt `g` prefix hints, and `_handle_normal_pending_key()` dispatches prompt-specific
  continuations through `PromptInputBar.dispatch_g_prefix_key()`.
- NORMAL-mode `Ctrl+G` currently reaches the NORMAL branch in `_on_key()` and is swallowed after
  `_handle_normal_mode_key()` returns false. This protects the focused prompt from the app-level `Ctrl+G` binding but
  never starts a prefix or shows hints.
- `PromptInputBar.show_g_prefix_hints(prefix_label="^G", include_editor=True)` already renders the INSERT-mode `Ctrl+G`
  hint surface, including the editor continuation.
- Tests already cover normal `g` hints, insert `Ctrl+G` hints, insert continuation dispatch, and app-level binding
  shadowing. One test currently asserts the broken behavior: `test_focused_normal_mode_ctrl_g_is_swallowed`.

## Design

Add a NORMAL-mode `Ctrl+G` prefix path that reuses the existing prompt-local machinery instead of creating a second
dispatch table.

The intended behavior:

- Pressing `Ctrl+G` while the prompt text area is in NORMAL mode starts a prompt-local prefix, consumes the key, and
  prevents the app-level `Ctrl+G` binding from firing.
- The hint panel appears immediately and matches INSERT-mode `Ctrl+G` hints: `^G` prefix label, editor entry included,
  same prompt-specific continuation list, same escape subtitle.
- A second `g` or `Ctrl+G` opens the same editor action that INSERT-mode `Ctrl+G g` / `Ctrl+G Ctrl+G` opens.
- Prompt-specific continuations such as `Ctrl+G <enter>`, `Ctrl+G -`, `Ctrl+G =`, `Ctrl+G s`, `Ctrl+G S`, `Ctrl+G p`,
  `Ctrl+G P`, `Ctrl+G j`, and `Ctrl+G k` dispatch through `PromptInputBar.dispatch_g_prefix_key()`.
- NORMAL-mode pane focus/reorder continuations should keep the target pane in NORMAL mode, matching normal `g`
  semantics. INSERT-mode `Ctrl+G` should continue passing `target_mode="insert"`.
- `Esc` cancels the pending `Ctrl+G` prefix, hides hints, and stays in NORMAL mode.
- Unknown continuations hide hints and do not insert text or trigger app-level bindings.

## Implementation Approach

1. Introduce a small NORMAL-mode `Ctrl+G` prefix state in `PromptTextArea`, parallel to `_insert_g_prefix_pending`.
   - Keep the state local to the prompt widget.
   - Avoid synchronous I/O or other event-loop work in key handlers.
   - Ensure blur, mode transitions, prompt search, and stack mutations clear the prefix and hide the hint panel.

2. Add a focused helper for the NORMAL-mode `Ctrl+G` prefix in `_prompt_text_area_key_handling.py` or the prompt text
   area action mixin.
   - Initial `Ctrl+G`: mark the prefix pending and call the same hint renderer used by INSERT mode:
     `show_g_prefix_hints(prefix_label="^G", include_editor=True)`.
   - Continuation `g` or `Ctrl+G`: clear the prefix and call `action_open_editor()`.
   - Continuation `Esc`: clear the prefix and consume the key.
   - Other continuations: clear the prefix, call `dispatch_g_prefix_key(key, target_mode="normal")`, and consume the
     key.

3. Integrate the helper early in `_on_key()`.
   - Run it before the existing NORMAL-mode `_handle_normal_mode_key()` branch so `Ctrl+G` starts the prompt prefix
     instead of falling into the current swallowed fallback.
   - Keep INSERT-mode handling unchanged.
   - Keep visual mode behavior unchanged unless product requirements later call for `Ctrl+G` there.

4. Preserve the existing NORMAL-mode `g` path.
   - Do not change vim `g` commands such as `gg`, `ge`, `gE`, `gu`, `gU`, or `g~`.
   - Do not duplicate `_PROMPT_G_PREFIX_BINDINGS`; all prompt-specific continuations should continue using
     `PromptInputBar.dispatch_g_prefix_key()`.

5. Update tests.
   - Replace `test_focused_normal_mode_ctrl_g_is_swallowed` with a test asserting NORMAL-mode `Ctrl+G` starts the
     prompt-local prefix, shows the same `^G` hint panel, and still shadows the app-level `Ctrl+G` binding.
   - Add widget-level coverage in `test_prompt_g_prefix_hints.py` for NORMAL-mode `Ctrl+G` hint rendering, including the
     editor hint and prompt-specific entries.
   - Add NORMAL-mode continuation tests for `Ctrl+G g` / `Ctrl+G Ctrl+G` editor dispatch and at least one non-editor
     prompt-specific continuation, such as `Ctrl+G =` or `Ctrl+G s`.
   - Add cancellation/unknown continuation coverage: `Esc` hides hints and leaves NORMAL mode active; unknown keys hide
     hints without text insertion or side effects.
   - Add multi-pane coverage if needed to verify `Ctrl+G k` from NORMAL mode focuses the previous pane and leaves it in
     NORMAL mode.

6. Verify.
   - Run focused tests first:
     - `pytest tests/ace/tui/widgets/test_prompt_g_prefix_hints.py`
     - `pytest tests/ace/tui/widgets/test_prompt_input_bar_stack_editor.py`
     - `pytest tests/ace/tui/widgets/test_prompt_stack_keymaps_focus.py`
     - `pytest tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`
   - Because implementation changes in this repo require it, run `just install` if needed and then `just check` before
     completion.

## Risks and Checks

- The main regression risk is accidentally stealing existing vim NORMAL `g` commands. Keep `Ctrl+G` as its own prefix
  path and leave the existing `g` pending path untouched.
- The second risk is leaving the hint panel visible after cancellation, focus changes, or unknown continuations.
  Centralize clearing through a helper and reuse the existing hide behavior.
- The app-level `Ctrl+G` binding must remain shadowed while the prompt has focus, both in INSERT and NORMAL mode.
- No default keymap config update is expected because this is prompt-widget-local prefix behavior, not a new
  configurable app or leader binding. Re-check `src/sase/default_config.yml` only if implementation changes configurable
  keymap defaults.
