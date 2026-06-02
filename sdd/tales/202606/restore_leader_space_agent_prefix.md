---
create_time: 2026-06-02 15:06:05
status: done
prompt: sdd/prompts/202606/restore_leader_space_agent_prefix.md
---
# Plan: Restore `, Space` Agent Prefix Launch

## Goal

Fix the ACE TUI regression where leader `, Space` opens a home-mode prompt instead of deriving a VCS prompt prefix from
the currently selected ChangeSpec or selected agent.

The intended behavior after this fix:

- Bare Space in normal ACE mode remains the primary home-mode agent shortcut and calls `action_start_agent_home()`.
- Bare Ctrl+Space remains the repeat-last `@` / saved VCS selection shortcut and stays represented internally as
  Textual's `ctrl+@`.
- Leader `, Space` again runs the current-selection quick path:
  - on the ChangeSpecs tab, use the selected ChangeSpec, or all marked ChangeSpecs when marks exist;
  - on the Agents tab, use the selected agent's project / ChangeSpec context;
  - on Axe or other tabs, no-op except for normal leader-mode exit/refresh behavior.
- The leader home-mode alias must move off Space so it no longer shadows `agent_from_cl`. I will restore the previous
  leader home key `,h` as a secondary alias; bare Space remains the primary home shortcut.

No Rust core work is needed. This is a Textual keymap/default/help/test fix in the Python TUI.

## Findings

- The current dispatch regression is in `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`:
  `leader_keys["agent_home"]` is checked before `leader_keys["agent_from_cl"]`, and the defaults currently bind
  `agent_home` to `space`, so `, Space` always calls `_show_prompt_input_bar_for_home()`.
- The selection-derived behavior still exists and is healthy:
  - `_start_agent_from_changespec_quick()` builds a VCS prefix from the selected ChangeSpec and handles marked
    ChangeSpecs through `_start_agents_from_marked()`.
  - `_start_agent_from_agent_quick()` builds a VCS prefix from the selected agent.
- History confirms the old user-facing contract:
  - `747819397` added comma-space on the Agents tab to use the selected agent's project/CL, mirroring CLs-tab
    comma-space behavior.
  - `afcd2f4d9` moved the app-level repeat-last shortcut and leader `agent_from_cl` from Space to Ctrl+Space.
  - `8b392bc8` then moved leader `agent_home` from `h` to Space, which created the collision with the old comma-space
    behavior.
  - `397d4cc7` correctly added bare Space as a normal-mode home shortcut, making a leader-space home alias unnecessary.
- The existing help, footer, and command catalog surfaces are registry-driven and currently advertise the regression:
  `leader.agent_home == ", Space"` and `leader.agent_from_cl == ", Ctrl+Space"`.
- Leader-mode subkeys are plain string comparisons today. Although the key validator supports comma-separated
  alternatives for Textual `Binding` strings, leader dispatch does not treat `space,ctrl+@` as two subkeys. Supporting
  multiple leader subkeys for one command would require broader matching and command-palette executor changes, so this
  fix should keep one default subkey per leader command.

## Implementation Approach

1. Restore the default leader key split.
   - Change `LeaderModeKeymaps().keys["agent_home"]` from `"space"` back to `"h"`.
   - Change `LeaderModeKeymaps().keys["agent_from_cl"]` from `"ctrl+@"` back to `"space"`.
   - Make the matching changes in `src/sase/default_config.yml`.
   - Leave app defaults alone:
     - `app.start_agent_home == "space"`;
     - `app.start_agent_from_changespec == "ctrl+@"`.

2. Keep dispatch logic conceptually unchanged, but verify the restored defaults route correctly.
   - With `agent_home = "h"` and `agent_from_cl = "space"`, the existing dispatch order is no longer ambiguous.
   - `, Space` should call `_start_agent_from_changespec_quick()`, `_start_agents_from_marked()`, or
     `_start_agent_from_agent_quick()` depending on tab and marks.
   - `,h` should call `_show_prompt_input_bar_for_home()` as a secondary leader-only home alias.
   - Bare Space should continue to call `action_start_agent_home()` through the app binding, not through leader mode.

3. Update command surfaces and labels to match the restored semantics.
   - Command catalog:
     - `leader.agent_from_cl` should display `, Space`, be scoped to ChangeSpecs + Agents, and execute subkey `space`.
     - `leader.agent_home` should display `,h`, be scoped to all tabs, and execute subkey `h`.
     - `app.start_agent_home` should remain bare `Space`.
     - `app.start_agent_from_changespec` should remain `Ctrl+Space`.
   - Help modal:
     - Keep bare Space entries labeled as home mode.
     - Show `, Space` as "Run agent from current CL" on ChangeSpecs and "Run agent from selected agent" on Agents.
     - Show `,h` as "Run agent (home)" where leader-mode home is listed.
   - Leader footer:
     - Show `h agent (home)`.
     - Show `<space> run agent (CL)` on ChangeSpecs and Agents.
     - Keep footer labels concise; the Agents tab label can remain "run agent (CL)" if that is the established footer
       wording, while help/catalog clarify selected-agent behavior.

4. Update focused tests that currently lock in the bad behavior.
   - Keymap default tests:
     - assert app bare Space home and app Ctrl+Space repeat-last remain unchanged;
     - assert leader `agent_home == "h"`;
     - assert leader `agent_from_cl == "space"`.
   - Leader dispatch tests:
     - change `test_leader_space_runs_agent_home` into `test_leader_space_runs_agent_from_current_cl`;
     - add/restore `test_leader_space_runs_agent_from_selected_agent_on_agents_tab`;
     - keep marked-ChangeSpec coverage for `, Space`;
     - change the `h` regression to assert `,h` runs home mode.
   - E2E tests:
     - keep bare Space home and prompt-input typed Space coverage;
     - update `comma`, `space` to verify the quick current-selection path, not home;
     - keep bare Ctrl+Space repeat-last coverage.
   - Help/footer/catalog tests:
     - update expected `, Space` / `,h` displays and executor subkeys.

5. Search for stale user-facing text.
   - Update active help labels, command labels, and tests that imply `, Ctrl+Space` is the primary quick
     current-selection shortcut.
   - Do not rewrite historical SDD plan files except for this new plan submission.

## Verification

Focused tests after implementation:

```bash
.venv/bin/python -m pytest \
  tests/test_keymaps.py \
  tests/test_command_catalog.py \
  tests/test_keymaps_e2e.py \
  tests/ace/tui/test_show_agent_run_log_keymap.py
```

Then follow the repo rule for source edits:

```bash
just install
just check
```

## Risks And Boundaries

- The main risk is re-confusing three different shortcuts. Tests should lock the final split: bare Space = home, bare
  Ctrl+Space = repeat saved selection, leader Space = current selection, leader `h` = home alias.
- This plan intentionally does not add multi-alternative leader subkeys. That would be a larger keymap framework change
  because leader dispatch and command-palette execution currently pass one raw subkey string.
- User overrides should continue to work through the existing keymap loader. A user can still bind leader home or leader
  current-selection to different keys.
- Modal-local Space and focused prompt text input remain out of scope except for regression tests proving typed spaces
  still work after the home prompt opens.
