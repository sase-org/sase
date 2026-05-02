---
create_time: 2026-04-24 09:15:48
status: done
prompt: sdd/prompts/202604/fix_ci_inline_snapshot_xdist.md
---
# Fix CI failure: `--inline-snapshot=short-report cannot be combined with xdist`

## Problem

The CI `test` job is hard-failing on every run with:

```
ERROR: --inline-snapshot=short-report cannot be combined with xdist
```

This blocks merges to `master` and the Python 3.12/3.13/3.14 matrix.

## Root Cause

Two orthogonal pieces of configuration collide:

1. `.github/workflows/ci.yml:87` runs: `just test-cov --inline-snapshot=short-report`
2. The `test-cov` recipe in `Justfile` (lines 88–97) runs pytest with `-n auto --dist=loadfile` (pytest-xdist,
   parallel).

The `inline-snapshot` plugin (v0.32.5, per `uv.lock`) explicitly rejects `--inline-snapshot=short-report` when xdist is
active. The `short-report` mode aggregates "here is what would change" snapshot-drift data across the whole run, and the
plugin has no IPC to collect that from xdist worker subprocesses — so it bails out at pytest collection time rather than
silently dropping reports.

History: commit `6e56faa6` ("chore: Enable inline-snapshot in CI by passing --inline-snapshot=short-report to pytest")
added the flag when CI was still invoking `just test` (also xdist). Either the plugin tightened its compatibility check
in a subsequent release, or this has been silently broken since then — today it is hard-failing.

## Goal

Keep parallel test execution in CI (for speed) while still letting `inline-snapshot` catch snapshot drift. We do not
need the `short-report` summary formatting if keeping it costs us parallel CI.

## Options Considered

1. **Drop `--inline-snapshot=short-report` from CI.** Without the flag, `inline-snapshot`'s default behavior still fails
   tests whose snapshots don't match — enforcement is preserved; we only lose the aggregated "here's the diff you need
   to apply" summary in the CI log. **Simplest, lowest risk.**
2. **Run snapshot tests serially, rest in parallel.** Two pytest invocations, marker/path split, more CI wall time, more
   complexity in the Justfile.
3. **Drop xdist from `test-cov`.** Slows down all CI and local `just check` runs — regression in developer ergonomics.
4. **Pin/upgrade `inline-snapshot`.** Brittle; no evidence a compatible version exists; touches `uv.lock`.
5. **Use `--inline-snapshot=report` instead of `short-report`.** Same xdist-incompatibility check in the plugin.

**Recommendation: Option 1.** We keep parallel CI, we keep snapshot drift enforcement (tests still fail), we only lose a
log-formatting nicety. If the "here's the diff" summary turns out to be genuinely valuable later, we can add a
serial-only snapshot-audit CI step in a follow-up.

## Proposed Change

One-line edit in `.github/workflows/ci.yml`:

```diff
-        run: just test-cov --inline-snapshot=short-report
+        run: just test-cov
```

No `Justfile` change. No production code change. No test change. No dependency change.

## Validation

- Push to a branch; confirm the `test` matrix passes on Python 3.12 / 3.13 / 3.14.
- Locally run `just test-cov` (on a clean workspace) to confirm the Justfile path still exits 0.
- Snapshot enforcement sanity check (optional): locally edit one snapshot string, run `just test-cov`, confirm pytest
  fails on the mismatch. Skip if we're confident in `inline-snapshot`'s default behavior.

## Risk and Rollback

Very low risk. Rollback is reverting the one-line change. The only capability lost is the aggregated `short-report`
summary in CI logs; real snapshot drift is still caught as a hard test failure.

## Out of Scope

- Restoring any form of aggregated snapshot-diff reporting in CI (deferred; add only if needed).
- Auditing whether other `inline-snapshot` CLI modes are incompatible with xdist (not relevant here; we stop passing the
  flag).
- Touching `uv.lock` or `pyproject.toml` to change the `inline-snapshot` pin.
