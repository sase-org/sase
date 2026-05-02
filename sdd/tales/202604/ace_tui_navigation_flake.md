---
create_time: 2026-04-24 10:22:56
status: done
---
# SASE Plan: Stabilize Ace TUI navigation key test under parallel load

## Context

`just check` fails with:

- `tests/test_ace_tui_app.py::test_navigation_next_key`
- observed assertion: `idx` remains `0` immediately after `await page.press("j")`

Investigation findings:

- Running `tests/test_ace_tui_app.py` alone passes.
- Running the single failing test repeatedly in isolation passes consistently.
- Full-suite failure is order/process dependent and appears in xdist load, indicating a race/timing issue in test
  observation rather than deterministic functional breakage of `action_next_changespec`.
- The test asserts state immediately after keypress; other TUI tests use `expect_state(...)` polling to account for
  async event handling.

## Root-cause hypothesis

The failing test is timing-sensitive: under heavier parallel test load, the key event may not be fully processed at the
instant of immediate state assertion.

## Plan

1. Update navigation assertions in `tests/test_ace_tui_app.py` to use `await page.expect_state("idx", <expected>)` after
   each keypress instead of immediate `assert page.state["idx"] == <expected>`.
2. Keep test intent unchanged (same key sequence and expected positions), only improve synchronization with the async UI
   event loop.
3. Re-run targeted tests:
   - `tests/test_ace_tui_app.py::test_navigation_next_key`
   - `tests/test_ace_tui_app.py`
4. Re-run `just check` to confirm the suite is green.
5. If failures persist, collect the neighboring test file order in failing workers and add scoped diagnostics around
   keymap/action dispatch for deeper isolation.
