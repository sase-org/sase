---
create_time: 2026-05-12 18:24:45
status: completed
prompt: sdd/prompts/202605/dismiss_freeze.md
---
# Plan: Fix TUI Freeze When Dismissing Agents

## Problem Statement

When the user kills/dismisses an agent (single or bulk) in the `sase ace` TUI Agents tab, the TUI becomes unresponsive
for several seconds. The freeze severity scales with the number of agents being dismissed and the size of the user's
existing dismissed-bundle archive.

On the user's machine, `~/.sase/dismissed_bundles/` currently contains **16,707** bundle JSON files. Every single-agent
dismiss triggers up to ~16k file reads + JSON parses, even though the dismiss runs in a worker thread.

## Suspected Origin

The regression was introduced by the recent `sase-37` epic (Agent Archive and Query Language). Specifically, the
archive-revision tracking added in:

- `7fcb5706d feat: add v2 dismissed bundle archive index (sase-37.2)`
- `ce8cb9e37 feat: harden dismissed agent archive storage (sase-37.7)`

These commits added `archive_revision` tracking on every dismissed bundle and a fallback filesystem scan in
`next_archive_revision()` that defeats the purpose of the SQLite index.

## Root Cause

The freeze chain is:

1. **TUI dismiss entry point** `src/sase/ace/tui/actions/agents/_dismissing.py:223-229` — `_dismiss_planned_agent` calls
   `self.call_later(_run_dismiss_persistence_async, ...)`.

2. **Worker dispatch (correct in principle)** `_dismissing.py:247-253` —
   `await asyncio.to_thread(_persist_single_dismiss_transaction, ...)`. This is _meant_ to keep the UI responsive.

3. **Persistence inside the worker**
   `_persist_single_dismiss_transaction → persist_dismiss_side_effects → save_dismissed_bundle`
   (`src/sase/ace/dismissed_agents.py:173-232`).

4. **The hot loop — primary culprit** `save_dismissed_bundle` runs a retry loop of up to **8** iterations
   (`dismissed_agents.py:190`), and each iteration calls `next_archive_revision(_DISMISSED_BUNDLES_DIR, bundle)`.

5. **`next_archive_revision` performs an O(N) directory scan + JSON parse**
   `src/sase/ace/dismissed_bundle_index.py:262-294`:

   ```python
   def next_archive_revision(root, bundle):
       agent_id = _agent_id_for_bundle(bundle)
       max_revision = 0
       if _index_path_for_root(root).is_file():
           ...  # cheap DB query already returns the answer
       for path in _iter_bundle_paths(root):              # <— scans 16k+ files
           try:
               existing = _read_bundle(path)              # <— JSON parse per file
               if _agent_id_for_bundle(existing) != agent_id:
                   continue
               max_revision = max(max_revision, ...)
           ...
       return max_revision + 1 if max_revision else DEFAULT_ARCHIVE_REVISION
   ```

   `_iter_bundle_paths()` (`dismissed_bundle_index.py:859`) walks every shard directory and globs every `*.json` and
   `*/bundle.json`. `_read_bundle()` reads + `json.loads()` each one.

6. **GIL starvation freezes the TUI** `json.loads` is a C call that does **not** release the GIL between iterations of a
   tight 16k-file loop. Even though the work runs in a worker thread, the GIL is held long enough that Textual's render
   loop on the main thread cannot get scheduling slices — producing the visible freeze.

7. **Bulk dismiss amplifies it** `persist_bulk_dismiss_transaction` (`_dismissing.py:294-315`) loops over agents and
   calls `persist_dismiss_side_effects` for each, so N dismissed agents triggers O(N × 16k × ≤8) reads.

The SQLite index query that immediately precedes the filesystem scan (`dismissed_bundle_index.py:269-278`) already
returns the correct `MAX(archive_revision)` for the agent — the subsequent file scan is defensive redundancy that has
become catastrophically expensive.

## Goal

Restore single-digit-millisecond dismiss persistence so the TUI never freezes when dismissing one or many agents, while
preserving the archive-revision correctness guarantees added by sase-37.

## Proposed Fix

