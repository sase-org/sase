---
create_time: 2026-04-12 17:36:32
status: done
prompt: sdd/prompts/202604/remove_ace_agent_mode.md
---

# Plan: Remove `sase ace --agent` CLI Option

## Goal

Remove the `sase ace --agent` headless mode CLI surface and all supporting code. The `AcePage` testing DSL has fully
replaced this as the recommended way to test the ace TUI, so the CLI flag, its handler, and the `agent_runner.py` module
are dead weight. Utility functions still used by `AcePage` must be preserved by relocating them.

## Phases

### Phase 1: Relocate utility functions into `testing.py`

Move `capture_screen()`, `_get_modal_name()`, and `extract_state()` from `src/sase/ace/agent_runner.py` into
`src/sase/ace/testing.py`. These are used by `AcePage.state` and `AcePage.screen` properties. Update the import at line
8 of `testing.py` to use local definitions instead. The `json` and `Literal` imports in `agent_runner.py` are only
needed by `run_agent_mode()` — don't carry them over.

### Phase 2: Delete `agent_runner.py` and its tests

- Delete `src/sase/ace/agent_runner.py`
- Delete `tests/test_agent_runner.py`

### Phase 3: Remove CLI surface

- **`src/sase/main/parser_ace.py`**: Remove the `--agent` (`-a`), `--keys` (`-k`), and `--size` (`-s`) argument
  definitions (lines 52-69).
- **`src/sase/main/ace_handler.py`**: Remove the `if getattr(args, "agent", False)` block (lines 33-51), plus the
  now-unused `sys` import if nothing else uses it.

### Phase 4: Migrate `test_keymaps_e2e.py` to `AcePage`

Rewrite the two tests in `tests/test_keymaps_e2e.py` to use `AcePage` instead of `run_agent_mode()`. The `_patch_config`
mock for keymap overrides stays. Remove the local `_make_changespec`, `MOCK_CHANGESPECS`, and `_patch_changespecs`
helpers — `AcePage` handles changespec mocking internally.

### Phase 5: Update documentation

- **`docs/ace.md`**: Remove the 3 option table rows (`--agent`, `--keys`, `--size`) and the "Agent Mode (Headless)"
  section.
- **`docs/configuration.md`**: Remove the 3 configuration table rows.
- **`memory/e2e_testing.md`**: Remove the entire "`sase ace --agent` CLI (headless JSON)" section (lines 58-78).
