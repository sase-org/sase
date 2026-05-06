---
create_time: 2026-05-05 21:52:53
status: done
prompt: sdd/prompts/202605/running_agent_runtime_tick.md
---
# Plan: Increment RUNNING Agent Runtimes Each Second

## Problem

The Agents tab already updates the top info panel once per second for `(auto-refresh in <N>s)`, but the right-aligned
runtime suffix on RUNNING agent rows only changes when the agent list is rebuilt or a row is patched for some unrelated
mutation. The goal is to make those visible runtimes advance every second without adding meaningful load to the TUI.

## Current Shape

- `StartupMixin.on_mount()` installs a single one-second timer that calls `_on_countdown_tick()`.
- `_on_countdown_tick()` already updates only the currently visible tab's info/dashboard panel.
- Agent row runtimes are produced by `build_runtime_suffix()` via `compute_row_runtime(agent, now=...)`.
- `AgentList.patch_agent_row()` can replace one row prompt without rebuilding the OptionList.
- `AgentRenderCache` already keys active statuses (`RUNNING`, `WAITING`, `RETRYING`) by second-quantized `now`, so
  passing a stable `datetime.now()` for a tick gives correct cache invalidation while still allowing same-second cache
  hits.
- `_try_patch_agent_row()` is aimed at arbitrary agent mutations and updates the info panel, so it is too broad for a
  per-second clock tick.

## Design

Add a narrow runtime-tick path that reuses the existing countdown timer:

1. Extend `AgentList` with a lightweight `patch_active_runtime_rows(now: datetime) -> int` helper.
   - Iterate only over that widget's already-mounted local `_agents` list.
   - Patch only agents whose `status` is time-sensitive and whose rendered suffix can change on a clock tick: `RUNNING`,
     `WAITING` with `run_start_time`, and `RETRYING`.
   - Use existing `patch_agent_row(local_idx, now=now)` so row rendering, alignment, cache invalidation, and Textual
     prompt replacement stay centralized.
   - Do not fall back to a full rebuild if a row refuses to patch. A countdown tick is cosmetic; the next normal refresh
     will heal any stale row.

2. Add an AgentsMixin-level helper, e.g. `_patch_agent_runtime_rows()`.
   - Return immediately unless `current_tab == "agents"` and the first agent load has completed.
   - Query only mounted `AgentList` widgets under `#agent-list-container`.
   - Capture `now = datetime.now()` once per tick and pass it to each widget so all panels advance consistently.
   - Do not touch disk-backed state, panel grouping, tab counts, info panel state, detail panels, notifications, or
     auto-refresh scheduling.

3. Call the new helper from `_on_countdown_tick()` after `_update_agents_info_panel()` for the Agents tab.
   - Keep changespecs and axe behavior unchanged.
   - This means there is still only one one-second timer in the app.

## Performance Guardrails

- No new timers.
- No disk IO.
- No async work.
- No `update_list()` or tree rebuilding.
- No detail panel refresh.
- Work is proportional to mounted Agents-tab rows only, and only active runtime rows are patched.
- Failed cosmetic patches are ignored instead of escalating to expensive fallback work.

## Tests

Add focused tests near existing agent-list runtime/render-cache tests:

- `AgentList.patch_active_runtime_rows()` advances a RUNNING row from `59s` to `1m` with no row-count change.
- It skips terminal DONE rows.
- It skips pure WAITING rows that do not render a runtime suffix.
- If useful, a small mixin-level unit test can assert the countdown tick path calls the runtime patch helper only on the
  Agents tab, but the core risk is in the widget helper and can be covered without a full app harness.

## Verification

After implementation:

- Run the focused agent-list widget tests.
- Run `just install` if the workspace environment needs it.
- Run `just check` before replying, per repo instructions.
