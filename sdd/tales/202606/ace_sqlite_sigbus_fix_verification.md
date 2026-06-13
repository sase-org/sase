---
create_time: 2026-06-13 09:45:53
status: done
prompt: sdd/prompts/202606/ace_sqlite_sigbus_fix_verification.md
---
# Plan: Verify and Complete the `sase ace` SQLite SIGBUS Fix

## Purpose

The prior change set (commit `265f3e90b` here + `1b99aa5` in `sase-core`) tried to fix the macOS
`EXC_BAD_ACCESS (SIGBUS)` crash in `sase ace`. This plan **verifies whether that fix actually prevents the crash**, and
concludes it does **not** fully prevent it. It then specifies the remaining fix.

## What the crash actually is (forensics)

From `~/tmp/ace_macbook_crash.txt`:

- Exception: `EXC_BAD_ACCESS (SIGBUS)`, `FS pagein error: 22`, kernel triage `cluster_pagein past EOF`. This is the
  signature of a **memory-mapped file truncated/replaced out from under a live mapping**.
- Faulting region: a **32 KB `mapped file`** VM region — the size of a SQLite WAL `-shm` wal-index region.
- **Thread 3 (crashed)**: deep inside `sase_core_rs.abi3.so`, in `_platform_memmove` against that mapped region. The
  SQLite frames are _inside_ the Rust extension → the Rust core uses its **own statically linked SQLite**.
- **Thread 5 (concurrent)**: Python `_sqlite3` → **system `libsqlite3.3.53.1.dylib`** → `unixShmMap` → `seekAndWriteFd`,
  i.e. actively (re)sizing the WAL `-shm` on a _fresh_ connection (`sqlite3InitOne`/`sqlite3ReadSchema`).

### Root cause

`sase ace` runs **two distinct SQLite library instances in one process**:

1. The Rust core's statically linked SQLite (used by every `agent_scan_facade` call into `sase_core_rs`).
2. Python's system `libsqlite3` (used by `sqlite3.connect(...)` in `agent_artifact_index_lifecycle.py`).

Both open the same WAL database `~/.sase/agent_artifact_index.sqlite`. SQLite coordinates concurrent WAL access two
ways: POSIX advisory locks on the files, and a **private, per-library in-process list of open inodes / shared-memory
nodes**. Neither mechanism works between two libraries in one process:

- POSIX advisory locks are **process-owned** — they never conflict with the _same_ process, so the two libraries are
  invisible to each other's locks.
- The inode/`-shm` bookkeeping is `static` inside each SQLite build, so each library believes it is the only connection.

Result: one library truncates / rebuilds / unlinks the `-shm` (on open growth, on WAL recovery, or on last-connection
close) while the other still has it `mmap`'d → access past the new EOF → **SIGBUS**. This explains every property of the
crash: native (not a Python exception), intermittent, launch-time (peak concurrency), and machine-dependent (APFS
surfaces it as SIGBUS).

Note: cross-process access (the **AXE daemon** at `sase.axe.process`, and `sase agents index` CLI runs) is _not_ the
cause — across processes POSIX locks **do** conflict, so normal WAL sharing is safe. The hazard is specifically **two
libraries inside the one `sase ace` process**.

## Does the current fix prevent the crash? No — one concrete gap remains.

The current fix added a process-local reentrant lock (`agent_artifact_index_operation_lock`) and wrapped:

- every Rust facade call in `agent_scan_facade.py` (`query/upsert/delete/replace/rebuild`), and
- the Python sqlite metadata + mutation paths in `agent_artifact_index_lifecycle.py`.

If the lock truly bounded _every_ connection's full lifetime, serialization would be sufficient (only one connection —
from either library — could exist at a time, so nothing could be mapped while another truncates). It does not, because
of how Python closes connections:

> `with sqlite3.connect(...) as conn:` **commits but does not close** the connection. The connection is closed later,
> when `conn` is garbage-collected at function return.

In both `_read_projection_metadata` (lines ~482-503) and `_write_projection_metadata` (lines ~506-531), that GC-close
happens **after** the `with agent_artifact_index_operation_lock()` block has already exited. On a WAL database the
last-connection close **truncates/unlinks `-shm`**. So:

