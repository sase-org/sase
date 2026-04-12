# End-to-End Testing

## `AcePage` Testing DSL (recommended)

The `sase.ace.testing` module provides a Playwright-inspired async DSL for writing TUI tests. Use `AcePage` as an async
context manager — it handles app lifecycle, changespec mocking, and pilot management.

```python
from sase.ace.testing import AcePage, make_changespec

async def test_navigation():
    async with AcePage() as page:
        await page.expect_state("idx", 0)
        await page.press("j")
        await page.expect_state("idx", 1)

async def test_modal_open_close():
    async with AcePage() as page:
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        await page.press("escape")
        await page.expect_no_modal()

async def test_custom_changespecs():
    specs = [make_changespec(name="a"), make_changespec(name="b")]
    async with AcePage(query='"a"', changespecs=specs) as page:
        await page.expect_state("total", 2)
```

### Key APIs

- **`AcePage(query, size, changespecs, model_tier_override)`** — constructor; defaults to 3 test changespecs
- **`page.press(*keys)`** / **`page.click(selector)`** — interaction
- **`page.state`** / **`page.screen`** — read current TUI state dict or screen text
- **`page.app`** — access the underlying `AceApp` for direct widget queries
- **`page.expect_state(key, value)`** — auto-retry assertion; supports dot-notation (e.g., `"selected.name"`)
- **`page.expect_modal(name)`** / **`page.expect_no_modal()`** — modal assertions
- **`page.expect_screen_contains(text)`** / **`page.expect_screen_not_contains(text)`** — screen text assertions
- **`page.wait_for(predicate)`** — generic polling with a `lambda state: bool` predicate

### Direct widget access via `page.app`

For things the DSL doesn't cover (e.g., inspecting specific widgets), use `page.app`:

```python
from textual.widgets import Input

async def test_modal_input_widget():
    async with AcePage() as page:
        await page.press("slash")
        modal = page.app.screen_stack[-1]
        input_widget = modal.query_one("#query-input", Input)
        input_widget.value = '"new_query"'
        await page.click("#apply")
        assert page.state["query"] == '"new_query"'
```

## `sase ace --agent` CLI (headless JSON)

The `sase ace --agent` command runs the TUI headlessly and returns structured JSON output. Use `--keys` to send
keystrokes and `--size` to control terminal dimensions. Useful for quick one-shot checks from the shell.

```bash
# See initial TUI state
sase ace --agent

# Navigate down two items
sase ace --agent --keys j j

# Open query modal
sase ace --agent --keys slash

# Switch to agents tab
sase ace --agent --keys tab

# Custom terminal size
sase ace --agent --size 200x50 --keys j
```
