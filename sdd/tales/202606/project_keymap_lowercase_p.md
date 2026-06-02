---
create_time: 2026-06-02 06:10:18
status: done
prompt: sdd/prompts/202606/project_keymap_lowercase_p.md
---
# Plan: move project management leader key from ,P to ,p

## Context

The current ACE project management entry point is a leader-mode command:

- Runtime dispatch reads `leader_mode.keys["projects"]` in `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`.
- Built-in mode defaults are duplicated in `src/sase/ace/tui/keymaps/types.py` and `src/sase/default_config.yml`.
- Help modal, footer, and command palette display derive from the loaded `KeymapRegistry`, so their runtime code should
  update automatically once the registry default is lower-case `p`.
- Focused tests currently pin `,P` in `tests/test_keymaps.py` and `tests/test_command_catalog.py`.
- Current user-facing docs pin `,P` in `README.md`, `docs/ace.md`, `docs/project_spec.md`, and `docs/configuration.md`.

The search found no existing leader-mode command using lowercase `p`. Copy-mode uses `p` after the `%` prefix, which
does not conflict with `,p`. Historical SDD prompt/tale/epic files also mention `,P`; those are records of prior work
and should not be rewritten for this narrow product change.

## Implementation Steps

1. Update the default leader project key:
   - Change `projects: "P"` to `projects: "p"` in `src/sase/default_config.yml`.
   - Change `LeaderModeKeymaps.keys["projects"]` from `"P"` to `"p"` in `src/sase/ace/tui/keymaps/types.py`.

2. Update tests that pin the visible/default key:
   - In `tests/test_keymaps.py`, change the project-management default assertion and docstring from `,P`/`"P"` to
     `,p`/`"p"`.
   - In `tests/test_keymaps.py`, change the help modal expected entry from `(",P", "Project management")` to
     `(",p", "Project management")`.
   - In `tests/test_command_catalog.py`, change `leader.projects` expected `key_display` from `,P` to `,p`.
   - Keep the existing `temporary_llm_override` checks at `,o` to verify the old conflict resolution stays intact.

3. Update current user-facing docs:
   - Replace product-facing `,P` references with `,p` in `README.md`, `docs/ace.md`, `docs/project_spec.md`, and
     `docs/configuration.md`.
   - In the `docs/configuration.md` keymap example, update the `projects` default to `"p"` and avoid leaving
     duplicate/stale `projects: "P"` entries.
   - Do not update historical `sdd/` files unless a later task explicitly asks for historical record edits.

4. Validate the change:
   - Run `just install` first, per repo guidance for ephemeral workspaces.
   - Run focused checks:
     - `pytest tests/test_keymaps.py tests/test_command_catalog.py`
     - `rg --line-number --fixed-strings ',P' README.md docs tests src config`
     - `rg --line-number 'projects: "P"' src docs config README.md tests`
   - Run `just check` after implementation because this repo requires it for source/doc/test changes.

## Expected Result

Pressing `,p` opens the Project Management panel from all ACE tabs. The command palette, help modal, and leader footer
show `,p`; `,P` is no longer advertised or used as the default project-management trigger. Existing user overrides
remain possible through `ace.keymaps.modes.leader_mode.keys.projects`.
