---
create_time: 2026-05-13 17:55:38
status: done
prompt: sdd/prompts/202605/repeat_last_leader_keymap.md
bead_id: sase-3f
tier: epic
---
# Repeat Last Leader Keymap Plan

## Goal

Add a new default `,,` leader-mode keymap that re-runs the most recently run leader command. The motivating workflow is:

1. On the Agents tab, press `,j` to jump to the most recent unread completed agent.
2. Press `,,` repeatedly to run the same `,j` command again, walking unread completed agents until none remain.

The feature must apply to every built-in leader-mode command under `ace.keymaps.modes.leader_mode.keys`, not only `,j`.

## Current Code Shape

Relevant surfaces in this repo:

- `src/sase/default_config.yml`: production keymap defaults. Keymap changes must update this.
- `src/sase/ace/tui/keymaps/types.py`: typed defaults for built-in modes, including `LeaderModeKeymaps`.
- `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`: current leader-mode dispatcher and footer update hook.
- `src/sase/ace/tui/actions/_state_init.py`: initializes transient TUI state, including `_leader_mode_active`.
- `src/sase/ace/tui/actions/event_handlers.py`: routes the second key while leader mode is active.
- `src/sase/ace/tui/commands/catalog.py`, `availability.py`, `execute.py`: command-palette coverage for leader commands.
- `src/sase/ace/tui/widgets/keybinding_footer.py`: transient footer while leader mode is active.
- `src/sase/ace/tui/modals/help_modal/*_bindings.py`: `?` help popup entries.
- Existing focused tests: `tests/test_keymaps.py`, `tests/test_command_catalog.py`,
  `tests/test_command_catalog_guards.py`, `tests/test_command_availability.py`,
  `tests/ace/tui/test_show_agent_run_log_keymap.py`, `tests/ace/tui/test_agent_unread_navigation.py`,
  `tests/test_command_palette_wiring.py`.

## Behavior Contract

- Add a leader-mode command id named `repeat_last` unless an implementer finds an existing local naming convention that
  is clearly better.
- Default binding: `leader_mode.keys.repeat_last: "comma"`, making the default sequence `,,`.
- `,,` repeats the last successfully matched built-in leader subkey.
- `escape`, unknown leader subkeys, and `repeat_last` itself must not become the last command.
- If there is no last leader command, `,,` should exit leader mode, restore the current tab footer/display, and notify
  the user with a short message such as `No leader command to repeat`.
- The remembered command should be the raw leader subkey, not the command id. This preserves existing context-sensitive
  duplicate-key behavior, especially `,r`, which means retry-edit on the Agents tab and runners elsewhere.
- Repeating a command should run through the same production dispatch path as pressing the original leader subkey. For
  `,j`, each repeated `,,` should acknowledge the selected unread completed agent and then move to the next candidate on
  the next repeat.
- The remembered command can persist across tabs during the app session. If the repeated command is not meaningful on
  the current tab, the existing command-specific no-op/notification behavior applies.
- Leader commands executed from the command palette should update the same remembered command because they already
  dispatch through `_handle_leader_key`.
- Respect keymap overrides. If a user remaps the leader prefix, the repeat command is still whatever
  `leader_mode.keys.repeat_last` resolves to. Do not hard-code the literal comma outside defaults/tests.

## Phase 1 - Core Dispatcher and State

Owner: one implementation agent.

Scope:

- Add `repeat_last: "comma"` to:
  - `src/sase/default_config.yml`
  - `LeaderModeKeymaps` in `src/sase/ace/tui/keymaps/types.py`
- Initialize session state in `src/sase/ace/tui/actions/_state_init.py`, likely `_last_leader_key: str | None = None`.
- Refactor `LeaderModeMixin._handle_leader_key` enough to support repeat without duplicating the entire dispatcher:
  - Keep the public `_handle_leader_key(key: str) -> bool` entry point.
  - Add a small private helper if useful, for example `_dispatch_leader_key(key: str, *, remember: bool) -> bool`.
  - Handle `escape` before repeat/recording.
  - Handle `repeat_last` before normal command matching.
  - Record the raw subkey only after a known leader branch is matched.
  - Avoid recording `repeat_last`, unknown keys, or `escape`.
- Add type hints for the new state attribute in `LeaderModeMixin` and any fake test app that needs it.

Tests:

- Extend the existing fake-app tests in `tests/ace/tui/test_show_agent_run_log_keymap.py` or create a focused
  `tests/ace/tui/test_leader_repeat_keymap.py`.
- Cover:
  - `,j` records `j`; `,,` invokes `_jump_to_next_unread_done_agent` again.
  - `,,` with no previous leader command notifies and refreshes.
  - Unknown key and `escape` do not overwrite the remembered command.
  - Repeat does not overwrite the remembered command with `comma`.
  - Duplicate-key `,r` repeats by raw subkey so context-dependent behavior remains intact.

Validation:

- Run targeted tests for the new fake-app coverage plus `tests/test_keymaps.py`.

