---
create_time: 2026-05-05 16:37:10
status: wip
prompt: sdd/prompts/202605/agent_run_log_leader_keymap.md
---
# Agent Run Log Leader Keymap Plan

## Goal

Restore the legacy CLs-tab Agent Run Log as a temporary fallback while keeping the unified artifacts panel on the
capital `A` app key. The restored shortcut should be leader-mode `,A` by default and should only open the run-log modal
from the CLs tab with a selected ChangeSpec.

## Current State

- `src/sase/ace/tui/modals/agent_run_log_modal.py` still implements the Agent Run Log modal.
- `ChangeSpecMixin.action_show_agent_run_log()` still exists and already opens `AgentRunLogModal` for the current CL,
  with no-ops outside the CLs tab or when there are no ChangeSpecs.
- `open_artifacts_panel` is the configured app-level `A` binding in `src/sase/default_config.yml`,
  `src/sase/ace/tui/keymaps/types.py`, and `src/sase/ace/tui/bindings.py`.
- Leader-mode commands are configured under `ace.keymaps.modes.leader_mode.keys`, handled by
  `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`, displayed in
  `src/sase/ace/tui/widgets/keybinding_footer.py`, and documented in `src/sase/ace/tui/modals/help_modal/bindings.py`.
- The command palette auto-discovers leader-mode keys via `src/sase/ace/tui/commands/catalog.py`, but needs labels and
  CL-only availability metadata for a polished command.

## Implementation Plan

1. Add a new leader-mode command key named `agent_run_log` with default subkey `A`.
   - Update `src/sase/default_config.yml` under `ace.keymaps.modes.leader_mode.keys`.
   - Update `LeaderModeKeymaps` defaults in `src/sase/ace/tui/keymaps/types.py` so tests and default objects match the
     bundled config.

2. Wire leader-mode dispatch to the existing ChangeSpec action.
   - In `_handle_leader_key()`, when the pressed key matches `leader_keys["agent_run_log"]`, call
     `action_show_agent_run_log()` only on the CLs tab, then refresh the current tab.
   - Reuse the existing `ChangeSpecMixin.action_show_agent_run_log()` implementation rather than adding another modal
     construction path.

3. Surface the shortcut in user-visible keybinding metadata.
   - Add `,A` to the CLs-tab Leader Mode help section as "Agent run log".
   - Add the command palette leader label and mark `leader.agent_run_log` as CL-only.
   - Add it to the leader footer only while leader mode is active on the CLs tab, since this is an explicit temporary
     fallback users should be able to discover.

4. Add regression tests.
   - Restore a focused `tests/ace/tui/test_show_agent_run_log_keymap.py`, adjusted for `,A` instead of app-level `A`.
   - Assert the default leader key is `A`, the app-level `A` binding remains `open_artifacts_panel`, and leader dispatch
     opens `AgentRunLogModal` for the selected CL.
   - Assert leader dispatch is a no-op on non-CL tabs and empty CL lists.
   - Update keymap/help tests that intentionally guarded against `A` being relabeled as run log so they now guard the
     distinction: app-level `A` is artifacts, leader `,A` is agent run log.
   - Add command palette coverage if existing tests do not already cover leader command IDs and CL-only applicability.

5. Verify.
   - Run targeted tests for keymaps, artifact-panel launch, agent-run-log keymap, and command palette wiring.
   - Because this repo requires it after changes, run `just install` if needed and then `just check`.

## Non-Goals

- Do not add a second app-level `A` binding or change the artifacts panel shortcut.
- Do not reintroduce artifact-panel legacy run-log bridge UI.
- Do not alter the Agent Run Log modal data-loading behavior.
