---
create_time: 2026-05-21 09:02:35
status: done
prompt: sdd/prompts/202605/fast_manual_agents_refresh.md
---
# Plan: Make Agents `y` Refresh Use The Active Index Path

## Problem

Pressing `y` on the Agents tab still takes roughly 3 seconds in large local histories. The refresh is already routed
through `_schedule_agents_async_refresh()`, so the issue is not the key binding doing synchronous work directly. The
slow part is the load scope selected by `action_refresh()`.

Today `src/sase/ace/tui/actions/base.py::action_refresh()` checks `_agents_history_reconcile_pending`. If that flag is
set, a manual Agents refresh clears the flag and schedules `_schedule_agents_async_refresh(full_history=True)`. That
forces `_load_agents_async()` into the Tier 2 source scan path in `src/sase/ace/tui/models/agent_loader.py`, bypassing
the SQLite artifact index. That Tier 2 scan is the known multi-second path.

The fast path already exists: `full_history=False` calls `_query_artifact_index_for_loader()`, which queries
`~/.sase/agent_artifact_index.sqlite` for active rows plus a bounded recent-completed window. The Rust query already
filters dismissed identities through the `dismissed_agents` table and avoids full artifact-tree fan-out.

## Goal

Make the manual `y` refresh on the Agents tab a quick "refresh what should normally be visible now" action, backed by
the active artifact index/Tier 1 loader. Keep full-history reconciliation available for background idle/startup
reconcile, revive, and explicit full-history/search paths.

## Proposed Change

1. Change the Agents branch of `action_refresh()` so it does not promote pending Tier 2 reconciliation to
   `full_history=True`.
   - Schedule `_schedule_agents_async_refresh(full_history=False)` or just `_schedule_agents_async_refresh()`.
   - Do not clear `_agents_history_reconcile_pending`; leave the existing idle/startup Tier 2 mechanisms to reconcile
     history later.
   - Keep the immediate `"Refreshed"` toast behavior unchanged.

2. Update comments/docstrings that currently describe manual `y` as an "explicit escape hatch" to full history.
   - `tests/ace/tui/test_lazy_tier2_reconcile.py` has a module docstring saying manual refresh triggers the reconcile.
   - `src/sase/ace/tui/actions/agents/_loading_apply.py` comments also mention manual `y` promotion.
   - Replace that language with the new contract: manual `y` refreshes the index-backed Tier 1 view; idle/startup
     reconcile remains responsible for full history.

3. Keep the loader query shape conservative.
   - Do not add an active-only query mode in this first patch. The existing Tier 1 query is already the active index
     path plus a bounded recent-completed slice, which preserves current visible completed rows and avoids surprising
     list shrinkage.
   - Do not change `full_history=True`; revive and other explicit history-dependent operations still need source-of-
     truth artifact scans.

4. Add focused tests for the new refresh contract.
   - Add or extend a small unit test around `action_refresh()` with a fake app on the Agents tab:
     `_agents_history_reconcile_pending=True`, call `action_refresh()`, assert the scheduled refresh uses
     `full_history=False` and the pending flag remains true.
   - Add a companion case with no pending reconcile to ensure the normal manual refresh still schedules once.
   - Update lazy Tier 2 tests so idle and startup triggers still schedule `full_history=True`; the change must not
     weaken those existing paths.
   - Keep existing loader tests that assert Tier 1 uses `query_agent_artifact_index()` and Tier 2 uses source scan.

## Files To Touch

- `src/sase/ace/tui/actions/base.py`
- `src/sase/ace/tui/actions/agents/_loading_apply.py`
- `tests/ace/tui/test_lazy_tier2_reconcile.py`
- Possibly a new focused test file under `tests/ace/tui/` if there is no clean existing home for `action_refresh()`.

## Out Of Scope

- Changing the default Tier 1 query from active-plus-recent to active-only.
- Changing the startup/idle Tier 2 reconcile policy.
- Changing revive, search, or explicit full-history behavior.
- Reworking the artifact-index schema or lifecycle hooks.
- Keymap/config changes; `y` remains the manual refresh binding.

## Validation

Run the focused tests first:

```bash
.venv/bin/python -m pytest tests/ace/tui/test_lazy_tier2_reconcile.py tests/ace/tui/actions/test_agent_loader_phase5_wiring.py
```

Then run the repository-required check after code changes:

```bash
just install
just check
```

Manual verification: open `sase ace` on the Agents tab in a large-history workspace, press `y`, and confirm the refresh
settles through the index-backed Tier 1 path rather than waiting for the multi-second full-history scan.
