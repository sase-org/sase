---
create_time: 2026-06-22 09:22:59
status: done
prompt: sdd/prompts/202606/at_keymap_to_plus.md
---
# Change ACE `@` Agent Launcher Keymap To `+`

## Context

ACE app-level keybindings are loaded from `src/sase/default_config.yml` through the keymap registry in
`src/sase/ace/tui/keymaps/`. The app currently binds `start_custom_agent` to `at`, which Textual displays as `@`. That
action opens the project/custom-agent selector on all ACE tabs.

This change should target only the app-level custom-agent launcher. It should not change:

- prompt-input `@` behavior for xprompt inline expansion or file/reference syntax;
- the `ctrl+@` canonical Textual spelling used for Ctrl+Space repeat-last agent selection;
- proposal/help text where `@` refers to mail/spec proposal options rather than the launcher key;
- VCS project completion `+` behavior inside the prompt input, which is widget-local and already intentional.

Textual normalizes the printable `+` key to the key name `plus`, so the implementation should use `plus` as the
configured binding and display it as `+`.

## Implementation Plan

1. Update the default binding source of truth:
   - Change `ace.keymaps.app.start_custom_agent` in `src/sase/default_config.yml` from `at` to `plus`.
   - Update the fallback `DEFAULT_BINDINGS` entry in `src/sase/ace/tui/bindings.py` from `Binding("at", ...)` to
     `Binding("plus", ...)`.

2. Teach the keymap layer how to validate and render plus:
   - Add `plus` to `_KEY_DISPLAY` in `src/sase/ace/tui/keymaps/types.py` as `+`.
   - Prefer accepting raw `+` as a friendly config spelling by canonicalizing it to `plus`; consider accepting
     `plus_sign` as a compatibility alias because Textual maps the Unicode name to `plus`.
   - Keep `at` supported as a valid key name for user overrides, but it should no longer be the default.

3. Update user-facing surfaces that derive from the registry or still mention the old launcher:
   - The help modal should automatically display `+` for `start_custom_agent` once the registry changes.
   - Replace stale `@/Ctrl+Space` wording for the repeat-last custom-agent selection with `+/Ctrl+Space`, where it
     refers to the custom-agent selector flow.
   - Update command palette metadata for `start_custom_agent` so the default key display and search aliases point at `+`
     rather than `@`.
   - Leave unrelated `@` wording alone when it describes xprompt syntax, agent names/tags, or proposal mail behavior.

4. Update focused tests:
   - Key validation/display tests should cover `plus`, friendly raw `+` canonicalization if implemented, and footer/help
     display as `+`.
   - Registry/default tests should assert `start_custom_agent == "plus"` while `start_agent_home == "space"` and
     `start_agent_from_changespec == "ctrl+@"` remain unchanged.
   - Binding-construction tests should assert `start_custom_agent` produces a `plus` binding.
   - Command catalog tests should assert the custom-agent command uses `+`.
   - Add or adjust an ACE pilot test so pressing `plus` dispatches `action_start_custom_agent`, and pressing `at` no
     longer does so with default config.

5. Verify with targeted tests first:
   - `python -m pytest tests/test_keymaps_validation.py tests/test_keymaps_display_help.py tests/test_keymaps_registry_loading.py tests/test_keymaps_app_bindings.py tests/test_command_catalog.py tests/test_keymaps_e2e.py`
   - Include any touched adjacent tests, such as `tests/ace/tui/test_show_agent_run_log_keymap.py`, if expectations
     move.

6. Final repo verification:
   - Run `just install` if the workspace has not already been refreshed.
   - Run `just check` after implementation because this will change non-SDD source/test files.

## Risks And Checks

- `+` is already meaningful inside the prompt input for VCS project completion. The app-level binding should only fire
  when the prompt widget is not focused; the pilot test should catch accidental global interception.
- Raw punctuation has historically used Textual-friendly names like `minus`, `equals_sign`, and `at`. Supporting raw `+`
  should be narrowly scoped to this key unless a broader punctuation-alias policy is intentionally introduced.
- Existing user configs that explicitly bind `start_custom_agent: "at"` should continue to work as overrides; the
  default should move to `plus`.