## Phase 2 - Command Catalog, Palette, Footer, and Help Surfaces

Owner: separate implementation agent after Phase 1 lands.

Scope:

- Add an explicit `_LEADER_LABELS["repeat_last"]`, for example `Repeat last leader command`.
- Add tab scoping in `_LEADER_TABS` only if the default `_ALL_TABS` is not sufficient. The repeat command itself is
  globally available because the remembered command may be globally useful and existing repeated-command guards handle
  context.
- Confirm `execute_command` needs no special case because it should already call `_handle_leader_key(executor.subkey)`
  for `leader_mode_key`.
- Decide how to surface repeat in `KeybindingFooter.update_leader_bindings`:
  - Show it on all tabs while in leader mode.
  - Prefer a concise label like `repeat`.
  - It may always show, even before a remembered command exists, or only when the app can provide a
    `has_last_leader_command` flag. Prefer always showing unless the footer state plumbing stays simple and well-tested.
- Update all relevant help modal bindings per `src/sase/ace/AGENTS.md`. At minimum:
  - Agents help leader section.
  - Changespecs help leader section.
  - Axe help leader section if it lists leader commands.
- Ensure command palette search displays `,,` with the new label.

Tests:

- Extend `tests/test_command_catalog.py`:
  - `leader.repeat_last` exists.
  - key display is `,,` with defaults.
  - executor kind is `leader_mode_key` with subkey `comma`.
  - tabs are all three tabs unless Phase 2 intentionally scopes them.
- Extend `tests/test_command_catalog_guards.py` if any guard expectations need explicit assertions.
- Extend footer/help tests:
  - Footer leader mode includes `, repeat` or equivalent.
  - Help popup includes `,,` on each tab where leader help is shown.
- Extend `tests/test_keymaps.py`:
  - typed default and YAML default both include `repeat_last: "comma"`.
  - a user override of `repeat_last` is reflected in displayed key sequences.

Validation:

- Run targeted tests for keymaps, command catalog, footer, and help surfaces.

## Phase 3 - Real Navigation Semantics for the `,j` Workflow

Owner: separate implementation agent after Phases 1 and 2 land.

Scope:

- Add regression coverage around the concrete workflow that motivated the feature.
- Use the existing unread-agent helper tests where possible instead of building a full terminal smoke test first:
  - Drive `LeaderModeMixin._handle_leader_key("j")` against an app that also uses `AgentUnreadMixin`, or extend the
    existing fake app to simulate sequential unread jumps.
  - Verify repeated `comma` dispatch walks all unread completed agents and eventually reports no unread completed agents
    without losing the remembered command.
- Confirm that repeated `,j` keeps the current unread semantics:
  - completion-recency ordering
  - acknowledgement/removal from `_unread_completed_agent_ids`
  - panel focus changes
  - notification dismissal refresh hooks

Tests:

- Add or extend a test that starts with three unread completed agents and calls:
  - `_handle_leader_key("j")`
  - `_handle_leader_key("comma")`
  - `_handle_leader_key("comma")`
  - `_handle_leader_key("comma")`
- Assert the selected agent sequence and final notification.
- Keep lower-level unread-order tests in `tests/ace/tui/test_agent_unread_navigation.py` intact.

Validation:

- Run the new repeat navigation test plus all unread navigation tests.

## Phase 4 - Remapping, Palette Execution, and Integration Regression

Owner: separate implementation agent after Phases 1-3 land.

Scope:

- Add tests for configured keymaps and command-palette execution:
  - Override `leader_mode.keys.repeat_last` and verify the catalog/help/footer use the override.
  - Override `leader_mode.prefix` and verify display helpers do not assume a literal comma for the prefix.
  - Execute a leader command through `execute_command`, then execute `leader.repeat_last`, and verify both go through
    `_handle_leader_key` with the expected subkeys.
- Add an e2e/pilot test only if the existing AcePage DSL can set up the required state without a large fixture. Prefer a
  targeted pilot test over a terminal smoke test unless failures would otherwise be invisible.
- Review for stale assumptions in comments or docs that list every leader subkey.

Validation:

- Run:
  - `just install` first if this ephemeral workspace has not been prepared.
  - Targeted tests touched by the phase.
  - `just check` before final handoff, per repo instructions.

## Cross-Phase Notes

- Do not modify files under `memory/` without explicit user approval.
- Keep behavior in Python/TUI code. This is presentation/input state, not shared backend logic, so the Rust core
  boundary does not require changes.
- Avoid changing app-level bindings. This is a leader-mode subkey, not a new `AppKeymaps` field.
- Be careful with duplicate leader subkey values. The current `,r` behavior is intentionally context-sensitive because
  both `runners` and `retry_edit` use `r`; storing raw subkeys is the simplest way to preserve it.
- The command catalog has broad guard tests; adding a key only to defaults without adding labels/help/footer will leave
  user-visible drift even if generic catalog fallback labels keep tests green.
- If any phase adds file changes, run appropriate targeted tests. The final implementation phase should run
  `just check`.
