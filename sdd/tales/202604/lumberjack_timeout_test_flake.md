---
create_time: 2026-04-27 16:50:10
status: done
prompt: sdd/prompts/202604/lumberjack_timeout_test_flake.md
---
# Plan: Fix flaky test `test_per_chop_timeout_overrides_lumberjack_default`

## Problem

`just test tests/test_axe_lumberjack.py` intermittently fails:

```
FAILED tests/test_axe_lumberjack.py::test_per_chop_timeout_overrides_lumberjack_default
assert 30 == 10
  at tests/test_axe_lumberjack.py:509
  assert mock_run.call_args_list[0].kwargs["timeout"] == 10
```

The test passes in isolation (`-k` selecting only it) but fails when run alongside its siblings in the same file.

## Root Cause

The test asserts on **positional** indices of `mock_run.call_args_list`:

```python
# tests/test_axe_lumberjack.py:507-510
assert mock_run.call_count == 2
assert mock_run.call_args_list[0].kwargs["timeout"] == 10  # custom_timeout chop
assert mock_run.call_args_list[1].kwargs["timeout"] == 30  # default_timeout chop
```

But `_run_tick` (`src/sase/axe/lumberjack.py:179-187`) submits each chop to a `ThreadPoolExecutor` and aggregates via
`as_completed`:

```python
with ThreadPoolExecutor() as executor:
    futures = {
        executor.submit(self._run_single_chop, chop, context_file): chop
        for chop in eligible_chops
    }
    for future in as_completed(futures):
        results.append(future.result())
```

The two worker threads each call `run_chop_script` independently, so the order in which the mock records its calls is
determined by thread scheduling — not by `eligible_chops` order. The flake surfaces depending on test load / CPU state.

Concurrent chop execution is intentional (commit
`2c6464b1 feat: Run lumberjack chops concurrently using ThreadPoolExecutor`); the production code is correct.

## Fix

Change the test to be order-independent. Each `run_chop_script` call receives an `env=` kwarg that includes the chop
name via `ENV_CHOP_NAME` (`src/sase/axe/lumberjack.py:334-343`, `_chop_launch_env`). Build a `{chop_name: timeout}` map
from `mock_run.call_args_list` and assert against it.

```python
from sase.axe.chop_agents import ENV_CHOP_NAME

# ...
assert mock_run.call_count == 2
timeouts_by_chop = {
    call.kwargs["env"][ENV_CHOP_NAME]: call.kwargs["timeout"]
    for call in mock_run.call_args_list
}
assert timeouts_by_chop == {"custom_timeout": 10, "default_timeout": 30}
```

## Audit of sibling tests

`test_timeout_expired_records_error_and_continues` (`tests/test_axe_lumberjack.py:450-478`) uses an ordered
`side_effect` list (`[TimeoutExpired, _ok_result()]`), but its assertions check only totals (`errors_encountered == 1`,
`chops_executed == 1`). Both possible call orderings yield the same totals, so it is safe and **does not need changes**.

A quick scan of the other tests in this file should confirm no other order-dependent positional assertions on
`mock_run.call_args_list` exist; if any are found, apply the same `chop_name`-keyed pattern.

## Out of scope

- No changes to production code. `ThreadPoolExecutor` use in `_run_tick` is intentional.
- No changes to `_chop_launch_env` env contract.

## Verification

1. Run the targeted file repeatedly to confirm the flake is gone:
   ```bash
   for i in 1 2 3 4 5; do just test tests/test_axe_lumberjack.py || break; done
   ```
2. `just check` — full lint + type + test gate.
