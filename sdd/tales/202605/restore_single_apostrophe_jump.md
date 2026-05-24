---
create_time: 2026-05-24 10:18:46
status: wip
prompt: sdd/prompts/202605/restore_single_apostrophe_jump.md
---
# Restore Single Apostrophe Jump While Removing Double Apostrophe

## Problem

The prior implementation removed the entire app-level `jump_to_entry` keymap. That made the single apostrophe key stop
opening current-tab jump hints, even though the intended change was narrower: remove the double-apostrophe first/back
shortcut while keeping the normal apostrophe jump mode.

There are two different behaviors currently coupled together:

- The app-level binding `apostrophe -> action_jump_to_entry`, which should remain and should open inline current-tab
  jump hints.
- The jump-mode handler branch for `key == "apostrophe"`, which implements the second keypress in `''` by jumping back
  or falling through to the first hint. This is the behavior that should be removed from the user-facing apostrophe
  flow.

`Ctrl+O` should continue to provide the fast first/back behavior, but it should no longer depend on treating
`apostrophe` as a public in-jump shortcut.

## Proposed Implementation

1. Restore the single apostrophe app-level keymap surface.
   - Re-add `jump_to_entry: "apostrophe"` to `src/sase/default_config.yml`.
   - Re-add `jump_to_entry` to `AppKeymaps` and `_BINDING_META` in `src/sase/ace/tui/keymaps/types.py`.
   - Re-add the fallback `Binding("apostrophe", "jump_to_entry", "Jump to Entry", show=False)` in
     `src/sase/ace/tui/bindings.py`.
   - Re-add `jump_to_entry` to `_APP_COMMAND_META` in `src/sase/ace/tui/commands/catalog.py`.

2. Decouple fast jump from the public double-apostrophe handler.
   - Extract the existing first/back logic from `_handle_entry_jump_key("apostrophe")` into a helper with a name that
     describes the behavior, such as `_dispatch_entry_jump_first_or_back()`.
   - Have `action_jump_to_entry_fast()` call that helper directly after preparing maps, preserving current `Ctrl+O`
     behavior and its no-footer/no-hints path.
   - Change `_handle_entry_jump_key("apostrophe")` so an apostrophe pressed while jump mode is already active no longer
     selects the first target or restores jump history. It should consume the key and leave jump mode in a predictable
     state, most likely by exiting jump mode like any invalid jump key.

3. Update jump-mode footer/help/docs to match the intended UX.
   - Restore help-modal rows and `docs/ace.md` navigation tables that advertise `'` as “Jump to entry by hint character
     (current tab)”.
   - Keep `Ctrl+O` documented as the fast first/back command.
   - Do not document `''` as a jump-back shortcut.
   - Update the jump footer so it no longer advertises `"' first"` or `"' back"` while inline jump mode is active.

4. Update regression tests around the corrected contract.
   - Restore keymap and command-catalog assertions that `app.jump_to_entry` exists and defaults to apostrophe, while
     `app.jump_to_entry_fast` remains `Ctrl+O`.
   - Replace tests that currently assert `_handle_entry_jump_key("apostrophe")` performs first/back with tests that
     assert the second apostrophe is consumed without navigating.
   - Keep and extend `action_jump_to_entry_fast()` tests so `Ctrl+O` still covers first-target fallback, stack pop,
     stale-history handling, folded banners, and agents-panel anchors.
   - Leave modal-local apostrophe tests alone unless they fail because those modals have separate local bindings.

## Validation

Run focused tests first:

```bash
.venv/bin/pytest tests/test_keymaps.py tests/test_command_catalog.py tests/test_command_catalog_guards.py \
  tests/ace/tui/test_jump_to_entry_hints.py tests/ace/tui/test_jump_hints_for_folded_banners.py \
  tests/ace/tui/test_agent_sibling_navigation.py
```

Then run the repository check because production code and docs will change:

```bash
just check
```

If `uv run` is still blocked by the existing lockfile/source issue seen in the previous run, use the installed `.venv`
for targeted pytest and still run `just check` for the full project gate.
