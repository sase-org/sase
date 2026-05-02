---
create_time: 2026-04-12 17:54:52
status: done
prompt: sdd/prompts/202604/migrate_e2e_tests.md
---

# Plan: Migrate E2E Tests to AcePage Testing DSL

## Problem

The `sase.ace.testing` module provides a Playwright-inspired `AcePage` DSL that eliminates boilerplate in TUI tests. Two
files have been migrated so far (`test_ace_tui_app.py`, one test in `test_ace_tui_widgets.py`), but 8 prompt normal mode
test files (~130 tests) still use raw `app.run_test()` + pilot with identical `_TestApp` boilerplate.

## Design

### Add `PromptPage` DSL to `sase.ace.testing`

A new `PromptPage` class alongside `AcePage` that wraps the `_TestApp` + `PromptTextArea` boilerplate. Every normal mode
test file duplicates this exact pattern:

```python
class _TestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")

async def test_xxx():
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "..."
        ta.cursor_location = (row, col)
        ta._enter_normal_mode()
        await pilot.press(...)
        assert ta.text == "..."
```

`PromptPage` absorbs all of this:

```python
async def test_xxx():
    async with PromptPage("...", cursor=(row, col)) as page:
        await page.press(...)
        assert page.text == "..."
```

API surface:

- `PromptPage(text, cursor, mode)` - constructor; mode defaults to "normal"
- `page.press(*keys)` / `page.pause()` - interaction
- `page.text` / `page.cursor` / `page.mode` - read current state
- `page.ta` - direct PromptTextArea access for edge cases (e.g., `_snippet_tabstops`)

### Not migrating (with rationale)

- **test_prompt_snippet_expansion.py**: Calls `ta._try_expand_snippet()` directly, not keyboard-driven. Unit tests.
- **test_prompt_file_completion.py**: Needs `PromptInputBar` (not just `PromptTextArea`), monkeypatched HOME, and
  private widget state. Would need a separate `InputBarPage` DSL for minimal benefit.
- **test_agent_list_bindings.py**: Custom `_EnterPassthroughApp` for enter passthrough verification. Too specialized.
- **test_update_display_expands_prompt_for_done_workflow_without_diff**: `AgentDetail` widget CSS class assertions.
  Would need a widget-specific page DSL.

## Phases

### Phase 1: Add `PromptPage` to `sase.ace.testing` and add self-tests

Add the `PromptPage` class to `src/sase/ace/testing.py` and add basic self-tests to `tests/test_ace_testing.py` covering
initial state, press, text/cursor/mode properties.

### Phase 2: Migrate `test_prompt_normal_mode_*.py` (8 files, ~130 tests)

Mechanical transformation for each file:

1. Replace `_TestApp` class + imports with `from sase.ace.testing import PromptPage`
2. Replace `app.run_test()` boilerplate with `async with PromptPage(...) as page`
3. Replace `ta.text` / `ta.cursor_location` / `ta._vim_mode` with `page.text` / `page.cursor` / `page.mode`
4. Replace `pilot.press(...)` with `page.press(...)`
5. For tests that need `pilot.pause()`, use `page.pause()`
6. For tests that need direct `ta` access (e.g., `ta._snippet_tabstops`), use `page.ta`

Files: `test_prompt_normal_mode_{delete,change,motions,char_search,text_objects,dot,join,toggle_case}.py`

### Phase 3: Deduplicate `_make_changespec` in `test_ace_tui_widgets.py`

Replace the local `_make_changespec` (lines 23-48) with `make_changespec` imported from `sase.ace.testing` -- they are
identical.
