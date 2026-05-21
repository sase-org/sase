---
create_time: 2026-05-21 14:11:50
status: done
prompt: sdd/prompts/202605/agent_index_gc_corruption.md
---
# Plan: Repair `sase agents index gc` on corrupt artifact index

## Problem

`sase agents index gc` is intended to repair the persistent agent artifact index, but it fails when the SQLite index
file itself is corrupt. The live default file at `~/.sase/agent_artifact_index.sqlite` cannot be opened with Python
SQLite in read-only mode; `PRAGMA integrity_check` raises `DatabaseError: database disk image is malformed`.

The command flow explains the traceback:

- Python `gc` first calls `verify_agent_artifact_index`.
- `verify_agent_artifact_index` catches the corrupt index query failure and returns a degraded report.
- `gc` then calls Rust `rebuild_agent_artifact_index`.
- Rust `rebuild_agent_artifact_index` calls `open_index`, which tries to run DDL/migrations on the existing malformed
  database and returns the raw SQLite error.
- The repair command never reaches the rebuild that would replace the stale cache from source artifact files.

The artifact tree under `~/.sase/projects` is the source of truth, so a corrupt artifact-index SQLite file should not be
fatal for the explicit rebuild/gc repair path.

## Approach

1. Update the Rust core backend in `../sase-core/crates/sase_core/src/agent_scan/index.rs`.
   - Keep normal query/upsert/delete behavior strict: corrupt indexes should still fail so callers can fall back or
     report repair needed.
   - Change the full rebuild path to tolerate a corrupt existing index by replacing the unusable cache file and
     rebuilding from source artifacts.
   - Remove any stale SQLite WAL/SHM sidecars when replacing the main index so SQLite does not reattach broken state.
   - Keep the change scoped to rebuild semantics because rebuild is the operation that can safely reconstruct the cache.

2. Add Rust tests in `../sase-core/crates/sase_core/src/agent_scan/index.rs` or the parity test suite.
   - Create an invalid/non-SQLite file at the target index path.
   - Assert `rebuild_agent_artifact_index` succeeds and produces a valid schema/version.
   - Assert normal `query_agent_artifact_index` against an invalid existing file still returns an error rather than
     silently discarding the cache.

3. Add Python CLI coverage in `tests/test_agents_index_cli.py`.
   - Pin that `gc` proceeds to `rebuild_agent_artifact_index` after a failed preflight instead of treating the failed
     verify as terminal.
   - If Python-side messaging changes are needed, keep it minimal and do not duplicate Rust repair logic in Python.

4. Verify.
   - Run the targeted Rust tests for `sase_core`.
   - Reinstall/build the local binding if needed for Python tests.
   - Run targeted Python tests for the index CLI and facade.
   - Because this repo will have file changes, run `just install` if needed and then `just check` before finishing.

## Expected Outcome

After the fix, `sase agents index gc` should recover from a malformed `~/.sase/agent_artifact_index.sqlite` by
rebuilding the index from source artifacts. The root cause remains visible as a corrupt cache file, but the user-facing
repair command no longer fails on the same corruption it is supposed to repair.
