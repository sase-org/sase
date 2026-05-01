---
create_time: 2026-05-01 00:00:00
status: complete
bead_id: sase-1p.7
---

# Agent Compose Phase 7 Default Handoff

## Summary

Phase 7 makes Rust agent-list composition the normal `load_all_agents()` route.
`SASE_AGENT_COMPOSE_BACKEND` now defaults to `rust`, so missing or stale
`sase_core_rs.compose_agent_list` bindings fail through the strict facade
instead of silently reusing the Python composer.

Changed files:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/core/agent_compose_facade.py`
- `tests/test_agent_loader.py`
- `docs/rust_backend.md`
- `plans/202604/agent_compose_phase7_default_handoff.md`

## Boundary

Rust owns deterministic visible-list composition: candidate merge/dedup, status
relationship overrides, follow-up and retry-chain relationships, and display
ordering.

Python still owns host state and side effects: ChangeSpec/project snapshots,
artifact scanning, process liveness checks, retry/tag/attempt and dismissed
bundle supplements, filesystem mutation, and transient notification-driven TUI
status overrides.

The Python composer remains available via `SASE_AGENT_COMPOSE_BACKEND=python`
as an explicit reference/debug route while the migration window is open. It is
not the default route and no product path falls back to it implicitly.

## Verification

```bash
just install
SASE_AGENT_COMPOSE_BACKEND=rust .venv/bin/pytest \
  tests/test_agent_loader.py \
  tests/test_agent_loader_dedup_pid.py \
  tests/test_agent_loader_status_overrides.py \
  -q
.venv/bin/pytest \
  tests/test_agent_loader.py \
  tests/test_agent_loader_changespec.py \
  tests/test_agent_loader_dedup_merge.py \
  tests/test_agent_loader_dedup_pid.py \
  tests/test_agent_loader_dedup_pid_safety_net.py \
  tests/test_agent_loader_dedup_vcs.py \
  tests/test_agent_loader_dedup_vcs_removal.py \
  -q
.venv/bin/pytest \
  tests/test_ace_tui_app.py::test_query_edit_modal_cancel \
  tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query \
  tests/test_command_palette_e2e.py::test_semicolon_opens_command_palette_from_agents_and_axe_tabs \
  tests/test_command_palette_e2e.py::test_palette_executes_refresh_from_agents_tab \
  tests/test_command_palette_e2e.py::test_palette_escape_dismisses_from_each_tab \
  -q
VIRTUAL_ENV=/home/bryan/projects/github/sase-org/sase_100/.venv \
  PYO3_PYTHON=/home/bryan/projects/github/sase-org/sase_100/.venv/bin/python \
  PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  LD_LIBRARY_PATH=/home/bryan/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib \
  just rust-check
just phase7-perf-check --smoke
just check
```
