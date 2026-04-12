# TUI End-to-End Testing for Agents

## Problem Statement

Agents making changes to sase's TUI (`sase ace`) need a way to verify their changes work correctly. The current
`sase ace --agent` command provides basic headless execution with JSON output, but the testing experience is far from
Playwright-level. Key gaps:

1. **One-shot execution** -- each invocation boots the app, presses keys, captures state, and exits. There's no
   persistent session for multi-step interactions.
2. **No assertions API** -- agents must parse raw JSON and write manual `assert` statements. No auto-retrying, no
   semantic matchers, no fluent `expect()` chains.
3. **No widget selectors** -- you can check `state["modal"]` or `state["idx"]`, but can't query arbitrary widgets by CSS
   selector, ID, or content.
4. **No wait conditions** -- if a key triggers an async operation, there's no way to wait for it to complete before
   capturing state.
5. **No screen region queries** -- the `screen` field is a single giant string. Finding specific text in context
   requires string parsing.
6. **Boilerplate-heavy test setup** -- every test needs `_patch_changespecs()`, JSON parsing, error checking. See
   `tests/test_agent_runner.py` for the pattern.

## Current State

### `sase ace --agent` (agent_runner.py)

```python
async def run_agent_mode(query, keys=None, size=(120, 40)) -> str:
    app = AceApp(query=query, ...)
    async with app.run_test(size=size) as pilot:
        if keys:
            await pilot.press(*keys)
        screen = _capture_screen(app, size[1])
        state = _extract_state(app)
        return json.dumps({"screen": screen, "state": state, "error": None})
```

Returns JSON with three keys:

- `screen`: plain text rendering of the terminal
- `state`: structured dict of reactive properties (tab, idx, modal, selected, etc.)
- `error`: null or error string

### Current test pattern (test_agent_runner.py)

```python
async def test_slash_opens_query_modal():
    with _patch_changespecs():
        result = json.loads(await run_agent_mode(query='"feature"', keys=["slash"]))
    assert result["error"] is None
    assert result["state"]["modal"] == "QueryEditModal"
```

This works but is verbose and requires the agent to understand the JSON schema, mock setup, and assertion patterns from
scratch every time.

## Prior Art

### 1. Textual Pilot API (what we already use)

The foundation of `sase ace --agent`. Textual's `app.run_test()` returns a `Pilot` with `press()`, `click()`, `pause()`.
Combined with `app.query()` / `app.query_one()` for CSS selectors on the widget tree.

- **Pros**: In-process, fast, full access to app internals, no external deps.
- **Cons**: No auto-wait, no fluent assertions, no session persistence.

### 2. Microsoft tui-test (TypeScript)

Playwright-inspired TUI testing framework from Microsoft. Runs apps in a real PTY and provides locators, matchers
(`toBeVisible()`, `toMatchSnapshot()`), auto-wait, and trace recording.

- **Pros**: Closest to "Playwright for TUIs" from a major vendor. Auto-wait and retry semantics.
- **Cons**: Node.js/TypeScript -- not native to our Python stack. PTY-based (slower, black-box only).

### 3. Termwright (Rust)

Daemon that wraps any TUI in a PTY and exposes a JSON-RPC API. Designed for AI agent interaction. Supports persistent
sessions, wait conditions, screen reading, keyboard input.

- **Pros**: Persistent sessions, daemon model, explicitly AI-agent-focused.
- **Cons**: External Rust binary. Black-box only (no widget state access).

### 4. agent-tui (Rust + npm)

CLI tool for AI agents: `agent-tui screenshot`, `agent-tui press`, `agent-tui type`, `agent-tui wait`. Virtual terminal
emulation, session management, JSON output.

- **Pros**: Purpose-built for LLM agents. Simple CLI interface.
- **Cons**: External dependency. Black-box. Redundant with our Pilot-based approach that exposes internal state.

### 5. pytest-textual-snapshot

Official Textual pytest plugin. Renders app to SVG, diffs against saved snapshot. HTML report for visual comparison.

- **Pros**: Catches visual regressions.
- **Cons**: SVG diffs are fragile; any cosmetic change breaks them. Not useful for agents that can't visually judge
  diffs.

### 6. pexpect (classic Python)

Spawn process in PTY, `expect()` patterns, `send()` input. Mature (20+ years).

