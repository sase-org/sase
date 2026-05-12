---
create_time: 2026-05-12 12:17:34
status: done
bead_id: sase-35
tier: epic
prompt: sdd/prompts/202605/phase7_notification_perf.md
---
# Phase 7 Notification Store Performance Floor Plan

## Context

GitHub Actions fails `just phase7-perf-check` only on:

`notification_store.synthetic_5k.notification_store_append_plus_rewrite_concurrency`

The observed median is `2.762291s`, above the existing absolute ceiling of `2.717252s` (`1.40x` the recorded Phase 7B
Rust median of `1.940894s`). The performance expectation must stay intact: do not relax the baseline, do not increase
the slowdown factor, and do not remove this anchor.

The benchmark races one Python thread appending 25 notifications through the public store API with one Python thread
loading 5k notifications, marking 250 rows read, and rewriting the full file. Production correctness requires append and
rewrite to share the Rust sidecar lock and to preserve valid JSONL; that contract should not change.

Initial source inspection shows the likely cost centers:

- Python repeatedly crosses the PyO3 boundary for 25 appends, and every append currently returns a fully hydrated update
  outcome after rereading the whole file.
- Rust `rewrite_notifications` also rewrites through tempfile/rename, fsyncs the temp file and directory, then rereads
  the full file to build a complete outcome.
- Python converts full notification lists to/from dict/dataclass shapes even when callers ignore returned rows.
- The failing measurement is close to the ceiling, so a narrow elimination of unnecessary rereads/hydration on write
  paths should be enough, but the fix should target real product overhead rather than benchmark slack.

## Phase 1: Reproduce And Profile

Owner: first distinct agent instance.

Goals:

- Run `just install` in this workspace if needed.
- Reproduce the failing surface locally with
  `.venv/bin/python tests/perf/bench_notification_store.py --runs 3 --warmup 1 --count 5000`.
- Run the full floor check once to confirm whether local failure matches CI or whether only CI variance crosses the
  ceiling.
- Add temporary timing probes only outside tracked source, or use profiler commands, to split time across:
  - Python fixture copy and cache invalidation.
  - Python `load_notifications` hydration.
  - 25 append calls.
  - one rewrite call.
  - Rust read, write, fsync/rename, and post-write reread.
- Produce a short finding identifying the dominant avoidable cost.

Acceptance:

- A clear local baseline exists for the failing anchor.
- The next phase has a concrete optimization target, not speculation.

## Phase 2: Rust Store Write-Path Optimization

Owner: second distinct agent instance.

Goals:

- In `../sase-core`, add or adjust Rust notification-store APIs so write operations that only need mutation metadata do
  not reread and return all rows.
- Preserve the existing full-outcome APIs for callers that need rows.
- Keep append/rewrite locking semantics unchanged: append and rewrite must use the same sidecar lock, rewrite must
  remain lock-then-tempfile-rename, and JSONL validity under concurrent append/rewrite must remain covered.
- Prefer a counts-only append path for Python `append_notification`, since the public Python API ignores the returned
  outcome.
- Prefer a counts-only rewrite path for Python `rewrite_notifications`, since the public Python API currently ignores
  returned rows.
- Add Rust parity/unit coverage around the new no-row write APIs and existing concurrency behavior.

Acceptance:

- Rust tests in `../sase-core` pass for notification store coverage.
- The new APIs remove full-file post-write rereads where rows are unused.

## Phase 3: Python Facade Integration And Focused Tests

Owner: third distinct agent instance.

Goals:

- Update the Python facade and public notification store wrappers to call the no-row Rust write APIs for append and
  rewrite paths that discard returned notifications.
- Keep existing typed wire conversion behavior for read/snapshot APIs and for state updates that explicitly request
  rows.
- Update or add focused Python tests proving:
  - `append_notification` routes through the no-row/counts write binding.
  - `rewrite_notifications` routes through the no-row/counts write binding.
  - existing notification store behavior and append-plus-rewrite concurrency correctness still hold.
- Avoid changing benchmark expectations or baseline files unless the benchmark schema genuinely needs to report a new
  measured scenario.

Acceptance:

- Focused Python notification store tests pass.
- The failing benchmark anchor improves without weakening the floor.

## Phase 4: Full Verification And CI Parity

Owner: fourth distinct agent instance.

Goals:

- Run the focused benchmark enough times to confirm stable headroom below the existing ceiling:
  `.venv/bin/python tests/perf/bench_notification_store.py --runs 5 --warmup 1 --count 5000`
- Run the exact GitHub Actions command: `just phase7-perf-check`
- Run required repo checks for modified repos:
  - `just check` in this repo if tracked files here changed.
  - `just check` in `../sase-core` if tracked files there changed.
- Preserve and inspect the generated floor-check report at
  `sdd/tales/202604/perf_artifacts/rust_backend_phase7_floor_check.json`.

Acceptance:

- `just phase7-perf-check` passes without changing the expected performance floor.
- All required checks for modified repositories pass, or any non-performance blocker is documented with exact command
  output.

## Constraints

- Do not lower expected performance expectations.
- Do not modify memory files.
- Do not revert unrelated work in this workspace or sibling repos.
- Keep append/rewrite correctness semantics stronger than the old Python path.
- Keep edits scoped to notification store write-path performance unless Phase 1 proves another source is responsible.
