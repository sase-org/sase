---
create_time: 2026-04-29 21:43:44
status: done
prompt: sdd/prompts/202604/grouping_strategy_persistence.md
---
# Persist ACE Grouping Strategy

## Context

The `sase ace` TUI has two independent grouping states:

- Agents tab: `GroupingMode` in `src/sase/ace/tui/models/agent_groups/_buckets.py`, currently defaulting to `STANDARD`.
- CLs tab: `ChangeSpecGroupingMode` in `src/sase/ace/tui/models/changespec_groups/_buckets.py`, currently defaulting to
  `BY_PROJECT`.

Both states are cycled by the shared `o`/`O` actions in `src/sase/ace/tui/actions/agents/_grouping.py`. The backing fold
registries are already per-mode and per-tab, so persistence only needs to restore the active mode and point the active
fold registry at the restored mode's registry.

There are existing tests under `tests/ace/tui/` that assert old grouping files are ignored and that cycling does not
write grouping files. Those tests describe the old contract and should be updated to assert the new behavior.

## Goals

1. On `sase ace` startup, restore the last persisted grouping mode for both the Agents tab and the CLs tab.
2. Keep Agents and CLs grouping strategies separate on disk and in memory.
3. Save the new grouping strategy whenever the `o` or `O` keymap changes the focused tab's grouping mode.
4. Ensure save I/O never blocks the Textual event loop or synchronous key handler path.
5. Avoid stale final state if the user presses `o`/`O` repeatedly while earlier saves are still running.
6. Treat missing, invalid, or stale file content as non-fatal and fall back to current defaults.

## Design

Add a focused persistence module, likely `src/sase/ace/grouping_strategy.py`, that owns the on-disk contract:

- Agents file: `~/.sase/grouping_mode.txt`
- CLs file: `~/.sase/changespec_grouping_mode.txt`
- Values: enum `.value` strings such as `standard`, `by_date`, `by_status`, and `by_project`.

The module should expose small typed helpers:

- `load_agent_grouping_mode(default=GroupingMode.STANDARD) -> GroupingMode`
- `save_agent_grouping_mode(mode: GroupingMode) -> bool`
- `load_changespec_grouping_mode(default=ChangeSpecGroupingMode.BY_PROJECT) -> ChangeSpecGroupingMode`
- `save_changespec_grouping_mode(mode: ChangeSpecGroupingMode) -> bool`

The load helpers should catch `OSError`, strip whitespace, validate against enum values, and return the default on bad
content. The save helpers should create `~/.sase`, write the enum value plus a trailing newline, and return `False` on
`OSError`.

Update `_init_app_state` so startup initializes each active grouping mode from these load helpers instead of hard-coded
defaults. After loading a mode, initialize that tab's per-mode fold registry dictionary with the loaded mode as the
initial key and set the active registry pointer from that dictionary.

For nonblocking saves, add a small latest-value scheduler around the grouping cycle action rather than writing directly
from `_cycle_*_grouping_mode`. The scheduler can live in `AgentGroupingMixin` because the lifecycle is tied to the TUI
app instance:

- Maintain per-target pending mode and an in-flight flag, e.g. for `"agents"` and `"changespecs"`.
- When `o`/`O` changes a mode, update the pending mode and return immediately after refreshing the UI.
- If no save is in flight for that target, schedule an async runner with `call_later`.
- The runner writes the pending mode via `asyncio.to_thread(...)`.
- When the write completes, if the pending mode changed while the worker was running, schedule another write for the
  latest value.

This gives the key handler an O(1), no-I/O path and prevents rapid keypresses from leaving an older mode as the final
persisted value. It also keeps Agents and CLs independent because each target has its own file and in-flight state.

## Implementation Steps

1. Add the persistence module with load/save helpers and unit-testable paths.
2. Update `StateInitMixin._init_app_state` to load persisted Agents and CLs grouping modes and initialize registries
   from those restored modes.
3. Add async latest-value save scheduling to `AgentGroupingMixin`.
4. Call the scheduler from `_cycle_agents_grouping_mode` and `_cycle_changespec_grouping_mode` immediately after the
   in-memory mode swap, before or after the UI refresh. The save must not be awaited by the key handler.
5. Keep AXE tab behavior unchanged: `o`/`O` remains a silent no-op and should not save either file.
6. Update tests:
   - Replace the old "startup ignores stale grouping files" assertions with startup restore assertions.
   - Replace the old "cycle does not write grouping file" assertions with save-scheduling assertions.
   - Add a rapid-cycle/coalescing test that proves the latest mode is saved when a previous save is still in flight.
   - Keep independence tests for Agents vs CLs and AXE no-op behavior.
7. Run focused tests first, then `just install` if needed and `just check` before final response, per repo memory.

## Risks And Mitigations

- **Race on repeated keypresses:** avoid direct fire-and-forget writes; use latest-value scheduling per target.
- **Bad legacy content:** validate enum values and fall back to defaults without surfacing startup errors.
- **Cross-tab overwrite:** use separate files and separate save state for Agents and CLs.
- **Test fakes without a full Textual app:** make the scheduler tolerant of `call_later` fakes used by existing tests,
  and keep persistence helpers separately unit-testable.
