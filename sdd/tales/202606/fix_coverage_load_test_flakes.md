---
create_time: 2026-06-29 10:10:56
status: done
prompt: sdd/prompts/202606/fix_coverage_load_test_flakes.md
---
# Fix two CI test failures caused by load-sensitive flakes

## Problem

GitHub Actions (`just test-cov`) fails intermittently with **two** failures in an otherwise-green run
(`2 failed, 14807 passed` after ~9 minutes):

```
# Failure A
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot
    - AssertionError: Timed out waiting for commit delta summary

# Failure B
... pytest introspection follows:
Args:
assert (0.5,) == ()
  Left contains one more item: 0.5
```

Both pass locally in isolation and in a full local visual/unit run (125 visual + ~14.5k unit tests pass here). They only
surface under the CI `test-cov` run, which adds `--cov-branch` coverage instrumentation and runs the whole suite in
parallel with `-n <workers> --dist=loadfile`. Coverage tracing slows every line of Python, which is the shared trigger
for both failures.

## Root cause analysis

### Failure A — too-tight test deadline (`test_agents_commit_messages_panel_png_snapshot`)

The test helper `_wait_for_commit_delta_summary` in `tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py`
polls for the agent's commit-delta summary to be computed, bounded by:

```python
deadline = time.monotonic() + 3.0
```

The summary is produced asynchronously (debounced detail updates plus a threaded linked-delta load). In isolation this
resolves well within 3 seconds. Under the coverage-instrumented, fully-parallel CI run, that asynchronous work is slowed
enough to occasionally exceed the 3-second budget, so the helper raises "Timed out waiting for commit delta summary".
This is a **test-timing assumption**, not a product regression — locally the test's total call time is already ~3.5s
(setup + wait), confirming the budget is marginal.

### Failure B — leaked timer thread pollutes a global `time.sleep` mock

The failing assertion is uniquely produced by `pytest-mock`'s wrapper around the `assert_called*` family. The only
assertion in the whole suite that can emit `assert (0.5,) == ()` is:

- `tests/test_plan_utils.py` → `test_handle_plan_approval_rechecks_auto_approve_while_waiting` →
  `sleep.assert_called_once()` (line ~167), where the polled function under test sleeps `_POLL_INTERVAL = 0.5`.

That test patches sleep with `patch("sase.llm_provider._plan_utils.time.sleep")`. Because `_plan_utils` does
`import time`, this patches the **global** `time.sleep`, so every `time.sleep` call in the worker process during the
test is counted — not just the loop under test. The production loop sleeps exactly once, so in isolation the assertion
is deterministic and passes.

The pollution source is a genuine resource leak in `src/sase/output.py`:

```python
@contextmanager
def provider_timer(message=...):
    ...
    with Live(...) as live:
        def _update_timer():
            while True:                 # no stop condition
                live.update(_get_timer_text())
                time.sleep(0.5)
        timer_thread = threading.Thread(target=_update_timer, daemon=True)
        timer_thread.start()
        yield
        # finally: final update + time.sleep(0.3) — thread is never stopped
```

`provider_timer` wraps every real LLM provider invocation (`claude.py`, `codex.py`, `qwen.py`, `opencode.py`). Its
daemon thread loops forever (`while True`) with no stop event and is never joined on context exit, so once any test
enters `provider_timer`, the thread keeps calling `time.sleep(0.5)` every half second for the **rest of the worker
process's life**.

Under `--dist=loadfile`, one xdist worker runs many test files sequentially. When an earlier LLM-provider test on the
same worker leaks a `provider_timer` thread, that thread's `time.sleep(0.5)` ticks land inside the global mock while
`test_handle_plan_approval_...` is running. The mock's `call_count` becomes ≥ 2, so `assert_called_once()` fails, and
the introspection prints the leaked thread's last call args, `(0.5,)`. The `0.5` value matches both the leaked timer
interval and the poll interval, which is why the symptom is specifically `(0.5,)`. Coverage instrumentation widens the
timing window, so it only appears in full CI.

This is consistent with all observations: deterministic in isolation, flaky only under the full parallel coverage run,
and the exact `(0.5,) == ()` signature.

## Goals

- Make the CI `test-cov` run reliably green by removing the two load-sensitive failure modes at their source.
- Fix the real resource leak in `provider_timer` (a forever-spinning daemon thread), not just the test symptom.
- Keep the visual snapshot test meaningful while tolerant of CI load.

## Proposed changes

### 1. Stop the `provider_timer` daemon thread on context exit (primary fix for B)

In `src/sase/output.py`, give the timer thread a `threading.Event` stop signal:

- Replace the unbounded `while True: ...; time.sleep(0.5)` loop with a loop that waits on a stop event (e.g.
  `while not stop_event.wait(0.5): live.update(...)`), so the wait is interruptible and the thread exits promptly when
  signaled.
- In the context manager's `finally`, set the stop event and `join()` the thread (with a short timeout) before/around
  the final "completed in …" update.
- Preserve the existing visible behavior: the live timer updates roughly twice a second while the block runs and shows
  the final completion message on exit.

This eliminates the leaked thread, so it can no longer pollute a global `time.sleep` mock (or waste CPU spinning for the
life of any long-running process).

### 2. Harden the plan-approval sleep assertion (defense-in-depth for B)

In `tests/test_plan_utils.py`, `test_handle_plan_approval_rechecks_auto_approve_while_waiting`, make the assertion
robust to any stray global `time.sleep` activity rather than depending on an exact global call count:

- Keep the existing `get_auto_action.call_count == 3` check (this already proves the poll loop iterated exactly once
  before auto-approval was observed).
- Replace `sleep.assert_called_once()` with an assertion that the poll loop slept with the expected interval (e.g.
  assert `_POLL_INTERVAL` was among the sleep calls), which verifies the intended behavior without being sensitive to
  unrelated background sleeps.

This keeps the test green even if some other component ever leaks a sleeping thread, without weakening what the test
actually validates.

### 3. Relax the commit-delta-summary wait budget (fix for A)

In `tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py`, increase the `_wait_for_commit_delta_summary`
deadline from 3 seconds to a CI-load-tolerant value (on the order of 10–15s), matching how other visual waits already
allow generous margins. The polling cadence stays the same, so a fast local run is unaffected; only the worst-case
ceiling grows. Optionally factor the timeout into a named constant for clarity.

## Out of scope / non-goals

- No change to product behavior of plan approval, commit-delta rendering, or the Agents tab. These are test-stability
  and a thread-lifecycle fix only.
- No broad audit of every background-thread/`time.sleep` site. Only the confirmed leaker (`provider_timer`) is
  addressed; the test hardening in change 2 covers the general risk.

## Validation

- Run the previously-failing tests directly:
  - `just test-visual tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot`
  - `pytest tests/test_plan_utils.py`
- Add/extend a focused test for `provider_timer` confirming the timer thread is no longer alive after the context
  manager exits (e.g. assert no `sase-`/timer-named thread remains, or that a sentinel stop event is set).
- Run `just check` (after `just install`) to confirm lint, types, and the gated test subset pass.

## Risks

- `provider_timer` change touches a CLI presentation path used by all providers; the fix must preserve the live update
  cadence and the final completion message. Risk is low and covered by the focused thread-lifecycle test.
- Raising the visual wait deadline only affects the failure ceiling, not normal timing, so it cannot slow down healthy
  runs meaningfully.
