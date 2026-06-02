---
create_time: 2026-06-02 12:55:33
status: done
prompt: sdd/prompts/202606/ctrl_space_keymap.md
---
# Plan: Migrate Ace TUI Space Keymap to Ctrl+Space

## Goal

Move the current Ace TUI bare Space keymaps to Ctrl+Space without changing the underlying agent launch behavior:

- App-level `start_agent_from_changespec`, currently bound to `space`.
- Leader-mode `agent_from_cl`, currently reached as `,Space`.

The migration should remove bare Space from these defaults, keep existing modal/text-input Space behavior intact, and
make the new binding visible in help, footer, and command-palette surfaces.

## Current Findings

- Runtime app defaults come from `src/sase/default_config.yml` for `ace.keymaps.app.start_agent_from_changespec`.
- Built-in leader-mode defaults currently live in both `src/sase/default_config.yml` and `LeaderModeKeymaps` in
  `src/sase/ace/tui/keymaps/types.py`.
- `src/sase/ace/tui/bindings.py` is a fallback binding list and also still binds `start_agent_from_changespec` to
  `space`.
- Help modal labels still describe the repeat workflow as `@/Space` or `@/<space>`.
- Footer and command-palette output are registry-driven, so they will mostly follow the default key changes if key
  display is correct.
- Textual 8.0.0 maps real terminal Ctrl+Space input to the canonical key `ctrl+@` via the NUL byte. Textual accepts
  `Binding("ctrl+space", ...)`, but binding dispatch is exact-match on `event.key`, so a runtime binding that is only
  `ctrl+space` may not fire in real terminals.
- Prefix-mode subkeys, including `leader_mode.keys.agent_from_cl`, are compared directly against `event.key`. A
  comma-separated binding alternative is not enough for this leader subkey unless the mode handlers are broadened.

## Design

Use `ctrl+@` as the internal Textual key for this migration, and display it to users as `Ctrl+Space`.

This keeps the real terminal path reliable while preserving the user-facing intent of the keymap. Also accept user
config spelling `ctrl+space` by canonicalizing it to `ctrl+@` during keymap loading, so config authors can use the
intuitive spelling without breaking terminal dispatch.

Do not remove `space` from the validator entirely. Users may still explicitly bind an action to bare Space, and many
modal/widget-local Space bindings are unrelated to this migration.

## Implementation Steps

1. Add a small key canonicalization/display layer in `src/sase/ace/tui/keymaps/`.
   - Canonicalize `ctrl+space` and `ctrl+at` to `ctrl+@`.
   - Treat `ctrl+@` as a valid key.
   - Render `ctrl+@` and `ctrl+space` as `Ctrl+Space`.
   - Apply canonicalization to app keymaps and built-in/custom mode prefix/key strings when loading config.

2. Update default key sources.
   - Change `ace.keymaps.app.start_agent_from_changespec` to `ctrl+@` in `src/sase/default_config.yml`.
   - Change `ace.keymaps.modes.leader_mode.keys.agent_from_cl` to `ctrl+@` in `src/sase/default_config.yml`.
   - Change `LeaderModeKeymaps().keys["agent_from_cl"]` to `ctrl+@`.
   - Change the fallback `DEFAULT_BINDINGS` entry in `src/sase/ace/tui/bindings.py` to `ctrl+@`.

3. Update user-facing text tied to this keymap.
   - Replace active help labels like `Repeat last @/Space selection` with wording that does not imply bare Space, such
     as `Repeat last @/Ctrl+Space selection`.
   - Update `_entry_points.py` comments, docstrings, and notifications from `@/<space>` to `@/Ctrl+Space` or a neutral
     phrase like `saved agent selection`.
   - Keep historical SDD/research references unchanged unless they are current user-facing docs or tests depend on them.

4. Keep mode-display readability intact.
   - Verify command-palette display for `leader.agent_from_cl` becomes readable with a multi-character subkey, for
     example `, Ctrl+Space`.
   - Adjust help formatting for this leader entry if it would otherwise render as `,Ctrl+Space`.
   - Confirm footer leader-mode chips show `Ctrl+Space run agent (CL)`.

5. Add focused regression coverage.
   - Key validation accepts both `ctrl+@` and `ctrl+space`.
   - User config `ctrl+space` canonicalizes to the runtime key `ctrl+@`.
   - Default app binding for `start_agent_from_changespec` is no longer `space`.
   - Default leader subkey `agent_from_cl` is no longer `space`.
   - `key_display_name("ctrl+@")` and `footer_key_display("ctrl+@")` show `Ctrl+Space`.
   - Help modal and command catalog expose `Ctrl+Space`, not the old bare Space wording.
   - Where practical, add a Pilot or direct binding test that presses `ctrl+@` and confirms Textual dispatch reaches
     `start_agent_from_changespec`.

## Verification

After implementation:

1. Run `just install` if the workspace has not been bootstrapped recently.
2. Run targeted tests first:
   - `pytest tests/test_keymaps.py tests/test_keymaps_validation.py`
   - `pytest tests/test_command_catalog.py`
   - `pytest tests/test_keybinding_footer_core.py tests/test_keybinding_footer_agent.py`
   - Any focused Ace/Pilot test added for the binding dispatch path.
3. Run the required repository gate after source edits: `just check`.
4. Optional manual smoke in `sase ace`:
   - Bare Space should not trigger the repeat-last agent selection.
   - Ctrl+Space should trigger the repeat-last agent selection.
   - `,` then Ctrl+Space should trigger the quick agent-from-CL/agent flow.

## Risks and Boundaries

- Ctrl+Space terminal behavior can vary by terminal. Using Textual's canonical `ctrl+@` handles the common terminal NUL
  path; tests should cover the canonical event key.
- Do not touch modal-local Space bindings such as marking/selecting options; those are independent UI controls.
- Do not change prompt input behavior; literal Space must remain normal text entry inside focused input widgets.
- No Rust core changes are needed because this is presentation/keybinding behavior inside the Python TUI.
