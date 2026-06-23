---
create_time: 2026-06-23 09:47:06
status: wip
prompt: sdd/prompts/202606/disable_prompt_keymap_leak.md
---
# Disable App Keymaps While Prompt Normal Mode Owns Focus

## Problem

When the prompt input widget is focused and its `PromptTextArea` is in Vim normal mode, pressing `space` or `ctrl+space`
still reaches app-level keymaps. Those keys are globally bound to agent launch actions:

- `space` -> `start_agent_home`
- `ctrl+@` (`ctrl+space`) -> `start_agent_from_changespec`

Because normal-mode prompt handling currently returns without stopping unhandled keys, these bindings can remount or
replace the prompt input bar, which clears the current prompt draft.

## Current Findings

- App-level defaults live in `src/sase/default_config.yml` and are materialized through
  `src/sase/ace/tui/keymaps/loader.py`.
- `ctrl+space` is canonicalized to Textual's `ctrl+@` in `src/sase/ace/tui/keymaps/types.py`.
- `PromptTextArea._on_key()` in `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` already intercepts many
  prompt-local keys before TextArea or app bindings can see them.
- The same file already has a focused-prompt normal-mode guard for bare `K`, preventing an unrelated app-level
  Agents-tab binding from firing while the prompt owns focus.
- Existing e2e coverage confirms insert-mode `space` remains text input after a home prompt opens, but there is no
  regression test for normal-mode `space` or `ctrl+space`.

## Approach

1. Add focused-prompt normal-mode handling for `space` and `ctrl+@` in `PromptTextArea._on_key()`.
2. Treat these keys as prompt-local no-ops only when they are top-level normal-mode keys, mirroring the existing `K`
   guard:
   - no pending Vim prefix,
   - no pending operator,
   - no count prefix.
3. Preserve legitimate pending Vim behavior by allowing the existing normal mode handler to process key continuations
   when a sequence is in progress.
4. Do not change global keymap defaults, keymap canonicalization, or app-level agent launch behavior when the prompt is
   not focused.

## Tests

1. Add regression coverage to `tests/test_keymaps_e2e.py`:
   - Open the home prompt with `space`.
   - Enter text.
   - Press `escape` to enter prompt normal mode.
   - Press `space` and assert the prompt text remains unchanged and the global home action is not called again.
   - Press `ctrl+@` and assert the prompt text remains unchanged and the global changespec-agent action is not called.
2. Keep the existing insert-mode `space` test intact to prove regular text insertion still works.
3. Run the focused test file:
   - `pytest tests/test_keymaps_e2e.py`

If the focused file exposes unrelated slowness or fixture issues, run the specific new tests and report the limitation.

## Risk Notes

- The change is event-loop local and synchronous; it should not add blocking work or refresh paths.
- The narrow no-op guard minimizes compatibility risk for existing Vim sequences and app keymaps outside the prompt.
- If future prompt normal-mode commands want to use `space` or `ctrl+space`, the guard can be replaced with explicit
  prompt-local command handling without changing app keymap behavior.
