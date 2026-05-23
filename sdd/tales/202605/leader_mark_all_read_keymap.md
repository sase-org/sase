---
create_time: 2026-05-23 17:02:49
status: done
prompt: sdd/prompts/202605/leader_mark_all_read_keymap.md
---
# Plan: Move Mark-All-Read Leader Command to `,u`

## Context

The current runtime behavior binds the Agents-tab leader command `mark_all_unread_done_agents_read` to `,U`, because the
merged application config loads `src/sase/default_config.yml` and that file currently sets:

```yaml
mark_all_unread_done_agents_read: "U"
```

That conflicts with the intended and already partially documented/defaulted behavior:

- `LeaderModeKeymaps` in `src/sase/ace/tui/keymaps/types.py` defaults the same action to `"u"`.
- `docs/ace.md` documents the Agents-tab command as `,u`.
- Existing keymap unit tests already expect the bare dataclass registry path to use `"u"`.

The practical bug is drift between the packaged default config path and the typed/default/documented keymap path. Normal
ACE startup uses merged config, so the packaged default config wins and users see `,U`.

## Design

Make `,u` the single default trigger for the existing mark-all-read leader action by aligning the packaged default
config with the typed leader default. Keep the direct Agents-tab `U` binding unchanged, because that key toggles the
focused agent's unread marker and is a separate app-level action (`toggle_agent_unread`).

This should be a default-keymap correction, not a behavioral rewrite:

- No changes to `_mark_all_unread_done_agents_read()` behavior.
- No changes to leader dispatch semantics.
- No alias for `,U` unless a compatibility requirement emerges; the request is to start using `,u`, and the rest of the
  source already treats `,u` as the intended default.

## Implementation Steps

1. Update `src/sase/default_config.yml` so `ace.keymaps.modes.leader_mode.keys.mark_all_unread_done_agents_read` is
   `"u"` instead of `"U"`.
2. Add or strengthen regression coverage for the production-like merged-default path, not only
   `load_keymap_registry({})`, so future drift between `default_config.yml` and `LeaderModeKeymaps` is caught.
3. Check whether any docs or help/footer expectations still mention `,U`. Update only if needed; current docs already
   advertise `,u`.
4. Run focused keymap tests, then run the repo-required `just check` because the change touches repo files.

## Verification

Focused verification:

```bash
.venv/bin/python -m pytest tests/test_keymaps.py tests/test_command_catalog_guards.py
```

Required repository verification after file changes:

```bash
just check
```
