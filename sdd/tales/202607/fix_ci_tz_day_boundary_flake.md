---
create_time: 2026-07-05 22:18:45
status: wip
prompt: sdd/prompts/202607/fix_ci_tz_day_boundary_flake.md
---
# Fix CI Day-Boundary Timezone Flake in Time-Formatting Tests

## Problem

CI run #9078 on `master` (commit 932b6fa) failed in the `test (3.14)` job with two test failures (the 3.12/3.13 jobs
were cancelled as a consequence):

1. `tests/test_directives_time_parsing.py::test_parse_absolute_time_hhmm_past_wraps_to_tomorrow`
   - `assert datetime.date(2026, 7, 6) == datetime.date(2026, 7, 7)`
2. `tests/test_agent_model.py::test_format_wait_until_same_day`
   - `AssertionError: assert 'Jul 6 14:30' == '14:30'`

## Root Cause

This is a **day-boundary timezone flake**, not a product bug. The production code is correct.

- The autouse `_pin_configured_timezone` fixture (`tests/conftest.py`) pins the SASE configured timezone to
  `America/New_York` for every test, so `local_now()` (`src/sase/core/time.py`) always observes the Eastern clock.
- The code under test follows the codebase convention and uses `local_now()`:
  - `parse_absolute_time()` (`src/sase/xprompt/_directive_time.py`) wraps a past `HHMM` target to tomorrow relative to
    `local_now()`.
  - `format_wait_until()` (`src/sase/ace/tui/models/agent_time.py`) decides same-day vs different-day rendering against
    `local_now()`.
- The two failing tests, however, build their _expectations_ from bare `datetime.now()` — the **system** clock, which is
  UTC on GitHub Actions runners.

Every day between 00:00 and 04:00/05:00 UTC (i.e. 20:00–midnight Eastern), the UTC calendar date is one day ahead of the
Eastern date, so the two clocks disagree about "today"/"tomorrow" and both tests fail. The failing CI run executed these
tests at ~01:41 UTC on Jul 6 (21:41 Eastern on Jul 5) — squarely inside that window:

- Test 1: `parse_absolute_time("0000")` wrapped Eastern midnight to **Jul 6 00:00**, but the test expected
  `(datetime.now() + 1 day).date()` = **Jul 7** (UTC-based).
- Test 2: the test built "today 14:30" from the UTC clock (**Jul 6** 14:30), but `format_wait_until()`'s `local_now()`
  reference said today is **Jul 5**, so it rendered the different-day form `"Jul 6 14:30"` instead of `"14:30"`.

Both failures were reproduced locally by running the two tests with `TZ=UTC` while the current wall-clock was inside the
divergence window — identical assertion output to CI.

Note that `src/sase/core/time.py`'s module docstring explicitly forbids exactly this pattern ("Never use the bare system
clock ... for any value that is compared against ... a configured-tz value"), and
`tests/test_timezone_runtime_consistency.py` exists to pin the convention. These two tests (plus one sibling) are
stragglers that predate that cleanup.

## Fix

Make the test expectations use the same clock as the code under test (`local_now()`), so tests are self-consistent
regardless of the host system timezone or time of day. No production code changes.

### 1. `tests/test_directives_time_parsing.py`

In `test_parse_absolute_time_hhmm_past_wraps_to_tomorrow`, import `local_now` from `sase.core.time` and change the
expectation:

```python
assert target.date() == (local_now() + timedelta(days=1)).date()
```

The other `datetime.now()` usages in this file are safe (they only feed ±30-day offsets or assert hour/minute fields
that the parser preserves by construction) and are left unchanged.

### 2. `tests/test_agent_model.py`

The file already imports `local_now`. Switch the two `format_wait_until` tests that build naive "today"/"tomorrow"
targets from the system clock:

- `test_format_wait_until_same_day`: build the target from `local_now().replace(hour=14, minute=30, ...)`.
- `test_format_wait_until_different_day`: build the target from `(local_now() + timedelta(days=1)).replace(...)`. (This
  test currently passes only because any cross-clock date mismatch still lands in the different-day branch, but it
  violates the same convention and is a one-token fix.)

The remaining `datetime.now()` usages in this file are opaque roundtrip fixture data never compared against a
configured-tz clock — audited and left unchanged.

### Considered and rejected

- **Freezing `local_now()` via monkeypatch**: fully deterministic, but heavier than needed and inconsistent with how
  sibling tests in these files already use live `local_now()` with relative deltas. The residual race (Eastern midnight
  falling between two adjacent statements) is sub-millisecond once per day, the same accepted risk class as the rest of
  the suite.
- **Adding a `tz_divergence` regression test**: the divergence suite already covers the production paths
  (`test_wait_absolute_time_uses_configured_clock`); the bug here is in test expectations, not product code.

## Verification

1. Reproduce-then-verify: run the two previously-failing tests with `TZ=UTC` (which recreates CI's system clock; the fix
   must pass both inside and outside the 00:00–04:00 UTC divergence window):
   `TZ=UTC pytest tests/test_directives_time_parsing.py tests/test_agent_model.py`
2. Run the same tests without the `TZ` override (dev-machine conditions).
3. Run `just check` to satisfy the repo-wide gate.
