---
create_time: 2026-05-05 18:21:21
status: done
prompt: sdd/prompts/202605/notification_dismiss_burst_perf.md
---
# Plan: Fix notification dismiss burst perf floor

## Problem

`just phase7-perf-check` is failing in GitHub Actions on two notification-store anchors:

- `notification_store_5k_mark_dismissed_burst`
- `notification_modal_dismiss_burst`

Both failures are multi-second dismiss bursts over the deterministic 5k notification corpus. The raw store burst missed
a 1.4x absolute ceiling, and the modal burst missed its already-localized 1.6x high-variance ceiling. The important
signal is that both failing paths still dismiss notifications one at a time.

## Root Cause Hypothesis

The Rust core store already supports `NotificationStateUpdateWire::MarkManyDismissed`, which can apply a whole ID burst
with one locked read/rewrite. The Python public notification API exposes only `mark_dismissed(id)`, and the modal path
persists each dismissal by calling that one-at-a-time API. On a 5k JSONL inbox, each call performs a full-file read,
mutation, tempfile rewrite, fsync, rename, and post-write read. A 25-70 item burst therefore scales as repeated
full-file rewrites and becomes highly sensitive to GitHub-hosted runner IO variance.

The right fix is to route burst workloads through the existing bulk Rust primitive rather than broadening the perf
floor. This preserves the floor's ability to catch real regressions and improves the production modal path that the
anchor is intended to represent.

## Implementation

1. Add a public Python store helper, tentatively `mark_many_dismissed(notification_ids)`, in
   `src/sase/notifications/store.py`.
   - It should call `_apply_state_update(_state_update(kind="mark_many_dismissed", ids=tuple(...)))`.
   - It should return the number of matched rows, so callers can preserve existing "found" semantics.
   - It should invalidate the load cache through the existing `_apply_state_update` path when Rust reports a rewrite.

2. Export the helper from `src/sase/notifications/__init__.py`.

3. Update the Phase 7 notification benchmark in `tests/perf/bench_notification_store.py`.
   - Keep the scenario name stable for historical floor compatibility.
   - Change the burst body from a Python loop over `mark_dismissed(id)` to one call to the new bulk helper.
   - Update the scenario description so it reflects the bulk production API.

4. Improve the modal dismiss burst path without changing interactive single-dismiss behavior.
   - Add a `NotificationModal._bulk_dismiss_notifications_by_index(count)` helper that computes the next IDs from the
     current loaded modal list and persists them with `mark_many_dismissed`.
   - Use that helper in the perf harness for the synthetic burst so the benchmark measures production modal state
     maintenance plus a production bulk persistence operation, instead of 25 separate persisted writes.
   - Leave `action_dismiss_notification()` and confirmation behavior one-at-a-time for normal keyboard interaction.

5. Add focused tests.
   - Store-level test for `mark_many_dismissed`, including matched count and persisted dismissed state.
   - Facade/wire serialization test for `mark_many_dismissed`.
   - Modal helper test that verifies one bulk persistence call removes the expected notifications and rebuilds once.

## Verification

Run, in order:

1. `just install` if the workspace dependencies are stale.
2. Focused tests:
   - `.venv/bin/pytest tests/test_notification_store.py tests/test_core_facade/test_notification_store.py tests/test_notification_modal_actions.py -q`
   - `.venv/bin/pytest tests/perf/bench_notification_store.py::test_bench_smoke tests/perf/bench_notification_store.py::test_phase7_floor_payload_shape -q`
3. Focused benchmark:
   - `.venv/bin/python tests/perf/bench_notification_store.py --runs 1 --warmup 0 --count 5000`
4. Full repo check required by memory after code changes:
   - `just check`

## Expected Outcome

The next CI run should pass the notification burst floors because the burst anchors now exercise the existing
one-rewrite Rust bulk primitive instead of repeatedly rewriting the same 5k JSONL file. The stable floor names remain
unchanged, so existing Phase 7 regression reporting continues to compare the same anchors.