- **Pros**: Works with any terminal app. Pure Python.
- **Cons**: Pattern-matching on raw terminal output is fragile. No widget awareness. Poor for full-screen TUIs.

### 7. Ratatui layered testing (Rust ecosystem)

Layered approach: in-memory backend for unit tests, PTY for integration tests, `insta` snapshot library for regression
detection.

- **Key insight**: The layered architecture pattern (fast in-process tests + optional PTY integration tests + optional
  snapshots) is worth emulating regardless of language.

## Alternative Solutions

### Option A: `sase ace --agent` v2 (Enhanced CLI)

Extend the existing CLI with richer subcommands, making it more like a testing toolkit that agents call via shell
commands.

**New subcommands:**

```bash
# Multi-step session (keeps app alive between commands)
sase ace --agent session start --query '"feature"'    # returns session-id
sase ace --agent session press j j enter --id <sid>   # press keys, return state
sase ace --agent session query "#my-widget" --id <sid> # CSS query on widget tree
sase ace --agent session wait --text "Ready" --id <sid> # wait for text to appear
sase ace --agent session stop --id <sid>

# Built-in assertions (exit code 0/1)
sase ace --agent assert --state "modal==QueryEditModal" --keys slash
sase ace --agent assert --screen-contains "feature_a"
```

**Pros:**

- Agents already know how to call shell commands -- no new paradigm.
- Persistent sessions solve the one-shot problem.
- Built-in assertions reduce boilerplate.

**Cons:**

- Shell-command-per-interaction is slow (process startup overhead per call).
- Complex assertion DSL is hard to get right.
- Session management in a CLI is awkward (background process, IPC).

### Option B: Python Testing DSL (`sase.ace.testing` module)

A Playwright-inspired Python module that agents use when writing pytest tests. Wraps the Pilot API with auto-waiting,
selectors, and fluent assertions.

```python
from sase.ace.testing import AcePage

async def test_navigate_and_open_modal():
    async with AcePage(query='"feature"') as page:
        # Fluent assertions with auto-retry
        await page.expect_state("idx", 0)
        await page.expect_state("tab", "changespecs")
        await page.expect_screen_contains("feature_a")

        # Press keys and assert
        await page.press("j")
        await page.expect_state("idx", 1)

        # Widget selectors (wrapping Textual CSS queries)
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        modal = await page.query_one("QueryEditModal")
        assert modal is not None

        # Wait for async operations
        await page.wait_for(lambda s: s["total"] > 0, timeout=5.0)

        # Screen region assertions
        await page.expect_screen_line_contains(0, "sase ace")  # header
```

**Key features:**

- `AcePage` context manager handles app lifecycle, mocking, and cleanup.
- `expect_*` methods auto-retry with configurable timeout (like Playwright).
- `press()`, `click()` delegate to Pilot.
- `query()` / `query_one()` expose Textual CSS selectors.
- `wait_for(predicate)` polls state until condition met.
- Built-in mock helpers (`page.with_changespecs([...])`) eliminate boilerplate.
- Returns structured state dict -- agents parse Python dicts, not JSON strings.

**Pros:**

- Playwright-like API that agents can learn once and use everywhere.
- In-process (fast, full widget access).
- Auto-retry assertions eliminate timing issues.
- Python-native -- agents write pytest tests, which they already know how to do.
- Composable -- complex multi-step test scenarios are natural.

**Cons:**

- Agents must write Python test files (but they already do this).
- New abstraction layer to maintain.
- Must stay in sync with underlying app state schema.

### Option C: Declarative YAML Test Specs

Define tests as YAML files that a test runner interprets. Agents write YAML instead of Python.

```yaml
name: Navigate and open modal
query: '"feature"'
steps:
  - assert:
      state.idx: 0
      state.tab: changespecs
      screen_contains: feature_a
  - press: [j]
  - assert:
      state.idx: 1
  - press: [slash]
  - assert:
      state.modal: QueryEditModal
  - wait_for:
      state.total: { gt: 0 }
      timeout: 5
```

```bash
sase ace test run tests/tui/test_navigate.yml
```

**Pros:**

- Extremely simple for agents -- just write YAML.
- No Python boilerplate at all.
- Easy to validate, lint, and generate.
- Could support test recording: run `sase ace --record` to capture a YAML test from manual interaction.

