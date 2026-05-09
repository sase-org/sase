---
create_time: 2026-05-09 17:35:53
status: done
prompt: sdd/prompts/202605/notification_mark_all_read_perf.md
---
# Plan: Fix Phase 7 notification mark-all-read perf floor

## Problem

GitHub Actions is failing `just phase7-perf-check` only on:

`notification_store.synthetic_5k.notification_store_5k_mark_all_read`

The reported CI median is `149134.60us`, above the current floor ceiling of `100359.00us` (`1.40x` the captured Phase 7
Rust median of `71685.00us`). The neighboring notification store anchors pass, including load snapshot, bulk dismissed
burst, append/rewrite concurrency, and modal dismiss burst.

Local reproduction on this workspace shows `mark_all_read` near the original captured median (`~67.5ms`), which points
to CI storage/conversion sensitivity rather than a deterministic local slowdown. The failure is still a useful signal
because the implementation does unnecessary work on every state update.

## Root Cause

`src/sase/notifications/store.py::mark_all_read()` calls the Rust facade and uses only `outcome.changed_count`.

The Rust implementation in `../sase-core/crates/sase_core/src/notifications/store.rs` does considerably more:

1. Lock the store.
2. Read and deserialize the full 5k JSONL file.
3. Mark unread rows as read.
4. Rewrite the whole file through the tempfile/fsync/rename path.
5. Read and deserialize the full file again.
6. Build counts over all rows.
7. Return all notifications through PyO3 as Python dictionaries.
8. Rehydrate all dictionaries into Python `Notification` dataclasses.

For `mark_all_read`, and for the other Python public state-mutating helpers, the post-write notification snapshot is not
used by the caller. The extra post-write read plus cross-language conversion makes a full-file mutation much more
sensitive to GitHub-hosted runner IO and Python object allocation variance.

## Implementation Approach

1. Add a lightweight outcome path in `sase-core` for state updates that only need mutation metadata.
   - Keep the existing public `apply_notification_state_update()` API shape for compatibility.
   - Internally split the implementation so callers can choose whether to include the post-write notification snapshot.
   - When the snapshot is omitted, still return accurate `matched_count`, `changed_count`, `appended_count`,
     `rewritten`, and `expired_ids`.
   - Preserve existing full snapshot behavior for callers that depend on `outcome.notifications`, especially rewrite-all
     and tests that inspect returned rows.

2. Expose the lightweight path through the PyO3 extension.
   - Add a binding such as `apply_notification_state_update_counts`.
   - Parse the same update dictionary as the current binding.
   - Return the same wire outcome dictionary with empty `notifications`, default counts/stats when a snapshot was
     intentionally skipped.

3. Route Python store helpers that only use counts through the lightweight binding.
   - Add a private facade helper in `src/sase/core/notification_store_facade.py` for metadata-only state updates.
   - Update `src/sase/notifications/store.py::_apply_state_update()` to use the metadata-only path by default.
   - Add an opt-in full-outcome path for `expire_due_snoozes()`, which needs returned notifications to update the
     caller's in-memory objects.

4. Add focused tests.
   - Rust core test proving metadata-only `MarkAllRead` persists the mutation and returns correct counts without
     returning notifications.
   - PyO3 binding test for the metadata-only path shape.
   - Python facade/store tests covering `mark_all_read()` and `expire_due_snoozes()` so the count-only routing does not
     break the one caller that needs returned rows.

5. Verify performance and correctness.
   - Rebuild the local Rust extension with `just rust-install` or `just install`.
   - Run focused Rust tests in `../sase-core`.
   - Run focused Python notification tests.
   - Run the notification benchmark and `just phase7-perf-check`.
   - Run `just check` in this repo because code files will be modified.

## Expected Outcome

`mark_all_read` should avoid the second full-file read and avoid returning 5k notification objects through PyO3/Python
for a caller that only needs a changed count. That should reduce the median enough for CI to pass the existing 100 ms
floor without weakening the regression gate.

If the optimized path still fails only on CI while local results improve materially, the remaining option is a narrowly
documented per-anchor tolerance override. That should be treated as a fallback, not the primary fix, because there is
clear avoidable work in the implementation.
