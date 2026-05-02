---
create_time: 2026-04-27 12:26:21
status: done
prompt: sdd/prompts/202604/epic_agent_timestamp_collision.md
---

# Plan: Fix Epic Phase Agent Timestamp Collisions

## Problem

`sase bead work sase-w` was expected to launch 7 phase agents plus one land agent, but the Agents view only shows
`sase-w.1`, `sase-w.2`, `sase-w.3`, and `sase-w.land`.

The bead graph itself is correct:

- `sase bead show sase-w` lists all seven phase children.
- Each phase is pre-claimed as `in_progress` with the matching assignee.
- Rebuilding the epic work plan from the current bead DB renders 8 multi-prompt segments: `sase-w.1` through `sase-w.7`,
  then `sase-w.land`.

The launch state reveals the failure:

- `~/.sase/projects/sase/sase.gp` contains 8 workspace claims.
- The claims for `sase-w.4`, `sase-w.5`, `sase-w.6`, `sase-w.7`, and `sase-w.land` all share the same
  workflow/timestamp: `ace(run)-260427_121843` / `20260427121843`.
- The artifact directory and output log path are timestamp-derived, so same-second launches overwrite or merge metadata.
  The TUI loads one agent for that artifact key, which is why only the final `sase-w.land` survives visibly.

## Root Cause

`launch_multi_prompt_agents()` calls `generate_timestamp()` for each spawned child. `generate_timestamp()` has
one-second resolution (`YYmmdd_HHMMSS`). Deferred `%wait` children write `agent_meta.json` quickly, so the multi-prompt
launcher can spawn several children within the same second. Those children then share:

- `workflow_name = ace(run)-<timestamp>`
- artifact directory `~/.sase/projects/<project>/artifacts/ace-run/<timestamp>`
- output path from `spawn_agent_subprocess()`
- `RUNNING` claim workflow/artifact timestamp fields

The existing `time.sleep(1)` only applies between multi-model sub-prompts within one segment. It does not protect
ordinary multi-prompt segment launches.

## Implementation

1. Add a small timestamp allocator inside `src/sase/agent/multi_prompt_launcher.py` that guarantees each child launched
   by one multi-prompt batch receives a timestamp distinct from the previous child.
   - Keep using the existing timestamp format to avoid changing artifact path conventions and downstream parsers.
   - If `generate_timestamp()` returns the same value as the previous child, sleep briefly and retry until it advances.
   - Use the allocator for every sub-prompt in the batch, including ordinary segments and multi-model variants.

2. Preserve existing behavior around deferred workspaces and naming waits.
   - `%wait` children can still claim workspace `0`.
   - Naming wait still happens between segments so bare `%wait` remains supported.
   - Multi-model variants remain independent child launches, but now also receive unique timestamps.

3. Add focused tests in `tests/test_multi_prompt_launcher.py`.
   - Cover duplicate timestamps from `generate_timestamp()` and assert spawned children receive unique, ordered
     timestamps.
   - Cover the regression shape: multiple `%wait` segments can be launched in one batch without duplicate workflow
     names/artifact timestamps.
   - Avoid real one-second sleeps in tests by monkeypatching the sleep function and timestamp side effects.

4. Verification.
   - Run the focused multi-prompt launcher tests.
   - Run existing bead work tests to make sure rendered epic prompts and CLI handoff remain intact.
   - Run `just check` after code changes, per repo instructions.

## Out of Scope

This plan fixes the launch identity collision. It does not try to repair already-collided live agents or mutate `sase-w`
bead state. After the code fix, a separate operational recovery step can decide whether to manually launch missing
`sase-w.4` through `sase-w.7` or reset/re-run the epic.
