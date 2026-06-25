---
create_time: 2026-06-25 11:04:34
status: done
prompt: sdd/prompts/202606/prompt_history_ctrl_k_load_more.md
---
# Plan: Rebind Prompt-History Load More from Ctrl+D to Ctrl+K

## Goal

Migrate the ACE prompt-history modal's "load 250 older prompts" shortcut from `Ctrl+D` to `Ctrl+K`.

The current prompt-history modal opens with the newest 250 prompt-history rows and loads older rows one page at a time.
Today that page load is wired to `Ctrl+D` in `PromptHistoryModal`. After this change, `Ctrl+K` should be the only
prompt-history-modal shortcut for loading the next 250 older prompts.

## Current Findings

- The in-scope implementation is `src/sase/ace/tui/modals/prompt_history_modal.py`.
- The page size is `_PROMPT_HISTORY_PAGE_SIZE = 250`.
- The modal currently declares `Binding("ctrl+d", "load_more", "Load More", priority=True)`.
- The modal also intercepts `ctrl+d` in `on_key()` because the focused `FilterInput` can consume `Ctrl+D` before normal
  bindings. This guard is load-bearing and should move to `ctrl+k` for the new key.
- The visible modal hints and count label currently advertise `^d`.
- The docs and help modal tables also advertise `Ctrl+D` / `^d` for loading older prompt-history pages.
- `Ctrl+K` already has two other meanings outside this modal:
  - In the prompt input, `Ctrl+K` opens prompt history.
  - At the app level, `Ctrl+K` walks forward through the jump stack.
- Those existing uses should remain intact. The new behavior is scoped to the open prompt-history modal, where a
  modal-level binding plus `on_key()` interception should prevent the key from bubbling to the app-level jump action.

## Scope

Change only the prompt-history modal load-more shortcut and the user-facing strings/tests that describe it.

Do not change:

- `src/sase/default_config.yml`: this modal shortcut is not part of the configurable keymap registry, and the existing
  app-level `jump_to_entry_forward: ctrl+k` should stay as-is.
- The prompt input's `Ctrl+K` shortcut that opens prompt history.
- The app-level `Ctrl+K` jump-forward command and command-catalog expectations.
- Other modals that use `Ctrl+D` for scrolling/deleting, including saved-agent-group revival, project management, hook
  history, logs, and preview panels.
- Historical `sdd/` records describing prior keymap choices.

## Implementation Plan

1. Update `PromptHistoryModal.BINDINGS`.
   - Replace the `ctrl+d` `load_more` binding with `ctrl+k`.
   - Keep the action name as `load_more` and keep `priority=True`.
   - Do not leave `ctrl+d` as an alias; the request is a migration, not an additive shortcut.

2. Update `PromptHistoryModal.on_key()`.
   - Move the load-more interception branch from `event.key == "ctrl+d"` to `event.key == "ctrl+k"`.
   - Continue to call `event.prevent_default()`, `event.stop()`, and `self.action_load_more()`.
   - Update the docstring/comment so it explains that `Ctrl+K` is intercepted while the filter input is focused and so
     the key cannot bubble to the app-level jump-forward binding.
   - Remove the old `Ctrl+D` load-more interception so `Ctrl+D` no longer loads older prompt-history pages.

3. Update modal UI strings.
   - Change the footer hint from `^d: older +250` to `^k: older +250`.
   - Change `_history_count_label()` from `^d +250 older` to `^k +250 older`.

4. Update help modal strings.
   - In `src/sase/ace/tui/modals/help_modal/agents_bindings.py`, change both prompt-history descriptions from
     `(^d older)` to `(^k older)`.
   - Make the same two-string change in `changespecs_bindings.py`.
   - Make the same two-string change in `axe_bindings.py`.
   - These strings become no longer than before, so they should stay within the help-modal width budget.

5. Update user docs.
   - In `docs/ace.md`, change the Prompt History Modal keybinding table from `Ctrl+D` to `Ctrl+K` for "Load older
     prompts (+250)".
   - In the Filtering section, change the prose from "Press `Ctrl+D` to load older pages" to `Ctrl+K`.

6. Update tests.
   - In `tests/ace/tui/modals/test_prompt_history_modal.py`, update the count-label assertion to expect `^k +250 older`.
   - Rename and update the existing pilot test from `test_ctrl_d_loads_more_without_deleting_filter_text` to the
     `Ctrl+K` behavior. It should mount the modal with a focused filter input, press `ctrl+k`, assert the second page
     was loaded, and assert the filter text is unchanged.
   - Add or adjust coverage to ensure `Ctrl+D` is no longer the load-more key. The simplest durable assertion is that a
     focused prompt-history modal does not append the next page when `ctrl+d` is pressed after the initial load.
   - Add a binding-level assertion if useful: `load_more` should be present on `ctrl+k` and absent on `ctrl+d`.

7. Update visual snapshots if needed.
   - The prompt-history PNG golden renders the footer hint line, so the `^d` to `^k` change may require regenerating
     `tests/ace/tui/visual/snapshots/png/prompt_history_modal_redesign_120x40.png`.
   - Only accept the visual update if the diff is exactly the intended hint text change.

## Verification

After implementation, run:

```bash
just install
just check
```

Run focused tests while iterating:

```bash
pytest tests/ace/tui/modals/test_prompt_history_modal.py
pytest tests/ace/tui/widgets/test_prompt_history_trigger.py
pytest tests/test_command_catalog.py -k "ctrl_k or fast_jump"
```

If the visual suite reports a prompt-history PNG mismatch, inspect the diff under `.pytest_cache/sase-visual/`, update
the snapshot with the repository's visual-snapshot update flag, and rerun the visual test.

## Risks

- `Ctrl+K` already means jump-forward outside the modal. This is acceptable only because the binding is modal-scoped and
  `on_key()` will stop the event while the prompt-history modal is active.
- `Ctrl+K` also opens prompt history from the prompt input. That behavior should stay unchanged because it applies
  before the modal exists; once the modal is open, `Ctrl+K` means "load older prompts".
- Removing the old `Ctrl+D` handler may expose Textual's focused-input default behavior for `Ctrl+D`. That is expected;
  the important regression check is that `Ctrl+D` no longer loads another prompt-history page.
- The old `Ctrl+D` key remains widely used elsewhere for half-page scrolling or deletion. Those surfaces must not be
  changed as part of this migration.
