---
create_time: 2026-05-16 12:10:20
status: done
prompt: sdd/prompts/202605/agents_tab_empty_after_fast_load.md
---
# Diagnose And Fix Empty Agents Tab After Fast Loader

## Context

The `sase-3r` fast-loader work moved ordinary Agents-tab refreshes to the persistent artifact-index inbox query. Local
diagnostics show the index and disk loader are not fundamentally empty:

- `sase agents status` sees running agents.
- `load_agents_from_disk_with_state(..., full_history=False)` returns thousands of loader rows and current RUNNING rows.
- A mounted Textual harness can render a small filtered visible set.
- `~/.sase/perf/tui_trace.jsonl` also shows a problematic pattern: zero-row async apply/finalize events can occur on the
  Agents tab after non-empty index loads, temporarily or persistently replacing the visible list with an empty one.

The likely root cause is not the Rust query itself. It is stale or low-fidelity async load results being allowed to
apply after a newer good result, plus the Phase 3 missing-index/empty-snapshot behavior making a stale result capable of
blanking the panel. The current async path serializes normal scheduled refreshes, but `_load_agents_async` has no apply
generation guard, and startup/direct worker paths can still race or apply an older empty result to current UI state.

## Goals

- Keep the fast artifact-index path intact.
- Prevent stale/empty async agent loads from overwriting a newer populated Agents-tab projection.
- Preserve legitimate empty states when there truly are no agents and no cached rows.
- Add tests that reproduce the empty-overwrite class without relying on the user's real `~/.sase`.

## Plan

1. Add a focused regression test around async/apply ordering.
   - Build a fake app/mixin fixture or use the existing replay harness to model a non-empty Tier 1 result followed by an
     older empty complete/missing-index result.
   - Assert the final Agents-tab projection remains non-empty when a newer generation has already applied.
   - Add a companion assertion that an initial empty load can still render empty when there is no prior populated state.

2. Add load-generation tracking to the Agents async loader.
   - Initialize monotonic agent-load request/apply counters in `_state_init.py`.
   - When `_run_agents_async_refresh` starts a load, allocate a generation and pass it through `_load_agents_async`.
   - Before `_apply_loaded_agents_prepared`, drop the result if its generation is older than the latest applied or
     latest scheduled generation.
   - Keep callbacks and pending-refresh behavior intact; discarded stale loads should still allow the refresh runner to
     clear `_agents_loading` and process any pending follow-up.

3. Harden empty incomplete loads at the apply boundary.
   - For missing-index or otherwise incomplete Tier 1 results with zero loaded rows, preserve the current in-memory
     `_agents_with_children`/visible projection when a populated projection already exists.
   - Do not mask explicit full-history repair/revive/archive flows; those should still be allowed to replace the list
     when they are the current generation.

4. Improve trace/debug fields enough to verify the fix.
   - Add generation and stale-discard trace events for agent async refreshes.
   - Keep existing `agents.load_from_disk` fields unchanged so `sase-3r` perf comparisons remain comparable.

5. Verify.
   - Run the targeted agent-loader/Agents-tab tests first.
   - Run the Textual harness smoke that starts on the Agents tab and confirms the panel has rows after startup.
   - Because this repo will have source changes, run `just install` if needed and then `just check` before final
     response.

## Non-Goals

- Do not reintroduce ordinary full-history source scans for normal Agents-tab refreshes.
- Do not change Rust index query semantics unless the regression test proves the query is returning wrong records.
- Do not modify memory files.
