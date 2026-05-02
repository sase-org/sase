---
create_time: 2026-04-22 10:17:40
status: done
prompt: sdd/prompts/202604/fix_interrupt_monitor_test_race.md
---

# Fix flaky Python 3.14 CI failure in `test_start_interrupt_monitor_missing_message_field`

## Problem

Python 3.14 CI intermittently fails with:

```
FAILED tests/test_llm_provider_subprocess.py::test_start_interrupt_monitor_missing_message_field
  - AssertionError: Expected 'terminate' to have been called once. Called 0 times.
```

The test itself passes 10/10 locally on Python 3.14.3 under low load. CI runs 4244 tests in 122s and loses the race.

## Root Cause — Test Race Condition

The monitor at `src/sase/llm_provider/_subprocess.py:83-96` runs these operations in sequence on a background thread:

```python
def _monitor_interrupt() -> None:
    while process.poll() is None:
        if interrupt_path.exists():
            try:
                data = json.loads(interrupt_path.read_text(encoding="utf-8"))
                on_interrupt(data.get("message"))
                interrupt_path.unlink(missing_ok=True)   # step A
                process.terminate()                       # step B
            except (OSError, json.JSONDecodeError):
                pass
            return
        time.sleep(1.0)
```

The test at `tests/test_llm_provider_subprocess.py:88-106` does:

```python
assert _wait_until(lambda: bool(received))
assert received == [None]
assert _wait_until(lambda: not interrupt_path.exists())  # waits for step A
process.terminate.assert_called_once()                    # checks step B with no wait!
```

If the OS scheduler preempts the monitor thread between step A (unlink) and step B (terminate), the main test thread
can:

1. Observe `not interrupt_path.exists()` → `_wait_until` succeeds.
2. Fall through to `process.terminate.assert_called_once()` **before** step B runs.
3. Fail because terminate hasn't been called yet.

Python 3.14's scheduling under heavy CI load makes this race more likely to manifest than on 3.12/3.13.

The identical race exists in `test_start_interrupt_monitor_fires_callback_and_terminates` (line 42) — it just happened
to not lose the coin flip in this CI run. Both tests need the same fix.

## Fix — Wait For The Terminate Call

Insert a `_wait_until` poll for `process.terminate.called` before the `assert_called_once()` check in both vulnerable
tests.

**Before** (tests/test_llm_provider_subprocess.py, lines 41–42 and 105–106):

```python
assert _wait_until(lambda: not interrupt_path.exists())
process.terminate.assert_called_once()
```

**After**:

```python
assert _wait_until(lambda: not interrupt_path.exists())
assert _wait_until(lambda: process.terminate.called)
process.terminate.assert_called_once()
```

The `_wait_until(lambda: process.terminate.called)` poll closes the race by blocking until the mock actually records the
call. `assert_called_once()` still enforces the stronger invariant that terminate was called exactly once.

## Files To Change

- `tests/test_llm_provider_subprocess.py` — two spots (lines ~42 and ~106).

No source changes. The production code is correct; this is purely a test-reliability fix.

## Explicitly Out Of Scope

- Do NOT modify `src/sase/llm_provider/_subprocess.py`.
- Do NOT refactor the `_wait_until` helper.
- Do NOT touch `test_start_interrupt_monitor_no_op_without_env` (asserts negative state, no race).
- Do NOT touch `test_start_interrupt_monitor_handles_invalid_json` (uses a different `sleep(0.05)` pattern to assert
  terminate was NOT called; different failure mode, not what CI is hitting).

## Validation

1. `just check` passes locally.
2. Run the target test file in a tight loop on Python 3.14
   (`for i in $(seq 1 50); do uv run --python 3.14 python -m pytest tests/test_llm_provider_subprocess.py --no-cov -q; done`)
   → 50/50 pass.
3. CI on the fix branch passes the 3.14 matrix job.
