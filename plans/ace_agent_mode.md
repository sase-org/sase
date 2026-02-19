# Plan: Native Agent Mode for `sase ace`

## Context

The `tmux_sase` script bridges Claude Code and the `sase ace` TUI by launching the app in a tmux window, sending
keystrokes via `tmux send-keys`, and capturing output via `tmux capture-pane`. This works but has significant drawbacks:

- **Requires tmux** — must be running inside a tmux session
- **Timing-based** — 3s startup delay + 0.5s capture delay + polling; fragile and slow
- **No structured output** — only raw terminal text, no semantic state (which item is selected, which tab, etc.)
- **Separate script** — a whole extra entry point that duplicates `sase ace` setup logic

Textual 8.0.0 has a built-in headless pilot API (`app.run_test()`) that provides deterministic, timing-free interaction.
We can use this to give `sase ace` native agent support — no tmux, structured JSON output, and sub-second execution.

## Approach

Add an `--agent` flag to `sase ace` that runs the app headlessly using Textual's pilot API. The agent sends keys and
gets back JSON containing both the rendered screen text and structured state.

**Execution model: One-shot** — each invocation starts the app, sends keys, captures, exits. This maps naturally to
Claude Code's Bash tool (one command = one step). Multi-step debugging is done with sequential commands, each starting
from real disk state.

## Files to Create/Modify

### 1. NEW: `src/sase/ace/agent_runner.py`

Core module with ~120 lines. Three public functions + two helpers:

```
async run_agent_mode(query, keys, size, model_tier_override) -> str
    Creates AceApp, runs headlessly, sends keys, returns JSON string.

async _run_headless(app, keys, size) -> str
    Runs app.run_test(size=size), sends each key via pilot.press(),
    calls pilot.pause() after each key, captures screen + state.

_capture_screen(app, size) -> str
    Loops screen.render_line(y).text for y in range(height), joins with \n.

_extract_state(app) -> dict
    Reads reactive properties and returns structured dict (see State section below).

_serialize_result(screen, state, error) -> str
    json.dumps the output dict.
```

### 2. MODIFY: `src/sase/main/parser.py`

Add to the `ace_parser` argument group:

- `--agent` — `store_true`, enables headless agent mode
- `--keys` — `nargs="*"`, Textual key names to send (e.g., `j k enter slash`)
- `--size` — `default="120x40"`, terminal dimensions as `WxH`

### 3. MODIFY: `src/sase/main/entry.py`

In the `if args.command == "ace":` block (~line 230), add a branch before `app.run()`:

```python
if getattr(args, "agent", False):
    from sase.ace.agent_runner import run_agent_mode
    import asyncio
    w, h = (parse the --size arg)
    result = asyncio.run(run_agent_mode(
        query=args.query,
        keys=args.keys or [],
        size=(w, h),
        model_tier_override=model_tier_override,
    ))
    print(result)
    sys.exit(0)
```

### 4. DELETE: `src/sase/scripts/tmux_sase.py`

Remove the script file entirely.

### 5. MODIFY: `pyproject.toml`

Remove from `[project.scripts]`:

```
tmux_sase = "sase.scripts.tmux_sase:main"
```

### 6. MODIFY: `CLAUDE.md`

Replace the `## End-to-End Testing w/ tmux_sase` section with documentation for the new agent mode.

### 7. NEW: `tests/test_agent_runner.py`

Tests using the same mock pattern as `tests/test_ace_tui_app.py` — patch `find_all_changespecs`, call
`run_agent_mode()`, parse JSON output, assert on screen/state/error fields.

## Output Format

One-shot returns a single JSON object to stdout:

```json
{
  "screen": "line1\nline2\n...",
  "state": {
    "tab": "changespecs",
    "idx": 0,
    "total": 15,
    "query": "\"(!: \"",
    "canonical_query": "...",
    "marked": [],
    "modal": null,
    "hide_reverted": true,
    "selected": {
      "name": "feature-foo",
      "status": "Ready",
      "cl": "123456",
      "parent": "main-branch",
      "project": "myproject",
      "description": "First 200 chars...",
      "commit_count": 3,
      "hook_count": 2,
      "has_comments": false,
      "has_mentors": true
    },
    "hooks_collapsed": true,
    "commits_collapsed": true,
    "mentors_collapsed": true
  },
  "error": null
}
```

Tab-specific additions:

- **agents tab**: `agent_count`, `selected_agent` (with `type`, `cl_name`, `status`)
- **axe tab**: `axe_running`

On error: `"error"` contains the exception message, `"screen"` and `"state"` are empty.

## Structured State Fields

Extracted from these AceApp attributes (`src/sase/ace/tui/app.py`):

- `app.current_tab` → `state.tab`
- `app.current_idx` → `state.idx`
- `len(app.changespecs)` → `state.total`
- `app.query_string` → `state.query`
- `app.canonical_query_string` → `state.canonical_query`
- `app.marked_indices` → `state.marked` (sorted list)
- `app.screen_stack` → `state.modal` (class name of top modal, or null)
- `app.hide_reverted` → `state.hide_reverted`
- `app.hooks_collapsed` / `commits_collapsed` / `mentors_collapsed`
- `app.changespecs[app.current_idx]` → `state.selected` (ChangeSpec fields from `src/sase/ace/changespec/models.py:415`)
- `app._agents` → agent tab state
- `app.axe_running` → axe tab state

## Key Names

Uses Textual's native key names (same as the `Binding` definitions in `app.py:89-173`):

- Characters: `j`, `k`, `q`, `s`, `r`, `m`, etc.
- Special: `enter`, `escape`, `tab`, `shift+tab`, `space`
- Control: `ctrl+d`, `ctrl+u`, `ctrl+o`, `ctrl+i`
- Named: `slash` (`/`), `question_mark` (`?`), `full_stop` (`.`), `comma` (`,`)

## Screen Capture

Uses Textual's rendering pipeline:

```python
lines = [app.screen.render_line(y).text for y in range(height)]
screen_text = "\n".join(lines)
```

`Screen.render_line(y)` returns a `Strip` whose `.text` property gives the plain text content. This works in headless
mode because `run_test()` uses a virtual screen buffer.

## Usage Examples (from Claude Code)

```bash
# See initial TUI state
sase ace --agent

# Navigate to 3rd item
sase ace --agent --keys j j

# Open query modal
sase ace --agent --keys slash

# Filter to specific project, then navigate
sase ace --agent '"myproject"' --keys j j j

# Switch to agents tab
sase ace --agent --keys tab

# Larger terminal for more detail
sase ace --agent --size 200x50 --keys j
```

## Verification

1. **Unit tests**: `just test -- tests/test_agent_runner.py`
2. **Manual E2E**: Run `sase ace --agent` and verify JSON output has screen text + state
3. **Navigation**: Run `sase ace --agent --keys j j` and verify `state.idx == 2`
4. **Modal detection**: Run `sase ace --agent --keys slash` and verify `state.modal == "QueryEditModal"`
5. **Lint**: `just lint` passes (new module has type annotations)
6. **tmux_sase removed**: Verify `uv run tmux_sase` fails (entry point gone)
