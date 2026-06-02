---
create_time: 2026-06-02 14:43:33
status: done
prompt: sdd/prompts/202606/fix_space_agent_home.md
---
# Plan: Restore Bare Space Agent-Home Shortcut

## Goal

Fix the ACE TUI keymap regression where pressing bare Space does nothing after the attempted migration from the old `,h`
home-agent shortcut.

The intended behavior for this fix is:

- Bare Space in normal ACE mode opens the home-mode agent prompt by calling `_show_prompt_input_bar_for_home()`.
- Ctrl+Space remains the repeat-last `@`/VCS selection shortcut and stays internally represented as Textual's `ctrl+@`.
- The old `,h` shortcut must not come back.
- Existing modal/input-local Space behavior should not be changed.

## Root Cause

The recent migration implemented the new key as a leader-mode subkey (`leader_mode.keys.agent_home = "space"`), so the
runtime shortcut became `, Space`, not bare Space. The same commit also added an e2e regression test asserting bare
Space does nothing.

At the app binding layer, bare Space is currently unbound because `app.start_agent_from_changespec` was correctly moved
to `ctrl+@` during the Ctrl+Space migration and no replacement app-level home-agent action was added. Therefore a normal
Space key press reaches no Textual binding and no action handler.

## Implementation Approach

1. Add a dedicated app-level home-agent keymap.
   - Add an `AppKeymaps` field such as `start_agent_home`.
   - Add it to `_BINDING_META` with a description like `Run Agent (Home)`.
   - Add `start_agent_home: "space"` under `ace.keymaps.app` in `src/sase/default_config.yml`.
   - Do not reuse `start_agent_from_changespec`, because that command is now the Ctrl+Space repeat-last selection path.

2. Add the matching Textual action.
   - Implement `action_start_agent_home()` on the agent workflow entry-point mixin.
   - Keep the body small: call `_show_prompt_input_bar_for_home()`.
   - This preserves the old `,h` action behavior while moving it to a direct app binding.

3. Keep leader-mode behavior deliberate.
   - Leave `leader_mode.keys.agent_home = "space"` only if we want `, Space` as a backwards-compatible alias from the
     previous commit; otherwise update the leader catalog/help/footer expectations to avoid advertising it.
   - In either case, keep `h` unbound for agent-home and keep `agent_from_cl = "ctrl+@"`.
   - Ensure the normal-mode Space binding does not affect Ctrl+Space canonicalization.

4. Update user-facing command surfaces.
   - Add command-palette metadata for the new `app.start_agent_home` command with a label like `Run agent (home mode)`.
   - Update help/footer tests or surfaces if they should advertise bare Space as the primary home-agent shortcut.
   - Keep Ctrl+Space labels for repeat-last/VCS quick flow unchanged.

5. Add focused regression coverage.
   - Update keymap registry tests to assert:
     - `reg.app.start_agent_home == "space"`.
     - `reg.app.start_agent_from_changespec == "ctrl+@"`.
     - `LeaderModeKeymaps().keys["agent_home"] != "h"`.
   - Update binding tests to assert Space maps to `start_agent_home`, not `start_agent_from_changespec`.
   - Add a direct action test proving `action_start_agent_home()` calls `_show_prompt_input_bar_for_home()`.
   - Update the e2e test that currently asserts bare Space does nothing so bare Space launches the home prompt.
   - Keep or add a guard that Ctrl+Space still dispatches repeat-last and not home mode.

## Verification

Run focused tests first:

```bash
.venv/bin/python -m pytest tests/test_keymaps.py tests/test_command_catalog.py tests/test_keymaps_e2e.py tests/ace/tui/test_show_agent_run_log_keymap.py
```

After source changes, follow the repository rule from `memory/short/build_and_run.md`:

```bash
just install
just check
```

## Risks

- Space is a common key inside modals and prompt input widgets. The app-level binding should be verified through e2e
  coverage so it works in the main ACE screen without stealing typed spaces after the prompt bar is focused.
- Adding a new `AppKeymaps` field requires keeping `default_config.yml`, `_BINDING_META`, and command catalog metadata
  in sync; existing guard tests should catch drift.
- The main semantic risk is confusing bare Space with Ctrl+Space. Tests should prove both routes dispatch to separate
  actions.
