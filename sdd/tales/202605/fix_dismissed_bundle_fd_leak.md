---
create_time: 2026-05-05 09:02:23
status: done
prompt: sdd/prompts/202605/fix_dismissed_bundle_fd_leak.md
---
# Plan: Fix dismissed bundle SQLite file descriptor leak

## Problem

`just test` intermittently fails under pytest-xdist with `OSError: [Errno 24] Too many open files` in
`tests/test_dismissed_agents.py`, especially around `test_bundle_no_limit` and the removal tests that follow it.

The failure is not caused by the tmpdir path itself. A focused repro in this workspace showed the process moving from 6
open file descriptors to 1207 after 600 calls to `save_dismissed_bundle()`.

## Root Cause Hypothesis

`src/sase/ace/dismissed_bundle_index.py` opens SQLite connections through `_connect()` and then uses them as:

```python
with _connect(root) as conn:
    ...
```

Python's `sqlite3.Connection` context manager only manages transaction commit/rollback. It does not close the connection
when the `with` block exits. Every index upsert/query/rebuild path that uses this pattern can therefore leak database
descriptors. `test_bundle_no_limit` saves 600 bundles, and each save upserts a dismissed bundle summary, so it can leak
hundreds of descriptors in one test worker. With a normal per-process fd limit, later filesystem operations then fail
with `EMFILE`.

## Implementation Plan

1. Add an explicit connection-closing context manager in `dismissed_bundle_index.py`, likely using `contextlib.closing`
   wrapped around `_connect(...)`, so transaction semantics are preserved and the underlying SQLite connection is closed
   after each operation.

2. Replace every `with _connect(...) as conn:` in `dismissed_bundle_index.py` with the new closing helper. Keep the
   existing SQL, schema, WAL settings, and error handling intact.

3. Add a focused regression test that repeatedly saves dismissed bundles and asserts the fd count does not grow
   materially on Linux via `/proc/self/fd`. Skip or use a portable fallback on platforms without `/proc/self/fd`.

4. Run the targeted dismissed-agent tests first, including a low-file-limit run if feasible, then run `just check`
   because this repo requires it after changes.

## Expected Result

Saving and indexing hundreds of dismissed bundles should leave SQLite descriptors closed promptly. The dismissed bundle
tests should stop exhausting file descriptors in xdist workers, and the full check suite should pass without `EMFILE`.
