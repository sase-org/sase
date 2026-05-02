---
create_time: 2026-04-12 16:37:07
status: done
bead_id: sase-i
prompt: sdd/prompts/202604/ace_testing_dsl.md
---

# Plan: Implement `sase.ace.testing` — Playwright-Inspired TUI Testing DSL

## Goal

Create a `sase.ace.testing` module that provides a Playwright-inspired Python API for testing the `sase ace` TUI. This
wraps the existing Textual Pilot API with auto-retrying assertions, mock helpers, and fluent interaction methods —
eliminating the boilerplate in current tests while keeping them in-process and fast.

## Key Design Decisions

1. **`AcePage` wraps the Pilot directly, not `run_agent_mode()`**. The existing `test_ace_tui_app.py` tests show the
   pattern: `AceApp(...).run_test()` gives a Pilot, then you call `pilot.press()` and inspect `app.*` properties. The
   DSL should wrap this same pattern, not the JSON-serializing `run_agent_mode()` function. The `_extract_state()` and
   `_capture_screen()` helpers from `agent_runner.py` will be reused for the `state` and `screen` properties.

2. **Reuse `_make_changespec` and `_patch_changespecs` from test files**. Both `test_agent_runner.py` and
   `test_ace_tui_app.py` define identical `_make_changespec()` factories and similar patching patterns. The DSL should
   export a shared `make_changespec()` factory and integrate the patching into `AcePage`.

3. **Auto-retry assertions poll `_extract_state()` / `_capture_screen()`** in a loop with configurable timeout and
   interval, similar to Playwright's `expect()` semantics. This avoids timing issues without requiring explicit
   `await pilot.pause()` calls.

4. **Module location**: `src/sase/ace/testing.py` — a single file alongside `agent_runner.py` in the `sase.ace` package.
   At ~150-200 lines, a single module is appropriate.

## Phases

### Phase 1: Core `AcePage` class with lifecycle, interaction, and state access

**Files to create:**

- `src/sase/ace/testing.py`

**What to implement:**

- `make_changespec()` — public factory function (extracted from duplicated test helpers)
- `DEFAULT_CHANGESPECS` — pre-built list of 3 test ChangeSpecs (replaces per-file `MOCK_CHANGESPECS`)
- `AcePage` async context manager class:
  - Constructor: `query`, `size`, `changespecs` (defaults to `DEFAULT_CHANGESPECS`), `model_tier_override`
  - `__aenter__` / `__aexit__` — creates `AceApp(query=..., refresh_interval=0)`, patches `find_all_changespecs`, enters
    `app.run_test(size=size)`, stores the pilot
  - `press(*keys)` — delegates to `pilot.press()`
  - `click(selector)` — delegates to `pilot.click()`
  - `state` property — calls `_extract_state(app)` from `agent_runner.py`
  - `screen` property — calls `_capture_screen(app, height)` from `agent_runner.py`
  - `app` property — exposes the underlying `AceApp` for direct access when needed
  - `query_widget(selector)` / `query_one_widget(selector)` — delegates to `app.query()` / `app.query_one()`

**Refactoring in `agent_runner.py`:**

- Make `_extract_state()`, `_capture_screen()`, and `_get_modal_name()` public (remove leading underscore) so
  `testing.py` can import them. Update `run_agent_mode()` to use the new names.

**Tests to write** (in `tests/test_ace_testing.py`):

- `test_ace_page_initial_state` — verify `page.state` returns expected dict after entering context
- `test_ace_page_press` — verify `page.press("j")` changes `page.state["idx"]`
- `test_ace_page_screen` — verify `page.screen` returns non-empty string
- `test_ace_page_custom_changespecs` — verify passing custom changespecs works

**Verification:** `just check` passes.

---

### Phase 2: Auto-retry assertions and wait conditions

**Files to modify:**

- `src/sase/ace/testing.py`

**What to implement:**

- `expect_state(key, value, *, timeout=2.0, interval=0.05)` — polls `_extract_state()`, retries until
  `state[key] == value` or timeout. Supports dot-notation for nested keys (e.g., `"selected.name"`). Raises
  `AssertionError` with descriptive message on timeout.
- `expect_modal(name, *, timeout=2.0)` — sugar for `expect_state("modal", name)`
- `expect_no_modal(*, timeout=2.0)` — sugar for `expect_state("modal", None)`
- `expect_screen_contains(text, *, timeout=2.0)` — polls `_capture_screen()`, retries until `text in screen`
- `expect_screen_not_contains(text, *, timeout=2.0)` — inverse of above
- `wait_for(predicate, *, timeout=2.0, interval=0.05)` — generic polling: `predicate(state)` returns bool

The retry loop should call `await pilot.pause()` between attempts to let Textual process pending events.

**Tests to write** (append to `tests/test_ace_testing.py`):

- `test_expect_state_passes` — immediate match succeeds
- `test_expect_state_fails_on_timeout` — wrong value raises `AssertionError`
- `test_expect_state_nested_key` — dot-notation like `"selected.name"` works
- `test_expect_modal` — press slash, `expect_modal("QueryEditModal")` succeeds
- `test_expect_no_modal` — initial state, `expect_no_modal()` succeeds
- `test_expect_screen_contains` — verify screen text assertion works
- `test_wait_for` — custom predicate that checks `state["total"] > 0`

**Verification:** `just check` passes.

---

### Phase 3: Migrate existing tests to use the DSL

**Files to modify:**

- `tests/test_agent_runner.py` — rewrite tests using `AcePage`
- `tests/test_ace_tui_app.py` — rewrite tests using `AcePage`

**Migration approach:**

`test_agent_runner.py` before:

```python
async def test_slash_opens_query_modal():
    with _patch_changespecs():
        result = json.loads(await run_agent_mode(query='"feature"', keys=["slash"]))
    assert result["error"] is None
    assert result["state"]["modal"] == "QueryEditModal"
```

After:

```python
async def test_slash_opens_query_modal():
    async with AcePage(query='"feature"') as page:
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
```

`test_ace_tui_app.py` before:

```python
async def test_navigation_next_key():
    mock_changespecs = [...]
    with patch("sase.ace.changespec.find_all_changespecs", return_value=mock_changespecs):
        app = AceApp(query='"feature"', refresh_interval=0)
        async with app.run_test() as pilot:
            assert app.current_idx == 0
            await pilot.press("j")
            assert app.current_idx == 1
```

After:

```python
async def test_navigation_next_key():
    async with AcePage(query='"feature"') as page:
        await page.expect_state("idx", 0)
        await page.press("j")
        await page.expect_state("idx", 1)
```

**What to clean up:**

- Remove `_make_changespec()` and `_patch_changespecs()` from both test files (now in `sase.ace.testing`)
- Remove `MOCK_CHANGESPECS` from `test_agent_runner.py`
- Remove `json` imports and JSON parsing from `test_agent_runner.py`
- Keep direct `app` access tests in `test_ace_tui_app.py` where they test things the DSL doesn't cover (e.g.,
  `app.screen_stack`, `app.query_one("#query-input", Input)`) — use `page.app` for those

**Verification:** `just check` passes. All existing test behavior is preserved.

---

### Phase 4: Update documentation and memory

**Files to modify:**

- `memory/e2e_testing.md` — update to document both the `--agent` CLI and the new `AcePage` testing DSL, with examples
  showing the recommended pattern for writing TUI tests

**Verification:** `just check` passes.