1. Thread A finishes `_read/_write_projection_metadata`, releases the lock. Its Python connection is still open (not yet
   GC'd).
2. Thread B (e.g. the agents async refresh, `agent_loader.py:164` → `query_agent_artifact_index`) acquires the now-free
   lock, opens the Rust/bundled connection, `mmap`s `-shm`, begins `memmove`.
3. Thread A returns; `conn` is GC-closed → system `libsqlite3` (believing it is the last connection) truncates/unlinks
   `-shm`.
4. Thread B faults reading past EOF → **SIGBUS** — exactly the thread-3 / thread-5 shape in the report.

The startup-ordering change narrows the launch-time window but does not remove this race: marker-mutation upserts,
follow-up refreshes, and periodic refreshes still run concurrently with dismissed-projection metadata access during a
session. **Conclusion: the fix reduces frequency but does not eliminate the crash.**

The other parts of the prior fix are sound and should stay: the lock itself, the startup-ordering change
(defense-in-depth), and the rename-based quarantine of the corrupt DB + sidecars (renaming preserves live mappings on
their original inode, unlike `remove_file`).

## Remediation

### Required fix (closes the proven gap)

Close every Python sqlite connection to the artifact index **inside** the lock, so the system-`libsqlite3` connection's
full lifetime (open → work → close, including the `-shm`-truncating teardown) is bounded by the critical section.
Concretely, in `agent_artifact_index_lifecycle.py`:

- Wrap the connections in `contextlib.closing(sqlite3.connect(...))` _nested within_ the existing
  `with agent_artifact_index_operation_lock()` block in `_read_projection_metadata` and `_write_projection_metadata`, so
  `conn.close()` runs before the lock is released. Fetch rows inside the lock; parse/return after.

With this, in the `sase ace` process at most one artifact-index connection (Rust or Python) is ever open at an instant,
so no library can truncate `-shm` while another has it mapped. Combined with the existing lock on all Rust facade calls,
the in-process two-library race is fully closed.

### Recommended durable fix (removes the anti-pattern at its root)

Eliminate the _second_ SQLite library on this DB by moving the `meta`-table read/write into the Rust core (per
`memory/short/rust_core_backend_boundary.md`: "SQLite index semantics belong in the Rust core"):

- Add Rust facade functions (e.g. `read_agent_artifact_index_meta` / `write_agent_artifact_index_meta`) in
  `../sase-core` `crates/sase_core/src/agent_scan/index.rs`, exposed through `sase_core_rs`.
- Replace the Python `sqlite3.connect` metadata helpers with calls through the locked facade.

This makes the artifact index single-library inside every process and makes the required fix above moot. It is larger
(Rust + binding + rebuild + tests) but is the boundary-correct end state.

### Optional consistency hardening (low risk)

`src/sase/agents/cli_index.py` (`_read_index_schema_version`, `_count_index_rows`) mixes `query_agent_artifact_index`
(Rust SQLite) with raw `sqlite3.connect` (system SQLite) on the same index. This runs in the single-threaded
`sase agents index` CLI process, so it cannot hit the concurrent race in practice, but it is the same anti-pattern.
Align it with whichever approach is chosen above.

## Recommended approach

Ship the **required fix** (close-inside-lock) now — it is small, low-risk, and provably closes the crash — and track the
**Rust meta migration** as the durable follow-up.

- Question for the reviewer: do both now, or just the required fix now and the Rust migration as a separate change?
  - ANSWER FROM THE USER: Do both now.

## Validation

1. Add a regression test proving the gap is closed: spy/patch so a Python metadata connection's `close` cannot occur
   while the lock is free — i.e. assert the connection is closed _before_ `_read/_write_projection_metadata` releases
   the lock (e.g. instrument the lock and the connection and assert ordering), preventing reintroduction of the
   GC-close-outside-lock pattern.
2. Keep/extend existing lock-serialization and startup-ordering tests.
3. If the Rust meta migration is included: add `cargo test` coverage in `../sase-core` for the new meta facade functions
   and rebuild/reinstall the extension into the workspace venv.
4. Run `just install` then `just check` in `sase_11` (and `cargo fmt --check` + targeted `cargo test` in `sase-core_11`
   if Rust changed).

## Expected outcome

After the required fix, every artifact-index connection in the `sase ace` process — from either SQLite library — opens
and closes entirely under the shared lock, so no `-shm` mapping can be live while another connection truncates it. The
launch-time SIGBUS is eliminated, with unchanged user-visible behavior (fast first paint, background dismissed-index
maintenance, follow-up refresh on projection change).
