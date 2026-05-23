---
create_time: 2026-05-23 16:11:33
status: done
prompt: sdd/prompts/202605/ctrl_o_fast_jump.md
---
# Ctrl+O Fast Jump Plan

## Context

The current single-quote jump flow is two-step:

1. `action_jump_to_entry()` builds jump hint maps, enters jump mode, updates the jump footer, and refreshes the visible
   list to paint hint chips.
2. `_handle_entry_jump_key("apostrophe")` implements the second `'` behavior:
   - if a per-tab jump-back target exists, jump back and update the saved origin so repeated use toggles;
   - otherwise dispatch the first visible jump target by falling through as hint `1`;
   - on Agents, preserve panel focus and collapsed-banner behavior, and honor the artifact-viewer navigation guard.

The requested `<ctrl+o>` key should behave like that two-key `''` sequence, but without rendering intermediate hint UI.

Important conflict: `ctrl+o` is currently the default key for `prev_changespec_history`. That binding is active through
`default_config.yml` and the registry-driven Textual bindings, so the new keymap cannot safely share the same default
key. The implementation should explicitly make `ctrl+o` the new fast jump key and move the older previous-CL-history
binding to a non-conflicting default.

## Proposed Design

Add a new app-level keymap/action, tentatively named `jump_to_entry_fast`, with default key `ctrl+o`.

The action should not call `action_jump_to_entry()`, because that would still perform the expensive hint-footer/list
refresh. Instead it should:

1. Build the same in-memory jump target maps that normal jump mode would build for the active tab.
2. Temporarily mark jump mode active only long enough to reuse `_handle_entry_jump_key("apostrophe")`.
3. Let the existing apostrophe dispatch code perform the actual selection/back-jump state changes and final refresh.

This keeps one source of truth for the tricky behavior: saved back targets, Agents panel focus, collapsed banner
targets, stale anchor fallback, ChangeSpec grouped banners, and AXE list selection all continue to use the existing
dispatch path.

To make that clean, factor the map-building parts of `_begin_changespec_jump_mode()` and `_begin_agents_jump_mode()`
into small helpers that return `True` when maps are ready. The normal quote action will call those helpers and then
render hints; the new fast action will call those helpers and immediately dispatch apostrophe without hint rendering.

For the `ctrl+o` conflict, update the default keymap so:

- `jump_to_entry_fast: "ctrl+o"`
- `prev_changespec_history` moves to a non-conflicting default, with help text and tests updated to match.

## Files To Change

- `src/sase/default_config.yml`
  - Add the new app keymap default.
  - Reassign `prev_changespec_history` away from `ctrl+o`.

- `src/sase/ace/tui/keymaps/types.py`
  - Add the new `AppKeymaps` field.
  - Add binding metadata for the action.

- `src/sase/ace/tui/actions/navigation/_advanced.py`
  - Factor jump-map preparation helpers.
  - Add `action_jump_to_entry_fast()` using the existing apostrophe dispatch path without intermediate hint UI.
  - Update comments/docstrings that currently describe ChangeSpec history as `ctrl+o`.

- `src/sase/ace/tui/bindings.py`
  - Keep fallback bindings in sync with the registry defaults.

- `src/sase/ace/tui/commands/catalog.py`
  - Add command-palette metadata for the new action.

- Help/footer-adjacent display tests or help modal sections as needed
  - Show the new fast jump binding in the Navigation help rows where `jump_to_entry` is documented.

## Tests

Add focused unit coverage for the new action:

1. ChangeSpecs tab, no saved jump history:
   - starting from index 2, `action_jump_to_entry_fast()` lands on the first visible target and records the previous
     index.
   - it does not call `_update_jump_footer()`.

2. ChangeSpecs tab, saved jump history:
   - `action_jump_to_entry_fast()` jumps back to the saved index and updates the saved origin, matching `''`.

3. Agents tab, no saved anchor:
   - with a collapsed first banner, fast jump dispatches the first visible jump target and records the origin.

4. Agents tab, saved anchor:
   - fast jump restores the saved anchor, preserving panel/group behavior.

5. Keymap registry/build guards:
   - default registry exposes `jump_to_entry_fast == "ctrl+o"`.
   - `build_app_bindings()` includes the new action and no longer assigns `ctrl+o` to `prev_changespec_history`.
   - command catalog coverage remains in sync with `AppKeymaps`.

Run at least the targeted tests:

```bash
just install
uv run pytest tests/test_keymaps.py tests/test_command_catalog_guards.py tests/ace/tui/test_jump_to_entry_hints.py tests/ace/tui/test_jump_hints_for_folded_banners.py
```

If implementation files are changed, finish with the repo-required:

```bash
just check
```
