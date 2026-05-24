---
create_time: 2026-05-24 10:06:28
status: done
prompt: sdd/prompts/202605/remove_apostrophe_jump_keymap.md
---
# Remove Apostrophe Jump Keymap

## Goal

Remove the app-level double-apostrophe jump keymap surface so the Ace TUI only defines `Ctrl+O` for the current-tab
first/back jump behavior. The change should keep the existing `Ctrl+O` behavior intact: jump back when a jump-back
anchor exists, otherwise select the first current-tab jump target, without first painting hint UI.

## Current Behavior

- `src/sase/default_config.yml` defines both:
  - `jump_to_entry: "apostrophe"`
  - `jump_to_entry_fast: "ctrl+o"`
- The keymap pipeline exposes both app actions through `AppKeymaps`, `_BINDING_META`, fallback `DEFAULT_BINDINGS`, the
  command catalog, and help-modal keybinding sections.
- `action_jump_to_entry()` enters the hint-rendering current-tab jump mode.
- `action_jump_to_entry_fast()` prepares the same jump maps, marks jump mode active, and dispatches
  `_handle_entry_jump_key("apostrophe")` internally. That internal apostrophe token is behavior, not a user-facing
  keymap definition.
- Tests and docs still encode the separate user-facing apostrophe jump mode in several places.

## Proposed Scope

1. Remove the user-configurable app action/keymap for `jump_to_entry`.
2. Keep `jump_to_entry_fast` as the only app-level current-tab jump keymap, bound to `ctrl+o`.
3. Keep the internal jump map and back-stack behavior that `jump_to_entry_fast` relies on.
4. Update help and docs so they no longer advertise `'` / `''` as the normal Ace TUI current-tab jump key.
5. Update tests so keymap/config/catalog coverage expects only `jump_to_entry_fast` for this path, while retaining
   focused behavioral coverage for `action_jump_to_entry_fast()`.

## Implementation Plan

1. Update app keymap source of truth:
   - Remove `jump_to_entry: "apostrophe"` from `src/sase/default_config.yml`.
   - Remove `jump_to_entry` from `AppKeymaps`.
   - Remove `jump_to_entry` from `_BINDING_META`.
   - Remove the fallback `Binding("apostrophe", "jump_to_entry", ...)` from `src/sase/ace/tui/bindings.py`.

2. Update public command/help surfaces:
   - Remove `jump_to_entry` from `_APP_COMMAND_META` in `src/sase/ace/tui/commands/catalog.py`.
   - Remove help-modal rows that display `a.jump_to_entry`.
   - Keep and possibly clarify the `jump_to_entry_fast` help text as the only current-tab jump binding.

3. Preserve runtime behavior intentionally:
   - Leave `action_jump_to_entry_fast()` in place.
   - Leave `_handle_entry_jump_key("apostrophe")` support in place because `Ctrl+O` uses it as an internal dispatch
     token for the first/back behavior.
   - Leave `action_jump_to_entry()` in place unless removing it is clearly safe after test updates. It is still useful
     as the hint-mode implementation entry point and for focused unit tests, but it will no longer be bound or exposed
     as a configurable app command.

4. Update docs:
   - Remove the `'` key rows from the CLs and Agents navigation tables.
   - Rewrite the Jump Back section to describe `Ctrl+O` as the current-tab first/back shortcut, without documenting `''`
     as a user-facing keymap.

5. Update tests:
   - Adjust binding-count expectations for one fewer configurable app binding.
   - Add or update assertions that no app binding uses `apostrophe` for `jump_to_entry`.
   - Update catalog tests to assert `app.jump_to_entry` is absent and `app.jump_to_entry_fast` remains `Ctrl+O`.
   - Update help-modal expectations where they reference the removed `jump_to_entry` row.
   - Keep existing `action_jump_to_entry_fast()` behavior tests. Rename or adjust apostrophe-specific tests where needed
     so they are explicitly testing internal jump-mode handling rather than a public keymap.

6. Validate:
   - Run targeted tests around keymaps, command catalog, help bindings, and jump behavior first.
   - Because production files will be changed, run `just install` if needed and then `just check` before completion.

## Risks

- Removing the `AppKeymaps` field requires synchronized edits across config, binding metadata, and command catalog; the
  existing consistency tests should catch drift.
- Removing the public `jump_to_entry` command means hint-rendered current-tab jump mode may no longer be reachable from
  the normal app. That matches the stated goal of only defining `Ctrl+O`, but tests should still cover the retained fast
  jump path.
- Modal-local apostrophe bindings in notification/model picker modals are separate modal bindings, not the Ace app-level
  keymap. I will avoid changing them unless follow-up inspection shows the request is intended to remove modal-local
  apostrophe jump behavior too.
