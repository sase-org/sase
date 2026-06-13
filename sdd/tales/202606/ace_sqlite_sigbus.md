---
create_time: 2026-06-13 09:34:40
status: wip
---
# Plan: Fix `sase ace` Artifact-Index SIGBUS Crash

## Root-Cause Summary

The macOS crash report shows `sase ace` died with `EXC_BAD_ACCESS (SIGBUS)` and
`FS pagein error: cluster_pagein past EOF`. The crashed thread is inside `sase_core_rs.abi3.so`; another live thread is
inside Python's `_sqlite3` extension at the same time. The matching `sase_core_rs` binary UUID is
`8F37FA31-F8D9-346C-8796-44ECB3DF6BE6`, and the Rust extension is statically linked with bundled SQLite via `rusqlite`.

The shared file involved is the ACE agent artifact index, `~/.sase/agent_artifact_index.sqlite`. The Rust index code
opens it in WAL mode, which uses a memory-mapped `-shm` sidecar. During ACE startup, one background worker can query the
index through Rust while another dismissed-agent projection worker reads or writes index metadata through Python
`sqlite3`. That mixes two SQLite implementations in one process against the same WAL database. With WAL shared-memory
mappings, this can produce exactly the crash shape in the report: a native page-in fault rather than a catchable
Python/Rust error.

## Product Direction

Keep the fast artifact-index path for the Agents tab, but ensure all normal ACE artifact-index access goes through the
Rust binding and therefore one SQLite implementation per process. Do not remove the persistent index or move heavy scans
back onto the TUI event loop.

## Implementation Steps

1. Add Rust-core helpers in `../sase-core/sase-core_11` for lightweight artifact-index operations that Python currently
   performs with `sqlite3`:
   - read one `meta` value by key;
   - write one `meta` value by key;
   - return a small status payload with schema version, `agent_artifacts` row count, and `dismissed_agents` row count.

2. Expose those helpers through `crates/sase_core_py/src/lib.rs` as new PyO3 functions, using the same `open_index` path
   as existing query/rebuild/upsert calls and releasing the GIL for disk work.

3. Update the Python facade in this repo to wrap the new Rust functions.

4. Replace direct Python `sqlite3` access in artifact-index lifecycle/status code:
   - `src/sase/core/agent_artifact_index_lifecycle.py` should use Rust metadata helpers for dismissed-projection
     fast-path reads and metadata writes.
   - `src/sase/agents/cli_index.py` should use the Rust status helper for schema and row counts.
   - Keep corruption handling behavior, but classify Rust facade errors instead of relying on `sqlite3.Error`.

5. Add regression coverage:
   - Rust tests for metadata read/write and status counts on a temp index.
   - Python tests proving dismissed-projection sync reads/writes metadata through the facade helpers and that CLI status
     consumes the Rust status payload.
   - Keep existing corruption/quarantine tests passing, adjusting mocks to the new helper boundaries.

6. Verify:
   - Run focused Rust tests in `../sase-core/sase-core_11` for `agent_scan::index` and the PyO3 crate if available.
   - Run focused Python tests around `agent_artifact_index_lifecycle`, `agents_index_cli`, and `core_agent_scan_facade`.
   - Because this repo requires it after file changes, run `just install` then `just check` in the `sase_11` workspace,
     using the established `SASE_CORE_DIR` override only if the space-containing workspace path triggers the known
     Justfile quoting issue.

## Risk Notes

- This keeps the WAL-backed index and existing TUI fast path intact, which aligns with the TUI performance guidance: no
  synchronous event-loop work and no fallback to full source scans except on index failure.
- The fix addresses the native crash mechanism directly by eliminating normal same-process mixed SQLite access to the
  artifact index.
- Existing old `sase` processes could still have the old behavior until restarted, but updated ACE sessions should use
  the single Rust SQLite path.
