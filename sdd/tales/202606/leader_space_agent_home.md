---
create_time: 2026-06-02 13:17:02
status: done
prompt: sdd/prompts/202606/leader_space_agent_home.md
---
# Plan: Move `,h` Agent-Home Leader Key To `,<space>`

## Goal

Change the Ace TUI leader-mode "agent home" shortcut from `,h` to comma followed by bare Space, while preserving the
existing behavior of the action:

- `, <space>` should still call the direct home-mode agent prompt path (`_show_prompt_input_bar_for_home()`).
- Bare Space by itself should remain unbound at the app level and must not regress the recent Ctrl+Space migration.
- `, Ctrl+Space` should continue to mean the separate "agent from current CL / selected agent" quick path.

This is a keymap migration only. No Rust core changes are needed because the behavior is presentation/Textual dispatch
inside the Python TUI.

## Current Findings

- The `,h` mapping is `leader_mode.keys.agent_home`.
- Runtime defaults are defined in two places that must stay in sync:
  - `src/sase/default_config.yml` under `ace.keymaps.modes.leader_mode.keys.agent_home`.
  - `LeaderModeKeymaps` in `src/sase/ace/tui/keymaps/types.py`.
- Leader subkeys are not Textual app `Binding` objects. `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`
  compares `event.key` directly against configured leader subkeys.
- Textual uses `event.key == "space"` for bare Space. Unlike Ctrl+Space, no alias/canonicalization work is needed.
- The app-level `start_agent_from_changespec` binding and the leader `agent_from_cl` subkey already use `ctrl+@`
  internally and display as `Ctrl+Space`; those should not change.
- Help modal entries for `agent_home` currently concatenate prefix and subkey directly. If the subkey becomes `space`,
  those entries would render as `,Space`, so they should use the existing sequence formatter that renders
  multi-character keys readably.
- The footer already uses `footer_key_display("space") == "<space>"`, so the active leader-mode footer can naturally
  show `<space> agent (home)`.
- The command catalog already space-joins multi-character key names, so `leader.agent_home` should render as `, Space`
  once its configured subkey is `space`.

## Implementation Approach

1. Update the default leader key sources.
   - Change `agent_home: "h"` to `agent_home: "space"` in `src/sase/default_config.yml`.
   - Change `LeaderModeKeymaps().keys["agent_home"]` from `"h"` to `"space"` in `src/sase/ace/tui/keymaps/types.py`.
   - Do not change `src/sase/ace/tui/bindings.py`, because `agent_home` is a leader subkey, not an app-level binding.

2. Preserve the existing Ctrl+Space split.
   - Leave `app.start_agent_from_changespec` as `ctrl+@`.
   - Leave `leader_mode.keys.agent_from_cl` as `ctrl+@`.
   - Do not canonicalize bare `space` to anything else.
   - Keep bare Space by itself as a no-op for repeat-agent dispatch.

3. Update user-facing display for the moved key.
   - Update the three help-modal `agent_home` entries in CLs, Agents, and Axe bindings to use
     `key_sequence_display(lm.prefix, sk(lm.keys, "agent_home"))`.
   - Keep established display conventions:
     - Help modal and command palette can show `, Space`.
     - Active footer chips can show `<space> agent (home)`.
   - Search for current user-facing `,h` / `agent_home` references and update only active surfaces, not historical SDD
     plans or research notes.

4. Add focused regression tests.
   - Assert the loaded default registry and `LeaderModeKeymaps()` bind `agent_home` to `"space"`.
   - Assert `agent_from_cl` remains `"ctrl+@"` and app `start_agent_from_changespec` remains `"ctrl+@"`.
   - Assert help modal entries show the agent-home leader sequence as `, Space` for CLs, Agents, and Axe.
   - Assert the command catalog entry `leader.agent_home` has:
     - `key_sequence == ("comma", "space")`
     - `key_display == ", Space"`
     - executor subkey `"space"`.
   - Assert the active leader footer surfaces `<space>` with label `agent (home)`.
   - Add a direct leader-dispatch test where `_handle_leader_key("space")` calls `_show_prompt_input_bar_for_home()`,
     remembers `"space"`, exits leader mode, and refreshes the current tab.
   - Add a regression that `_handle_leader_key("h")` no longer calls the home-mode prompt. Unknown leader keys currently
     still exit leader mode and refresh, so the assertion should focus on "does not launch home" rather than
     `handled is False`.
   - Add or extend a Pilot/E2E test to press `comma` then `space` and verify the home-mode prompt path fires, while the
     existing bare-Space app-level no-op test continues to pass.

## Verification

After implementation:

1. Run `just install` if the workspace has not been bootstrapped recently.
2. Run focused tests first:
   - `.venv/bin/python -m pytest tests/test_keymaps.py tests/test_command_catalog.py`
   - `.venv/bin/python -m pytest tests/test_keybinding_footer_core.py tests/ace/tui/test_show_agent_run_log_keymap.py`
   - `.venv/bin/python -m pytest tests/test_keymaps_e2e.py`
3. Run the required repository gate after source edits:
   - `just check`

## Risks And Boundaries

- The main regression risk is confusing bare Space with Ctrl+Space. Tests should prove direct bare Space stays unbound
  while `, <space>` works only after leader mode is active.
- Help/catalog/footer display should remain readable, but this does not require changing global key display helpers.
- User overrides should continue to work through the existing loader path. A user can still rebind `agent_home` back to
  `"h"` if desired.
- Modal-local Space bindings, prompt input typing, and direct app-level keybindings are out of scope.
