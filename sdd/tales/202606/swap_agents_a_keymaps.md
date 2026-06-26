---
create_time: 2026-06-26 17:19:10
status: done
prompt: sdd/prompts/202606/swap_agents_a_keymaps.md
---
# Swap Agents Tab a/A Keymaps

## Goal

Swap the default `a` and `A` behavior for the ACE TUI Agents tab:

- `a` should open the selected or marked agents' artifacts.
- `A` should open the auto-approve menu or answer HITL for eligible agents.

This should be a keymap/default-display change, not a behavioral rewrite of either action.

## Current State

The TUI uses the configurable app-level keymap registry as the runtime source of truth:

- `accept_proposal` defaults to `a` in `src/sase/default_config.yml`.
- `open_agent_artifacts` defaults to `A` in `src/sase/default_config.yml`.
- `src/sase/ace/tui/actions/_state_init.py` builds runtime Textual bindings from the loaded registry.
- `src/sase/ace/tui/bindings.py` still carries fallback `DEFAULT_BINDINGS` and should stay in sync with the defaults.
- The Agents footer already resolves displayed keys through the registry via `_kd(...)`, so changing the registry
  defaults should update footer labels automatically once tests are adjusted.
- The help modal also renders keys through the registry, but its source text and docs need to remain semantically
  accurate.

The action methods should remain as-is:

- `action_accept_proposal()` remains responsible for PR proposal acceptance outside Agents and for Agents-tab
  HITL/auto-approve behavior.
- `action_open_agent_artifacts()` remains responsible for Agents-tab artifact selection, marked-agent artifact
  collection, tmux pane toggling, and no-artifact warnings.

## Implementation Plan

1. Update default keymap sources.
   - Change `ace.keymaps.app.accept_proposal` from `a` to `A` in `src/sase/default_config.yml`.
   - Change `ace.keymaps.app.open_agent_artifacts` from `A` to `a` in `src/sase/default_config.yml`.
   - Mirror the same swap in `src/sase/ace/tui/bindings.py` fallback `DEFAULT_BINDINGS`.

2. Keep contextual behavior unchanged.
   - Do not change `action_accept_proposal()` dispatch logic.
   - Do not change `action_open_agent_artifacts()` artifact discovery/opening logic.
   - Do not add any synchronous work to key handlers; this remains a binding/default swap and respects the TUI
     performance guidance.

3. Update user-facing references.
   - Update `docs/ace.md` Agents action table and Agent Artifacts section.
   - Update artifact docs that explicitly say the Agents tab opens artifacts with `A`, including `docs/agent_images.md`
     and `docs/notifications.md`.
   - Review the Agents help modal tests or expectations as needed; the help modal itself should pick up the new keys
     through the registry.

4. Update tests that encode the old defaults.
   - Adjust keymap construction/default tests, especially `tests/test_keymaps_app_bindings.py` and
     `tests/ace/tui/test_show_agent_run_log_keymap.py`.
   - Adjust Agents footer tests so artifacts are expected on `a` and auto-approve/HITL on `A`, while preserving tests
     that custom registries remap footer keys.
   - Add or adjust a registry/default guard that explicitly asserts the new swapped defaults to prevent regression.

5. Validate.
   - Run focused tests for keymaps, footer bindings, command availability, and the run-log keymap guard:
     - `pytest tests/test_keymaps_app_bindings.py tests/test_keymaps_defaults.py tests/test_keymaps_registry_loading.py tests/test_keybinding_footer_agent.py tests/test_keybinding_footer_core.py tests/ace/tui/test_show_agent_run_log_keymap.py tests/test_command_availability.py`
   - If focused tests pass and time permits, run a broader TUI/keymap subset:
     - `pytest tests/ace/tui tests/test_keymaps_*.py tests/test_keybinding_footer_*.py`

## Risks and Checks

- `accept_proposal` is shared by the PRs and Agents tabs, so this default swap also makes PR proposal acceptance use `A`
  unless the codebase supports tab-local app defaults. That appears consistent with the current app-level keymap
  architecture, but it should be called out in the final summary.
- User configs overriding either key will continue to win over defaults; duplicate-key validation should still behave
  normally.
- Leader-mode `,A` is a separate run-log fallback key and should not be changed.
- Modal-local keymaps, such as artifact modal `A` for "open all", should not be changed unless tests reveal they
  intentionally mirror the Agents-tab opener.
