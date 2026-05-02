---
create_time: 2026-04-27 09:25:54
status: done
prompt: sdd/prompts/202604/fix_changespec_norow_norefresh_flake.md
---
# SASE Plan: Fix `test_navigation_next_key` `NoMatches` flake on `#list-panel`

## Context

CI run failed in `just test-cov`:

```
FAILED tests/test_ace_tui_app.py::test_navigation_next_key
  - textual.css.query.NoMatches: No nodes match '#list-panel' on Screen(id='_default')
====== 1 failed, 5287 passed, 8 skipped, 14 warnings in 127.09s ======
```

Local repeated runs of the test in isolation pass — this is a load-dependent flake under xdist parallel execution,
surfacing only intermittently.

A prior fix (commit `c3fd7b54`) softened immediate `assert page.state["idx"] == N` into
`await page.expect_state("idx", N)` polling. That made the test wait longer, which lets the more recently-introduced
0.15s debouncer (commit `e44715f2`) tick and exposes a real production-code bug.

## Root cause

Every reference to `#list-panel` in production code lives in `src/sase/ace/tui/actions/changespec.py`:

- `_refresh_changespecs_display_debounced` at line 484 — has a `try/except NoMatches` guard, but its fallback path is
  buggy.
- `_refresh_display` at line 510 — **no guard at all**.

Press flow on `j`:

1. `action_next_changespec` (`src/sase/ace/tui/actions/navigation/_basic.py:83`) increments `current_idx`.
2. `watch_current_idx` (`src/sase/ace/tui/app.py:262`) calls `_refresh_changespecs_display_debounced()`.
3. That schedules `_refresh_display` via `DetailPanelDebouncer.schedule(...)` to fire 0.15s later
   (`src/sase/ace/tui/util/debounce.py`).

There are two distinct ways the bare `query_one("#list-panel", …)` can raise `NoMatches` and fail the test:

1. **The except branch is itself broken.** When the immediate query in `_refresh_changespecs_display_debounced` raises
   `NoMatches`, the handler does:

   ```python
   except NoMatches:
       self._changespec_detail_debouncer.cancel()
       self._refresh_display()   # ← runs the *same* query, will raise again
       return
   ```

   So the "fallback full-refresh" actively re-raises the exact error the guard was supposed to swallow.

2. **The 0.15 s debounce timer can fire after the widget tree changes.** The timer fires asynchronously, possibly during
   teardown, modal transitions, or any transient state where `app.screen.query_one("#list-panel", ChangeSpecList)` has
   nothing to match. The unguarded `_refresh_display` then raises.

The agents tab already solved this correctly: `_fire_debounced_detail_update` in
`src/sase/ace/tui/actions/agents/_display.py:231` wraps its queries in `try/except NoMatches` and silently returns.
`_refresh_agents_display` at lines 90–95 does the same. The changespec tab simply hasn't been brought up to that
pattern.

## Plan

All edits in **`src/sase/ace/tui/actions/changespec.py`**:

1. **Fix the broken fallback in `_refresh_changespecs_display_debounced`.** When `query_one("#list-panel", …)` raises
   `NoMatches`, cancel any pending debounce and `return` instead of calling `_refresh_display()`. Add a
   `logging.getLogger(__name__)` debug log line for diagnostics, mirroring `_fire_debounced_detail_update`
   (`src/sase/ace/tui/actions/agents/_display.py:240-242`).

2. **Guard `_refresh_display` itself.** Wrap the five `query_one` calls at lines 510–516 in a single
   `try/except NoMatches` block. On miss, log at debug and return. This protects the function whether it's called
   synchronously by other actions, by the 0.15 s debounce timer, or during teardown / modal swap — matching the pattern
   at `src/sase/ace/tui/actions/agents/_display.py:90-95`.

3. **No test changes.** `test_navigation_next_key` already uses `expect_state` polling; the production fix makes the
   debounced refresh path resilient regardless of test pacing.

## Verification

1. `just test tests/test_ace_tui_app.py::test_navigation_next_key` — targeted test still passes.
2. `just test tests/test_ace_tui_app.py` — whole TUI test file passes.
3. `just check` — full format/lint/mypy/coverage gate stays green.

## Risk

Very low. Both edits are defensive `try/except` additions following the established pattern in the agents-tab refresh
path, with no behavioural change on the happy path. There is no API change.
