---
create_time: 2026-06-14 11:21:48
status: done
prompt: sdd/prompts/202606/runners_uppercase_r.md
---
# Plan: Move Runners Panel to `,R`

## Goal

Update the ACE leader-mode keymap so:

- `,r` remains the Agents-tab revert-agent-commits action.
- `,R` opens the runners panel.
- The existing Agents-tab repro-capture action no longer collides with `,R`.

## Current Findings

The revert action is already configured as `leader_mode.keys.revert_agent: "r"` in both `src/sase/default_config.yml`
and `src/sase/ace/tui/keymaps/types.py`.

The runners panel is currently configured as `leader_mode.keys.runners: "w"`.

`leader_mode.keys.capture_agents_repro` is currently `"R"`, so changing runners to `"R"` without moving repro capture
would make two leader commands share the same subkey. The leader dispatcher checks `runners` before
`capture_agents_repro`, so repro capture would become unreachable by normal keypress and command-palette dispatch
through that subkey would be ambiguous.

This is a TUI keymap/config/docs change only. It does not require Rust core changes or backend behavior changes.

## Decisions

Move `runners` from `,w` to `,R`.

Keep `revert_agent` on `,r`.

Move `capture_agents_repro` from `,R` to `,C`, using uppercase C as the mnemonic for capture and leaving the existing
`,T` repro-check toggle unchanged.

## Implementation Steps

1. Update the default keymap sources:
   - `src/sase/default_config.yml`
   - `src/sase/ace/tui/keymaps/types.py`

2. Do not change the leader dispatcher logic unless inspection during implementation reveals hardcoded assumptions. The
   dispatcher compares against registry values, so changing the default keys should route `,R` to
   `action_show_runners()` and `,C` to `action_capture_agents_repro()`.

3. Update user-facing documentation:
   - `docs/ace.md`: leader tables, runners modal section, Agents-tab repro section.
   - `docs/configuration.md`: in-TUI repro-capture key reference.
   - `tests/ace/tui/repro/README.md`: fixture-capture instructions.

4. Update tests that assert exact default keys or dispatch names:
   - `tests/test_keymaps_defaults.py`: assert `revert_agent == "r"`, `runners == "R"`, `capture_agents_repro == "C"`,
     and add/keep a guard that default leader-mode subkeys are unique.
   - `tests/ace/tui/test_show_agent_run_log_keymap.py`: rename/update the runners dispatch tests from leader `w` to
     leader `R`, and ensure repeat-last stores/replays the raw `R` subkey.

5. Add focused catalog/help coverage if existing tests do not already pin the new display:
   - Verify `leader.runners` displays `,R`.
   - Verify `leader.capture_agents_repro` displays `,C`.
   - Verify Agents help shows `,C` for capture repro and no longer advertises `,R` for that action.

6. Keep unrelated behavior unchanged:
   - Direct Agents-tab `r` retry/edit remains separate from leader `,r` revert.
   - Revert backend and confirmation modal behavior remain untouched.
   - Runners panel availability and footer behavior remain data-driven by runner count.
   - Repro capture remains Agents-tab-only, just on a new leader subkey.

## Verification

After implementation, run targeted tests first:

```bash
python -m pytest \
  tests/test_keymaps_defaults.py \
  tests/ace/tui/test_show_agent_run_log_keymap.py \
  tests/test_keymaps_display_help.py \
  tests/test_command_catalog.py \
  tests/test_command_catalog_guards.py \
  tests/ace/tui/repro/test_in_tui_capture.py
```

Then run repository validation because source and docs files will have changed:

```bash
just install
just check
```

If visual snapshots fail only because footer key labels changed in a covered leader-mode view, inspect the generated
artifacts before accepting or updating any snapshot.
