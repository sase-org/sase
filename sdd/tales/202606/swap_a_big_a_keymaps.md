---
create_time: 2026-06-26 17:06:57
status: wip
prompt: sdd/prompts/202606/swap_a_big_a_keymaps.md
---
# Swap a/A ACE Keymaps Plan

## Goal

Swap the bare app-level `a` and `A` keymaps in `sase ace`:

- `A` should run the current `accept_proposal` action.
  - On the PRs tab, this accepts proposals.
  - On the Agents tab, this opens the auto-approve menu or answers HITL when the focused agent is waiting for input.
- `a` should run the current `open_agent_artifacts` action on the Agents tab.
  - It should still open the focused agent's artifact picker, the marked-agent artifact picker, or toggle the tracked
    tmux artifact viewer pane exactly as the action does today.

The action semantics should not change. This is a key assignment swap, not a rewrite of approval or artifact behavior.

## Scope

This plan targets the configurable ACE app-level keymaps only.

Keep these unrelated `a` / `A` bindings unchanged:

- Leader `,A` (`leader.agent_run_log`) remains the PR-tab Agent Run Log fallback. It is a different key sequence and is
  already separated by leader-mode dispatch.
- Modal-local keys remain local to their focused widgets, including plan approval modal `a`, artifact picker `A` for
  "open all", project-management pane `a` / `A`, mentor review modal `a` / `A`, and stash/cleanup modal local bindings.
- Prompt-editor vim-style `a` / `A` motions remain local to the prompt text area.

## Current Behavior

- The bundled keymap defaults in `src/sase/default_config.yml` set:
  - `accept_proposal: "a"`
  - `open_agent_artifacts: "A"`
- The Textual fallback binding list in `src/sase/ace/tui/bindings.py` mirrors those same physical keys.
- `src/sase/ace/tui/keymaps/loader.py` treats `default_config.yml` as the source of truth for production defaults, while
  `bindings.py` is still the fallback definition and should stay coherent.
- Help and footer surfaces generally resolve display keys dynamically through the keymap registry:
  - `src/sase/ace/tui/modals/help_modal/changespecs_bindings.py`
  - `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
  - `src/sase/ace/tui/widgets/_keybinding_bindings.py`
- Static docs and a handful of tests still encode the old physical keys and will need to be updated.

## Design

1. Swap the defaults in the two app-level key sources.
   - Change `accept_proposal` to `"A"` and `open_agent_artifacts` to `"a"` in `src/sase/default_config.yml`.
   - Change the corresponding fallback `Binding(...)` entries in `src/sase/ace/tui/bindings.py`.
   - Do not change `_BINDING_META`, action names, or action handlers; the existing registry and dispatcher should route
     the new keys to the same actions.

2. Preserve leader-mode behavior.
   - Leave `LeaderModeKeymaps().keys["agent_run_log"] == "A"` and the matching YAML leader key as-is.
   - Keep tests that prove `,A` opens the run-log modal, because this guards the important distinction between bare `A`
     and leader `,A`.

3. Let dynamic UI surfaces follow the registry.
   - The help modal and footer should automatically display `A` for approval/auto-approve and `a` for artifacts after
     the default config changes.
   - Update only comments, test names, or assertions that hard-code the old display keys.

4. Update static user-facing docs.
   - In `docs/ace.md`, change the PR action row from `a` to `A`.
   - In the Agents action table and Agent Artifacts section, change the artifact opener from `A` to `a` and the
     auto-approve/HITL action from `a` to `A`.
   - Leave the artifact modal's internal `A = Open all artifacts` documentation unchanged, because it is a focused modal
     binding.

5. Avoid config migration.
   - Existing user overrides under `ace.keymaps.app` should remain explicit preferences.
   - If a user override now collides with the new defaults, the existing duplicate-key validation path will handle it by
     warning and reverting the overridden action to its default. No new migration or compatibility shim is needed.

## Tests

Update focused tests that guard the keymap contract:

- `tests/test_keymaps_registry_loading.py` or `tests/test_keymaps_defaults.py`
  - Add or update assertions that `load_keymap_registry({}).app.accept_proposal == "A"` and
    `open_agent_artifacts == "a"`.

- `tests/test_keymaps_app_bindings.py`
  - Update the app-binding guard so `accept_proposal` is bound to `A`, `open_agent_artifacts` is bound to `a`, and
    `show_agent_run_log` remains `V`.

- `tests/test_keymaps_display_help.py`
  - Update help-modal expectations:
    - PR accept proposal displays `A`.
    - Agents auto-approve/HITL displays `A`.
    - Agents artifact pane displays `a`.
    - Leader `,A` still displays Agent Run Log.

- `tests/test_keybinding_footer_agent.py`
  - Update footer expectations so auto-approve/answer labels use the resolved `A` key and artifact labels use `a`.

- `tests/ace/tui/test_show_agent_run_log_keymap.py`
  - Update the default-key test name and assertions for bare `a` artifacts / bare `A` accept proposal while preserving
    the existing `,A` run-log dispatch tests.

- `tests/test_command_catalog.py`
  - Add or update a command-catalog assertion that `app.accept_proposal` displays `A` and `app.open_agent_artifacts`
    displays `a`, while `leader.agent_run_log` still displays `,A`.

Most direct `press("a")` / `press("A")` tests found during inspection are modal-local or prompt-editor tests and should
not change unless a focused app-level ACE test explicitly depends on the old bare key.

## Verification

After implementation, run focused tests first:

```bash
just install
pytest tests/test_keymaps_defaults.py tests/test_keymaps_registry_loading.py tests/test_keymaps_app_bindings.py tests/test_keymaps_display_help.py tests/test_keybinding_footer_agent.py tests/ace/tui/test_show_agent_run_log_keymap.py tests/test_command_catalog.py
```

Then follow repo policy for code changes:

```bash
just check
```

If `just check` reports ACE visual snapshot changes in help/footer surfaces, inspect the generated artifacts before
deciding whether snapshot updates are intentional.
