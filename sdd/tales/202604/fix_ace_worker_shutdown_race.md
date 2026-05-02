---
create_time: 2026-04-24 20:36:08
status: done
prompt: sdd/prompts/202604/fix_ace_worker_shutdown_race.md
---
# Fix `test_query_edit_modal_invalid_query` Worker Shutdown Race

## Problem

`just test` fails intermittently with:

```
FAILED tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query
  textual.worker.WorkerFailed: Worker raised exception:
  NoMatches("No nodes match '#agent-list-panel' on Screen(id='_default')")
```

The test passes in isolation; it only fails roughly 1 in ~6 runs of the full suite (parallel via
`pytest -n auto --dist=loadfile`).

## Root Cause

The trace pinpoints a shutdown race in the agents async refresh worker:

1. `AcePage` starts `AceApp` with `query='"valid"'`. The mock changespec is named `test_feature`, so the filtered list
   is empty.
2. `actions/startup.py:371-373` falls back to `self.current_tab = "agents"` when no changespecs match and no saved query
   rescues the search.
3. `_start_post_mount_background_loads` schedules `_run_agents_async_refresh` as a Textual worker.
4. The worker awaits `asyncio.to_thread(load_agents_from_disk, ...)`. Crucially, `load_agents_from_disk` reads the
   **real** `~/.sase/` tree — only `find_all_changespecs` is mocked by `AcePage`. With many real agents on disk, that
   I/O often outlives the short test body.
5. The test exercises the modal in ~3s and exits; `app._shutdown()` begins, widgets unmount.
6. The worker resumes after disk I/O. `_load_agents_async` sees `current_tab == "agents"` so `on_agents_tab` is `True`
   and `_apply_loaded_agents` → `_finalize_agent_list` → `_refresh_agents_display` runs. The first
   `query_one("#agent-list-panel", AgentList)` raises `NoMatches` because the widget tree has been torn down.
7. The unhandled exception flips the worker to `ERROR`, and Textual re-raises it from `app.run_test()`'s `finally`
   block, failing the test.

`_apply_loaded_agents` and `_finalize_agent_list` already wrap their direct `query_one` calls in try/except (see
`_loading.py:217-228` for `#agent-list-panel`/`#pinned-list-panel` loading flags and `_loading.py:561-571` for
`#tab-bar`). The display refresh is the one path that escapes the convention.

## Fix

Wrap the `query_one` block at the top of `_refresh_agents_display` (`actions/agents/_display.py:78-81`) in a try/except
so a vanished widget tree returns early instead of bubbling out. Specifically: if any of the four panel lookups
(`#agent-list-panel`, `#pinned-list-panel`, `#agent-detail-panel`, `#keybinding-footer`) raises `NoMatches`, log at
debug and return.

Why guard inside `_refresh_agents_display` rather than only the worker call site:

- It is invoked from many paths (timer ticks, watchers, navigation). Any of these can in principle fire after shutdown
  begins; centralising the guard is cheaper than auditing every caller.
- The existing convention in this file is "UI-touching code wraps query_one"; this just brings the display refresh in
  line.
- `NoMatches` from a destroyed widget tree is the _only_ failure mode of those four lookups; the widgets are
  unconditionally yielded by `compose()`. So the guard cannot mask a real bug — under normal app state these lookups
  always succeed.

## Validation

1. Run `just test` repeatedly (10+ iterations); the failure should not recur. Previously it surfaced ~1 run in 6.
2. Run `tests/test_ace_tui_app.py` in isolation — should still pass and exercise the modal logic.
3. `just check` to confirm lint/type/keep-sorted gates stay green.

## Out of Scope

- The wider issue that `AcePage`-based tests touch the real `~/.sase/` filesystem (only `find_all_changespecs` is
  mocked). This is the underlying reason the race window is wide. Fixing it would require mocking
  `load_agents_from_disk`/the dismissed-bundles directory across the test fixture, which is a larger refactor than this
  bug warrants.
- The startup fallback that flips the tab to "agents" when no changespecs match. That is intentional product behaviour;
  the test just happens to trigger it. We are not changing the test query or the fallback.