**Cons:**

- YAML DSL is inherently limited -- conditional logic, loops, and custom assertions are hard.
- Yet another DSL to design and maintain.
- Less flexible than Python for complex test scenarios.
- Agents are already good at writing Python; the YAML doesn't save much cognitive overhead.

### Option D: Hybrid -- Python DSL + CLI shortcuts

Combine Option B (Python DSL for writing tests) with lightweight CLI enhancements for quick one-off checks.

**Python side** (`sase.ace.testing`):

```python
async with AcePage(query='"feature"') as page:
    await page.press("j")
    await page.expect_state("idx", 1)
```

**CLI side** (for quick agent checks without writing a test file):

```bash
# Quick state check (enhanced --agent output with jq-friendly paths)
sase ace --agent --keys j --assert "state.idx==1"

# Screen content check
sase ace --agent --keys slash --assert "state.modal==QueryEditModal"
```

The CLI `--assert` flag is syntactic sugar that saves writing a full test file for simple verifications. Complex
multi-step tests use the Python DSL.

**Pros:**

- Best of both worlds: quick CLI checks + powerful Python tests.
- CLI assertions for the 80% case (agent presses keys, checks one thing).
- Python DSL for the 20% case (complex multi-step scenarios).

**Cons:**

- Two APIs to maintain (though the CLI assertions are thin wrappers).

## Recommendation: Option B -- Python Testing DSL (`sase.ace.testing`)

### Why

1. **Playwright's value is the API, not the transport.** Playwright succeeds because of its fluent assertions,
   auto-waiting, and selector model -- not because it talks to Chrome over CDP. We can bring those same API patterns to
   Textual's in-process Pilot, getting the DX _and_ the speed.

2. **Agents write Python naturally.** Every major coding agent (Claude, Gemini, Codex) is excellent at writing pytest
   tests. A well-designed Python module with clear method names (`page.press()`, `page.expect_state()`) is immediately
   learnable. YAML specs or CLI DSLs add artificial constraints.

3. **In-process testing is strictly superior for Textual apps.** External PTY-based tools (tui-test, termwright,
   agent-tui) are black-box -- they can only see the screen. Our Pilot approach gives us both the screen _and_ the full
   widget tree, reactive state, and CSS query system. We'd lose capabilities by going external.

4. **The boilerplate problem is solvable with a thin wrapper.** The current pain isn't architectural -- it's ergonomic.
   Compare:

   **Before (current):**

   ```python
   async def test_navigate():
       with _patch_changespecs(MOCK_CHANGESPECS):
           result = json.loads(await run_agent_mode(query='"feature"', keys=["j"]))
       assert result["error"] is None
       assert result["state"]["idx"] == 1
   ```

   **After (proposed):**

   ```python
   async def test_navigate():
       async with AcePage(query='"feature"') as page:
           await page.press("j")
           await page.expect_state("idx", 1)
   ```

   Same test, half the lines, no JSON parsing, no error checking boilerplate, and the assertion auto-retries if state
   hasn't settled yet.

5. **Incremental adoption.** The DSL wraps the existing `run_agent_mode()` and Pilot API -- existing tests keep working
   unchanged. New tests use the DSL. Migration is optional and gradual.

### Suggested scope for initial implementation

- `AcePage` context manager (app lifecycle, default mocks, cleanup)
- `press(*keys)` and `click(selector)` methods
- `expect_state(key, value)` with auto-retry + timeout
- `expect_modal(name)` and `expect_no_modal()` convenience methods
- `expect_screen_contains(text)` with auto-retry
- `wait_for(predicate, timeout)` for custom conditions
- `state` property for direct state dict access
- `with_changespecs(specs)` classmethod/builder for mock setup
- `query(selector)` / `query_one(selector)` for Textual CSS queries

This is ~150-200 lines of wrapper code. The complexity lives in Textual's Pilot, not in our DSL.

### Future extensions (not in initial scope)

- `--assert` CLI flag for quick one-off checks (Option D's CLI side)
- Snapshot testing integration (text-based, not SVG -- compare screen text against saved baseline)
- Test recording (`sase ace --record` captures interaction as Python test code)
- Screen region helpers (`page.screen_line(n)`, `page.screen_section(y1, y2)`)