### 1. Make `next_archive_revision()` index-driven (primary fix)

Trust the SQLite index as the source of truth for max revision per `agent_id`. The index is already maintained
transactionally by `upsert_bundle_summary()` after every successful bundle write, and a `rebuild_index()` path exists
for recovery from corruption or migration. The fallback filesystem scan was inserted as a safety net but is the cause of
the freeze.

**Change** (in `src/sase/ace/dismissed_bundle_index.py:262-294`):

- Drop the `for path in _iter_bundle_paths(root)` block entirely.
- Keep the SQLite query as the authoritative answer.
- If the index is missing (`_index_path_for_root(root).is_file()` is false), return `DEFAULT_ARCHIVE_REVISION` and rely
  on the caller's collision-detection retry to handle any edge case.

### 2. Eliminate the per-retry rescan in `save_dismissed_bundle`

Even with a fast `next_archive_revision`, the retry loop in `src/sase/ace/dismissed_agents.py:190-222` recomputes the
revision on every retry iteration. Retries fire only on `FileExistsError` (collision), so it's safe to bump the revision
locally on retry rather than recompute from scratch.

**Change**:

- Call `next_archive_revision` once before the loop.
- On `FileExistsError`, increment the local revision and try again.
- Cap retries at the existing limit of 8.

### 3. Defensive: rebuild-on-suspicion rather than scan-on-every-write

Move the "filesystem scan to find missing revisions" logic out of the hot dismiss path and into the existing
`rebuild_index()` / `verify_index()` flow (`dismissed_bundle_index.py:243`, `:332`). These are invoked via the archive
maintenance CLI added in sase-37.7/37.8 and at startup, which is the correct place for O(N) work.

No new code is required for this — removing the inline scan automatically delegates recovery to those existing paths.

### 4. Regression test

Add a unit test that asserts `next_archive_revision` does not perform a directory scan when the SQLite index exists. The
test seeds the index with a known max revision, populates the filesystem with bogus extra bundles that would otherwise
be read, and verifies the function returns the indexed revision without parsing the bogus files. A simple way to detect
this is to monkeypatch `_read_bundle` to raise, then assert the function still succeeds.

File: extend the existing `tests/ace/test_dismissed_bundle_index.py` (or similar) test module.

### 5. Performance smoke test

Add a benchmark test that creates ~1k bundle files in a tempdir and asserts that a single `save_dismissed_bundle()` call
completes in well under 100 ms. This guards against future regressions where someone re-adds the scan or introduces
equivalent O(N) work into the dismiss hot path.

## Out of Scope

- Changing the archive on-disk format or schema. The fix is purely about removing redundant work; the index already has
  everything needed.
- Background-thread architecture changes. The existing `asyncio.to_thread` dispatch is correct; fixing the O(N) work
  makes the existing dispatch sufficient.
- The 8-retry loop's outer limit (sase-37.7 design). Keeping retry semantics intact.

## Risk

Low. The SQLite index is already authoritative — it is written transactionally inside `upsert_bundle_summary`
immediately after each successful bundle write (`dismissed_agents.py:226-231`). The filesystem scan was a
belt-and-suspenders guard. Removing it is safe as long as `rebuild_index()` is run on detected index corruption (which
the existing CLI surface and migration markers already cover).

## Verification

1. With ~16k bundles in the local archive, dismiss a single agent and observe that the TUI remains responsive (no
   perceptible freeze; `agent dismiss persistence` log line shows elapsed < 50 ms).
2. Bulk-dismiss 10 agents and confirm same responsiveness.
3. Confirm archive revision still increments correctly: dismiss the same agent identity twice and inspect
   `archive_revision` in the two resulting bundle JSON files — should be 1 then 2.
4. `just check` passes.

## Affected Files

- `src/sase/ace/dismissed_bundle_index.py` — drop scan in `next_archive_revision`.
- `src/sase/ace/dismissed_agents.py` — hoist `next_archive_revision` call out of the retry loop and bump revision
  locally on collision.
- `tests/ace/test_dismissed_bundle_index.py` (or nearest existing test module) — regression test that the dismiss path
  does not read bundle files.
