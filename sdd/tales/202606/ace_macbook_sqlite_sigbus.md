---
create_time: 2026-06-13 09:08:02
status: done
prompt: sdd/prompts/202606/ace_macbook_sqlite_sigbus.md
---
# Plan: Diagnose and Fix `sase ace` macOS SIGBUS Crash

## Context

`~/tmp/ace_macbook_crash.txt` shows `sase ace` crashed on macOS with:

- `EXC_BAD_ACCESS (SIGBUS)`, `FS pagein error: 22 Invalid argument`
- APFS triage: `cluster_pagein past EOF`
- crashing thread inside `sase_core_rs.abi3.so`
- a 32 KB writable `mapped file` VM region
- another thread concurrently inside SQLite WAL/shared-memory setup through Python's `_sqlite3`

This is not a Python exception. The native crash shape is consistent with SQLite's `-shm` WAL shared-memory mapping
being truncated, unlinked, or replaced while another SQLite connection still has it mapped. On macOS/APFS that can
surface as SIGBUS instead of a recoverable SQLite error.

The current ACE startup path schedules these workers concurrently after first paint:

1. `_run_agents_async_refresh`, which queries the Rust-backed `agent_artifact_index.sqlite` via
   `query_agent_artifact_index`.
2. `_run_dismissed_index_startup_sync`, which opens the same index through both Python sqlite and Rust facade calls, and
   on corruption can quarantine/rebuild the index and delete `-wal`/`-shm` sidecars.

That concurrent startup shape matches the crash timing and thread mix in the report.

## Working Root Cause

The likely root cause is a race in artifact-index maintenance:

- The initial ACE agents refresh opens/query-repairs the persistent artifact index through `sase_core_rs`.
- The dismissed-projection startup sync opens the same SQLite index, may write the dismissed table/metadata, and may
  quarantine/rebuild the index if it sees corruption.
- The corruption-heal path currently renames/removes the main DB and unlinks SQLite sidecars (`-wal`, `-shm`) without
  coordinating with active readers/writers.
- If another connection has the `-shm` file mapped, deleting/truncating/replacing it can SIGBUS on macOS.

This explains why the crash is native, intermittent, launch-time, and machine-dependent.

## Implementation Plan

1. Confirm the exact index concurrency surface.
   - Audit all startup paths touching `agent_artifact_index.sqlite`.
   - Verify whether a broad agents refresh, artifact-delta refresh, dismissed-projection sync, and corruption heal can
     overlap in a single ACE process.
   - Keep the core/backend boundary in mind: SQLite index semantics belong in the Rust core, while ACE startup
     scheduling belongs in Python/TUI.

2. Introduce a process-local artifact-index operation lock in Python.
   - Add a small shared lock module around artifact-index calls in `src/sase/core`.
   - Use it for Python facade calls that touch the artifact index: `rebuild_agent_artifact_index`,
     `upsert_agent_artifact_index_row`, `delete_agent_artifact_index_row`,
     `replace_agent_artifact_index_dismissed_agents`, `query_agent_artifact_index`, and Python-side metadata
     reads/writes in `agent_artifact_index_lifecycle.py`.
   - Use a reentrant lock so lifecycle helpers can call facade helpers without deadlocking.
   - This prevents the TUI's thread pool from running Python sqlite and Rust sqlite operations against the same WAL
     index concurrently within one `sase ace` process.

3. Serialize startup dismissed-index sync behind the initial agents refresh.
   - Keep the sync off the event loop, but stop launching it concurrently with the initial agents load.
   - Schedule it as an `on_complete` callback after the startup agents refresh, or otherwise route it through existing
     agents refresh coalescing so first paint remains fast and index maintenance cannot race the first index query.
   - Preserve the existing behavior: if the dismissed projection changed, schedule a follow-up agents refresh with
     source `dismissed_index_sync`; if a heal occurred, notify the user.

4. Make corruption healing less dangerous.
   - Avoid deleting live SQLite sidecars while another connection may exist in-process.
   - Prefer closing the active connection before quarantine/rebuild and perform the whole heal under the shared lock.
   - Review the Rust `replace_unusable_index_file` path as a separate backend-side hazard. If needed, update
     `../sase-core` so corrupt-index replacement also happens under safer conditions and does not blindly remove WAL
     sidecars from a live shared DB.

5. Add focused regression coverage.
   - Add Python tests that assert startup schedules dismissed-index sync only after the startup agents refresh
     completes, not as a parallel startup worker.
   - Add unit tests for the shared lock by forcing nested lifecycle/facade calls and verifying no deadlock.
   - Add a concurrency regression test where one thread holds the artifact-index operation lock while another attempts a
     query/sync, proving calls serialize.
   - Update existing tests that currently expect all post-mount startup loads to be launched independently.

6. Validate.
   - Run targeted tests first:
     `pytest tests/ace/tui/test_dismissed_index_startup_sync.py tests/test_agent_artifact_index_lifecycle.py` plus
     relevant agent-loader/index tests.
   - If Rust core changes are needed, run the relevant `cargo test` package tests in `../sase-core`.
   - Because this repo changed files, run `just install` if needed and finish with `just check` per project
     instructions.

## Expected Outcome

The fix should eliminate the in-process race that can invalidate SQLite WAL shared-memory mappings during ACE startup.
The user-visible behavior remains the same: first paint stays fast, dismissed-index maintenance still runs in the
background, and any projection change still triggers a follow-up agents refresh.
