---
create_time: 2026-04-24 15:52:36
status: done
---
# Fix `#tab-bar` WorkerFailed flake in `test_expect_state_passes`

## Problem

CI run of `just test-cov` intermittently fails with:

```
FAILED tests/test_ace_testing.py::test_expect_state_passes
  textual.worker.WorkerFailed: Worker raised exception:
  NoMatches("No nodes match '#tab-bar' on Screen(id='_default')")
```

Locally the test passes consistently (10/10 runs, plus stress-parallel runs). The failure surfaced after commit
`b44f123c` ("fix: run startup axe init concurrently with agents refresh"), which changed `AceApp.on_mount` to schedule
post-mount background loads via `run_worker(...)` instead of `call_after_refresh(...)`.

## Root cause

`AceApp.on_mount` now dispatches the post-mount loads through a one-shot launcher:

```python
# src/sase/ace/tui/app.py
def _start_post_mount_background_loads(self) -> None:
    ...
    self.run_worker(cast(Any, self._run_agents_async_refresh), thread=False, ...)
    self.run_worker(cast(Any, self._run_axe_startup_init), thread=False, ...)
```

`run_worker` wraps execution in a textual `Worker`. Unlike `call_after_refresh` (whose unhandled exceptions are logged
inside the message pump), a worker that raises surfaces the exception as `WorkerFailed`, which propagates into
`run_test` and fails the enclosing pytest case.

The agents worker path is:

`_run_agents_async_refresh` → `_load_agents_async` → `await asyncio.to_thread(load_agents_from_disk, ...)` →
`_apply_loaded_agents` → `_finalize_agent_list`

and at `src/sase/ace/tui/actions/agents/_loading.py:528-537` it contains an **unguarded** widget lookup:

```python
from ...widgets import TabBar

tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
tab_bar.update_agents_count(
    manual_running,
    hidden_running,
    show_hidden=not self.hide_non_run_agents,
    done_count=done_visible,
    pinned_count=pinned_visible,
)
```

In the failing test body:

```python
async with AcePage() as page:
    await page.expect_state("idx", 0)
    await page.expect_state("total", 3)
    await page.expect_state("tab", "changespecs")
```

every `expect_state` call matches on its first iteration and returns **without yielding to the event loop** (no
`pilot.pause()`). So the test body exits before the startup workers have a chance to run. `AcePage.__aexit__` then
invokes `pilot_cm.__aexit__` which drives app shutdown.

During the shutdown window, the already-scheduled agents worker begins executing, suspends in `asyncio.to_thread(...)`,
and resumes after the app has started unmounting widgets. The unguarded `self.query_one("#tab-bar", TabBar)` raises
`NoMatches`, the worker dies, `WorkerFailed` propagates, and the test is marked FAILED. CI-level load widens the race
window; fast local machines almost always win the race.

Every other `#tab-bar` lookup reachable from background / refresh paths already guards the query with
`try/except Exception: pass`:

- `src/sase/ace/tui/actions/changespec.py:453-463`
- `src/sase/ace/tui/actions/axe_display/_loaders.py:316-325`
- `src/sase/ace/tui/app.py` `_apply_startup_loading_state` (lines ~642-646)

The agents `_finalize_agent_list` site is the lone outlier.

## Fix

Wrap the `TabBar` lookup and its `update_agents_count(...)` call in `_finalize_agent_list` with the same
`try/except Exception: pass` guard used at every other `#tab-bar` call site. This is the narrowest change that
eliminates the flake, keeps the established teardown-resilience pattern consistent across the file set, and does not
touch startup timing or worker scheduling.

### Files to change

- `src/sase/ace/tui/actions/agents/_loading.py`
  - Wrap the block that queries `#tab-bar`
    (`from ...widgets import TabBar; tab_bar = self.query_one(...); tab_bar.update_agents_count(...)`) in
    `try/except Exception: pass`.

### Non-goals

- Do **not** change the `run_worker` scheduling in `_start_post_mount_background_loads` — concurrent agents/axe startup
  is intentional (see commit `b44f123c`).
- Do **not** add a new regression test: the race requires CI-level timing to reproduce, and the fix is a mechanical
  application of an existing codebase convention.
- Do **not** expand the guard to other unrelated `query_one` calls in `_finalize_agent_list` that already fall inside
  existing `try/except` blocks or are benign.

## Verification

- `just test tests/test_ace_testing.py` passes.
- `just check` passes (ruff + mypy + tests).
- Manual sanity: run `sase ace` interactively and confirm the agents tab badge still updates on the first background
  agent load (guard still runs the update on the happy path; only failures during teardown are swallowed).
