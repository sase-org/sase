---
create_time: 2026-06-04 19:35:04
status: done
prompt: sdd/prompts/202606/concurrent_research_swarm_launch_race.md
---
# Plan: Fix Concurrent Research Swarm Launch Races

## Context

The recent failures clustered around the `2g` agent's approved implementation run:

- `2g` launched three `sase run -d` research swarms at `2026-06-04T23:22:35Z`, within about 20 ms of each other.
- The Bob/Obsidian swarm returned `partial multi-prompt launch failed` after a post-spawn chop-registry write failed:
  `agent_chops.tmp -> agent_chops.json`.
- Two initial SASE/Bob swarm launches reported `Agent started`, but their child fanout left seven failed artifacts:
  - `bob-cli` `20260604192243`: `research.cdx-8` collision
  - `sase` `20260604192244`: `research.cdx-8` collision
  - `bob-cli` `20260604192249`: `research.cld-8` collision
  - `sase` `20260604192321`: `research.cld-8` collision
  - `bob-cli` `20260604192323`: `research.final-8` collision
  - `sase` `20260604192350`: `research.final-8` collision
  - `sase` `20260604192401`: `research.image-8` collision
- `2g` then retried sequentially, producing the intended live swarms as `research-8`, `research-9`, and `research-10`.

The user's race-condition assumption is correct, but there are two related races rather than one isolated bug.

## Root Cause

1. `src/sase/axe/chop_agents.py` writes chop launch records via one fixed temp path, `agent_chops.tmp`, then replaces
   `agent_chops.json`. Concurrent `sase run -d` processes launched from the same Telegram chop can both use that temp
   path. One process can move or delete the temp file before another replaces it, producing the observed
   `FileNotFoundError`.

2. `src/sase/agent/multi_prompt_references.py::PlannedNameAllocator` allocates indexed templates like `research.cdx-@`
   from a local reservation set. It does not durably reserve `research.cdx-8` before the child process starts.
   Concurrent parent launches can therefore plan the same concrete indexed names and rewrite `%wait` / `#fork`
   references to the same suffix. The child runner eventually claims names under the global registry lock, so the losing
   children fail with `NameCollisionError` after the parent launch has already partially faned out.

3. `src/sase/agent/launch_spawn.py` records chop metadata after the child process is spawned. If that bookkeeping write
   raises, the parent launch reports failure even though at least one child may already be running. The generic
   `sase run -d` path does not roll back partial multi-prompt children, so abandoned children can keep running or fail
   later as confusing "recent failures."

## Plan

1. Make chop agent registry writes atomic under concurrency.
   - In `src/sase/axe/chop_agents.py`, protect the whole read/prune/update/write transaction with a per-lumberjack file
     lock.
   - Replace the fixed `agent_chops.tmp` path with a unique temp file in the same directory, followed by `os.replace`.
   - Keep pruning and appending inside the same lock so concurrent launches cannot lose each other's records.
   - Make post-spawn chop recording non-fatal in `launch_spawn.py`: log/telemetry the failure, but do not turn an
     already-spawned child into a failed launch solely because bookkeeping failed.

2. Add durable pre-reservation for parent-planned indexed agent names.
   - Extend the indexed-name planning path so a parent can reserve a concrete name against the future child artifact
     directory before returning `SASE_AGENT_PLANNED_NAME`.
   - For multi-prompt launches, allocate or expose each slot's timestamp early enough to know its future artifact
     directory, then reserve indexed names such as `research.cdx-8` under the global agent-name registry lock.
   - Preserve the current per-batch behavior where `research.final-@`, `%wait:research.cdx-@`, and
     `#fork:research.final-@` all resolve to the same concrete suffix within one swarm.
   - Ensure the child runner's later claim is idempotent for the same artifact owner and still rejects a different
     owner.
   - Apply the same reservation contract to single-prompt indexed-name planning where the timestamp is already known.

3. Roll back partial high-level launches.
   - Add a shared helper that consumes `_MultiPromptPartialLaunchError.results`, sends SIGTERM to each spawned child
     process group, and releases any known workspace claims.
   - Wire the helper into the CLI `sase run -d` path and TUI multi-prompt launch path. Keep the existing exception
     payload for callers, such as bead workflows, that already perform their own rollback.
   - Emit a clear error message that distinguishes "launch bookkeeping failed after spawning children" from ordinary
     prompt validation failures.

4. Add regression coverage.
   - Add a threaded chop-registry test proving concurrent `_record_chop_agent_launch` calls produce a valid
     `agent_chops.json` containing both records and no temp-file errors.
   - Add a concurrent `launch_multi_prompt_agents` test with two simultaneous `research.cdx-@` / `research.final-@`
     style batches. Assert the planned names are distinct across batches and `%wait` references stay internally
     consistent within each batch.
   - Add a post-spawn chop-recording failure test proving `spawn_agent_subprocess` still returns the launched child
     result when only chop bookkeeping fails.
   - Add a CLI or high-level launcher partial-failure test proving leaked children are terminated on generic
     `sase run -d` partial failures.

5. Verify.
   - Run focused tests for agent-name planning, multi-prompt launch planning, chop-agent registry behavior, and daemon
     CLI launch behavior.
   - Run `just test` or the repository's current focused check command if the full suite is too costly, then run the
     broader check command required by the project instructions before finishing source changes.

## Expected Result

Parallel `#research_swarm` launches should either start cleanly with distinct concrete indexed names, or fail before
spawning children. A failure in ancillary chop bookkeeping should no longer create a misleading partial launch, and any
true partial launch should clean up its already-spawned children.
