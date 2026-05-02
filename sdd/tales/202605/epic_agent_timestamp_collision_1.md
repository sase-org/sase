---
create_time: 2026-05-01 16:33:55
status: done
prompt: sdd/prompts/202605/epic_agent_timestamp_collision_1.md
---
# Diagnose and Fix Epic Agent Timestamp Collision

## Problem

`sase bead work sase-1u` rendered a correct epic work multi-prompt that included `sase-1u.8`, and the CLI pre-claimed
the bead as `status=in_progress, assignee=sase-1u.8`. The live ACE state later showed no `.8` agent while `sase-1u.land`
waited on `.8`.

The artifact directory for the expected `.8` slot, `~/.sase/projects/sase/artifacts/ace-run/20260501162034`, contains
mixed state:

- `waiting.json` says the slot is waiting for `sase-1u.6` and `sase-1u.7`, which matches the `.8` phase.
- `agent_meta.json`, `raw_xprompt.md`, and `live_reply.md` belong to a different prompt named `ub`.

That means the `.8` launch and an unrelated single-agent launch reused the same visible timestamp second. The
later/competing launch overwrote enough artifact metadata that ACE no longer had a live `sase-1u.8` identity to display
or satisfy waits.

`sase-1u.7` did start; it was correctly in `WAITING` because it depends on `sase-1u.3`. The broken case is `.8`, caused
by artifact timestamp collision.

## Root Cause

Agent artifact identity is based on `YYmmdd_HHMMSS` timestamps. The multi-prompt path uses
`LaunchTimestampBatchAllocator`, which makes timestamps unique only inside one fanout batch. The single-agent path still
calls `generate_timestamp()` directly, so a normal launch can receive the same timestamp as a slot in a concurrent
multi-prompt batch. Because `create_artifacts_directory(..., timestamp=...)` uses `mkdir(..., exist_ok=True)`, the
collision silently merges/overwrites files instead of failing.

This is a cross-launch allocation bug, not an epic DAG/rendering bug.

## Fix Plan

1. Add a process-safe launch timestamp reservation API in `src/sase/core/agent_launch_facade.py`.
   - Keep `allocate_launch_timestamp_batch()` as the pure deterministic Rust-backed helper for tests and non-reserving
     uses.
   - Add `reserve_launch_timestamp_batch()` that:
     - takes an exclusive `fcntl.flock` under `~/.sase/agent_launch_timestamps/`,
     - reads the last reserved timestamp from a small state file,
     - allocates after the maximum of wall-clock base, caller `after_timestamp`, and persisted state,
     - writes the final reserved timestamp before releasing the lock.

2. Route every production agent launch timestamp source through the reservation API.
   - `LaunchTimestampBatchAllocator.allocate()` should reserve batches globally, preserving its intra-batch behavior.
   - The single-agent path in `launch_agent_from_cwd()` should reserve one timestamp when the caller did not pass a
     preallocated timestamp.
   - CLI repeat and TUI repeat fanout should reserve their timestamp batches instead of using the pure allocator
     directly.

3. Add focused tests.
   - Preserve existing pure Rust allocation expectations for `allocate_launch_timestamp_batch()`.
   - Add coverage for global reservation with a temp home and fixed wall-clock base: two independent reservations in the
     same second must return disjoint sequential timestamps.
   - Update `LaunchTimestampBatchAllocator` coverage to run against an isolated temp home, proving it advances through
     the global reservation state without depending on the developer’s real `~/.sase`.

4. Validate.
   - Run the focused timestamp/launch tests first.
   - Run `just check` after source edits, as required by this repo.

## Operational Follow-Up

This code fix prevents future collisions. The already-broken live `.8` slot will still need operational
cleanup/relaunch: the old `sase-1u.8` pre-claim exists without a live matching agent, and `sase-1u.land` is waiting on
that missing name. After the fix is verified, either kill/dismiss the stale land/waiting agents and rerun
`sase bead work sase-1u --yes`, or explicitly relaunch the missing `.8` phase with `%name:sase-1u.8` and the same waits.
