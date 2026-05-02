---
create_time: 2026-04-24 22:48:36
status: done
prompt: sdd/prompts/202604/fix_debounced_detail_shutdown_race.md
---
# Fix `test_query_edit_modal_invalid_query` Shutdown Race (Deferred Timer Path)

## Problem

CI intermittently fails with:

```
FAILED tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query
  textual.css.query.NoMatches: No nodes match '#agent-detail-panel' on Screen(id='_default')
============ 1 failed, 4660 passed, 8 skipped in 114.14s ============
```

The test passes in isolation (≈10s). Under the full parallel suite it races. A prior fix
(`plans/202604/fix_ace_worker_shutdown_race.md`, status: done) guarded `_refresh_agents_display` against the same class
of race for `#agent-list-panel`. The remaining unguarded site is the timer-deferred follow-up.

## Root Cause

Same root shutdown race, different code path:

1. `AcePage` boots `AceApp` with `query='"valid"'`. The mock changespec is named `test_feature`, so the filtered list is
   empty and `actions/startup.py` falls back to `current_tab = "agents"`.
2. `_start_post_mount_background_loads` schedules `_run_agents_async_refresh` as a Textual worker.
3. The worker awaits real disk I/O (`load_agents_from_disk` reads the real `~/.sase/` tree — only `find_all_changespecs`
   is mocked).
4. When I/O returns, `_apply_loaded_agents` → `_finalize_agent_list` → `_refresh_agents_display(..., defer_detail=True)`
   runs (`actions/agents/_loading.py:582-584`).
5. `_refresh_agents_display` is now guarded (the previous fix), but its `defer_detail=True` branch schedules
   `self._detail_update_timer = self.set_timer(0.15, self._fire_debounced_detail_update)`
   (`actions/agents/_display.py:161-162`).
6. The test body exercises the modal in ~3s and exits before the 150 ms timer ticks — or the timer fires during
   `app._shutdown()` as widgets unmount.
7. `_fire_debounced_detail_update` (`actions/agents/_display.py:212-220`) calls
   `self.query_one("#agent-detail-panel", AgentDetail)` and `self.query_one("#keybinding-footer", KeybindingFooter)`
   with **no try/except**. The detail panel lookup raises `NoMatches`. Textual surfaces it from `app.run_test()`'s
   teardown and fails the test.

The previous fix stopped the race on the immediate path; it didn't cover the deferred path it spawns.

## Fix

In `src/sase/ace/tui/actions/agents/_display.py`, guard the widget lookups in `_fire_debounced_detail_update`
identically to the guard already in `_refresh_agents_display`:

```python
def _fire_debounced_detail_update(self) -> None:
    from textual.css.query import NoMatches
    from ...widgets import AgentDetail, KeybindingFooter

    self._detail_update_timer = None

    try:
        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)
    except NoMatches:
        log.debug("debounced detail update skipped: widget tree unavailable")
        return

    self._apply_agent_detail_update(agent_detail, footer_widget)
```

Rationale for the scope of the guard (matching the prior plan's reasoning):

- Both widgets are unconditionally yielded by `compose()`; a `NoMatches` here is only possible when the widget tree is
  gone. The guard cannot mask a real bug.
- Centralising the guard in the timer callback is cheaper than auditing every `set_timer` caller of this function.
- Mirrors the existing "UI-touching code wraps `query_one`" convention in this file.

## Out of Scope

- The second debounced path, `_refresh_agents_display_debounced` (`_display.py:178` onwards), has similar unguarded
  `query_one` calls for `#pinned-list-panel` / `#agent-list-panel`. It is only invoked from j/k navigation on the agents
  tab — not triggered by this test. Leaving it alone keeps the change minimal and focused on the reported failure. If a
  future flake points at those IDs, apply the same guard pattern.
- The broader issue that `AcePage`-based tests touch the real `~/.sase/` filesystem (only `find_all_changespecs` is
  mocked) — same as the prior plan's out-of-scope note. Fixing this would require a larger fixture refactor than this
  bug warrants.
- The startup fallback that flips the tab to `"agents"` when no changespecs match is intentional product behaviour; the
  test just happens to trigger it.

## Validation

1. Run `tests/test_ace_tui_app.py::test_query_edit_modal_invalid_query` in isolation — should still pass.
2. Run `just test` repeatedly (≥10 iterations under the parallel `-n auto --dist=loadfile` config) — the `NoMatches` on
   `#agent-detail-panel` during shutdown should not recur.
3. `just check` — lint/type/keep-sorted gates stay green.
