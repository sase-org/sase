---
create_time: 2026-05-06 00:19:52
status: done
prompt: sdd/prompts/202605/active_runtime_parent_rows.md
---
# Plan: Tick Runtime Suffixes For Active Parent Agent Rows

## Context

The Agents tab already has a low-cost per-second runtime update path. The countdown tick calls
`_patch_agent_runtime_rows()`, which only runs on the Agents tab after the first load, then asks each visible
`AgentList` to patch active runtime rows in place. This avoids a filesystem reload and avoids rebuilding the whole
option list.

The current eligibility check in `AgentList._runtime_suffix_ticks()` only patches rows whose status is `RUNNING`,
`RETRYING`, or post-wait `WAITING`. Parent rows such as `PLAN APPROVED`, `EPIC APPROVED`, `LEGEND APPROVED`, and
`PLAN COMMITTED` can represent an active follow-up agent step, but they are skipped by the cosmetic tick path. Their
displayed elapsed runtime therefore only changes on normal refreshes.

There is a second coupled concern: `AgentRenderCache` currently includes the quantized wall-clock second in the cache
key only for `RUNNING`, `WAITING`, and `RETRYING`. Any new ticking status must be treated as time-sensitive by the
render cache too, or the single-row patch may reuse stale `Text`.

## Goals

- Keep the current performance shape: one in-memory pass over visible rows once per second, no disk reads, no loader
  calls, no full list rebuild.
- Patch parent rows that are actively backed by running agent work, including `PLAN APPROVED` and `EPIC APPROVED`.
- Keep terminal rows stable and skipped.
- Keep render caching correct for all rows whose suffix can change per second.
- Add focused tests around the predicate, the visible row patching behavior, and cache invalidation.

## Implementation Approach

1. Introduce one shared helper for runtime tick eligibility near the existing time/runtime helpers, likely in
   `src/sase/ace/tui/models/agent_time.py`.

   The helper should return true only when:
   - the row has a `start_time`;
   - the row has no `stop_time`;
   - and either:
     - the row is directly active (`RUNNING` or `RETRYING`);
     - it is a `WAITING` row that has already begun actual running (`run_start_time` exists);
     - its status is an active parent status produced by a running follow-up (`PLAN APPROVED`, `EPIC APPROVED`,
       `LEGEND APPROVED`, `PLAN COMMITTED`);
     - or it has attached `followup_agents` with a runtime-ticking child, so future active parent statuses do not
       silently miss the tick path.

2. Replace `AgentList._runtime_suffix_ticks()` with a call to that shared helper.

   This keeps the existing per-second flow intact:
   - `_on_countdown_tick()`
   - `_patch_agent_runtime_rows()`
   - `AgentList.patch_active_runtime_rows(now)`
   - single-row `patch_agent_row(...)`

   No broader refresh path should be introduced.

3. Use the same shared helper in `src/sase/ace/tui/widgets/_agent_list_render_cache.py` when deciding whether
   `_runtime_signature()` should include `_quantize_now(now)`.

   This prevents stale cache hits for newly ticking statuses while preserving stable cache keys for terminal/non-ticking
   rows.

4. Add tests in the existing runtime/cache test files.

   Targeted tests:
   - `patch_active_runtime_rows` advances a `PLAN APPROVED` parent row with a running `.code` follow-up while preserving
     option count and marks.
   - `patch_active_runtime_rows` advances an `EPIC APPROVED` parent row with a running `.epic` follow-up.
   - terminal rows still skip patching.
   - the render cache key changes across seconds for a ticking parent status.

5. Verify with focused pytest first, then run repo checks after implementation.

   Commands:
   - `just install` if the workspace environment is not already prepared.
   - `pytest tests/ace/tui/widgets/test_agent_list_runtime.py tests/ace/tui/widgets/test_agent_render_cache.py`
   - `just check` before final response, per repo instructions.

## Performance Notes

The implementation should not add filesystem access, process checks, loader scans, or full `OptionList` rebuilds to the
one-second path. The helper is constant-time for normal rows and only inspects the already-attached `followup_agents`
list for parent rows. That list is built during the existing load/finalize pipeline, so the countdown tick remains an
in-memory cosmetic patch.
