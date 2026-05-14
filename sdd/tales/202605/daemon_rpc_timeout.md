---
create_time: 2026-05-14 14:44:15
status: done
prompt: sdd/prompts/202605/daemon_rpc_timeout.md
---
# Plan: Diagnose and Fix Daemon RPC Health Timeouts

## Context

`sase daemon doctor` reported a live daemon process and a valid host-local runtime layout, but the local Unix-socket
health RPC timed out. A later status check in this workspace shows the same daemon metadata is now stale: pid `3065686`
is no longer live, while `daemon.lock.json`, `daemon.lock`, and `sase-daemon.sock` remain under
`/home/bryan/.sase/run/sase-host`.

The local RPC client sends one framed JSON request and waits for a framed response. The Rust gateway accepts the socket
connection and dispatches health through `health_response`, which calls `DaemonState::diagnostic_details()`. That
currently computes full projection diagnostics synchronously, including source-export and scheduler summaries from the
projection SQLite database. If the DB mutex is held by indexing/rebuild work, or those health summary queries are slow,
the health call can exceed the Python doctor timeout and look like a broken RPC transport even though the socket
accepts.

## Goals

- Prove the timeout is caused by slow/blocking health diagnostics rather than malformed framing or a missing socket.
- Make the health RPC fast and bounded enough for doctor/startup checks.
- Preserve detailed diagnostics for doctor output without blocking the basic transport health path.
- Repair the stale local runtime state once source changes are understood.
- Add tests that reproduce a blocked projection health path and prevent regressions.

## Implementation Approach

1. Reproduce and instrument locally.
   - Clean up the stale runtime lock only after confirming the lock is not held.
   - Restart the daemon from the local build and time direct health RPCs.
   - Compare the Unix-socket health path with the mobile HTTP health/metrics path, and inspect whether projection WAL
     size or indexing activity correlates with slow health.

2. Narrow the source hot path.
   - Inspect `sase_gateway::local_transport::health_response`, `DaemonState::diagnostic_details`, and
     `ProjectionService::health_details`.
   - Identify synchronous DB calls on the async RPC handler thread, especially calls that lock the projection DB or scan
     source-export/scheduler tables.

3. Change the daemon health contract conservatively.
   - Keep `health` as a fast liveness/compatibility response based on cached service status and cheap in-memory state.
   - Avoid full projection DB summary reads in the default health response.
   - If detailed doctor diagnostics still need DB-backed summaries, expose them through a separate detailed path or make
     them optional behind the existing `include_capabilities`/request data flow if that matches the wire contract.

4. Update Python doctor/startup behavior if needed.
   - Ensure startup/doctor health checks use the fast health mode.
   - Keep richer doctor detail available where it can tolerate a longer timeout.
   - Improve the timeout/error message if the socket accepts but response generation times out.

5. Add regression coverage.
   - Add Rust tests around health response behavior with a blocked or unavailable projection DB summary path.
   - Add Python tests for doctor output/error wording if the client/doctor behavior changes.
   - Keep tests focused on daemon lifecycle and local transport.

6. Verify.
   - Run targeted Python tests in this repo.
   - Run targeted Rust tests in `../sase-core`.
   - Because this workspace may have stale dependencies, run `just install` before the final `just check` in this repo.
   - Run `just check` in every repo modified.

## Expected Outcome

`sase daemon doctor` should no longer report `socket_rpc_health: error` simply because projection diagnostics are slow.
A live daemon should answer basic health quickly, and doctor should distinguish true transport failure from degraded or
slow detailed diagnostics.
