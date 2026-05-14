---
create_time: 2026-05-14 11:56:45
status: done
---
# Plan: Move Mark-All-Unread Leader Key From `,U` To `,u`

## Goal

Change the default SASE ACE leader-mode binding for `mark_all_unread_done_agents_read` from uppercase `U` to lowercase
`u`, so the trigger becomes `,u`.

## Current Understanding

The binding is registry-driven:

- `src/sase/ace/tui/keymaps/types.py` defines the typed `LeaderModeKeymaps` default.
- `src/sase/default_config.yml` defines the bundled user-facing default config.
- `LeaderModeMixin._dispatch_leader_key` compares incoming keys against the registry value, so dispatch should follow
  the config once the default changes.
- Help and footer rendering already read from the registry, but static docs and tests still mention or assert `,U`.

Relevant current references found:

- `src/sase/default_config.yml`
- `src/sase/ace/tui/keymaps/types.py`
- `docs/ace.md`
- `tests/test_keymaps.py`
- `tests/ace/tui/test_show_agent_run_log_keymap.py`

Historical SDD tale files also mention the old migration to `U`; those appear to be historical design records, not
active runtime behavior. I will avoid changing them unless the implementation or tests prove they are
generated/validated docs.

## Implementation Steps

1. Update typed leader-mode defaults in `src/sase/ace/tui/keymaps/types.py`:
   - Change `mark_all_unread_done_agents_read` from `"U"` to `"u"`.

2. Update bundled YAML defaults in `src/sase/default_config.yml`:
   - Change `ace.keymaps.modes.leader_mode.keys.mark_all_unread_done_agents_read` from `"U"` to `"u"`.

3. Update user-facing docs in `docs/ace.md`:
   - Change the Agents tab leader-mode table entry from `,U` to `,u`.

4. Update tests that assert or exercise the old default:
   - In `tests/test_keymaps.py`, update the expected default and the test docstring/name if needed.
   - In `tests/ace/tui/test_show_agent_run_log_keymap.py`, update the default assertion and dispatch tests from
     `_handle_leader_key("U")` to `_handle_leader_key("u")`; rename test functions/docstrings where they would otherwise
     be misleading.

5. Re-scan for active references:
   - Run `rg -n ',U|mark_all_unread_done_agents_read.*"U"|_handle_leader_key\("U"\)'` and review any remaining matches.
   - Leave historical SDD matches alone if they are only archived context.

6. Validate:
   - Per repo memory, run `just install` before checks if this workspace may be stale.
   - Run the focused tests first: `pytest tests/test_keymaps.py tests/ace/tui/test_show_agent_run_log_keymap.py`.
   - Because source/doc/test files changed, run `just check` before final reply.

## Risks And Checks

- Lowercase `u` could conflict with another leader-mode subkey. The current leader defaults include `j`, `J`, `r`, `R`,
  etc., but no `u`; keymap duplicate validation and the focused tests should catch accidental collisions.
- Existing user configs that explicitly bind the action to `U` should continue to work because this changes only
  defaults, not action names or dispatch logic.
- Help modal and footer output should follow the registry automatically; if a test or grep shows static text elsewhere,
  update that static reference too.
