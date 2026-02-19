---
bead_id: sase-oqr
---

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

---

## Phased Implementation

Each phase is independently committable and leaves the codebase in a working state. Phases can be completed by separate
Claude Code instances.

### Phase 1: Core agent runner module + tests

**Goal**: Create the standalone `agent_runner.py` module and its tests. No CLI wiring yet — the module is importable but
not reachable via `sase ace`.

**Files**:

- **NEW**: `src/sase/ace/agent_runner.py` — core module (~120 lines)
- **NEW**: `tests/test_agent_runner.py` — tests using mocked changespecs

**What to implement in `agent_runner.py`**:

```
async run_agent_mode(query, keys, size, model_tier_override) -> str
    Creates AceApp, runs headlessly, sends keys, returns JSON string.

_capture_screen(app, height) -> str
    Loops screen.render_line(y).text for y in range(height), joins with \n.

_extract_state(app) -> dict
    Reads reactive properties and returns structured dict (see State section below).
```

**Test cases** (follow pattern from `tests/test_ace_tui_app.py` — patch `find_all_changespecs`):

- No keys → returns initial screen + state with idx=0
- Send `j j` → state.idx == 2
- Send `slash` → state.modal == "QueryEditModal"
- Send `tab` → state.tab changes
- Send `m` → state.marked is populated
- Output is valid JSON with required fields (screen, state, error)
- Custom size → correct number of screen lines
- Invalid query → error field is populated

**Verification**: `just test -- tests/test_agent_runner.py` and `just lint`

### Phase 2: Wire up CLI

**Goal**: Connect the agent runner to the `sase ace` CLI so it's usable via `sase ace --agent`.

**Files**:

- **MODIFY**: `src/sase/main/parser.py` — add `--agent`, `--keys`, `--size` args to ace subparser
- **MODIFY**: `src/sase/main/entry.py` — add agent mode branch before `app.run()`

**Parser additions** (add to `ace_parser`):

- `--agent` — `store_true`, enables headless agent mode
- `--keys` — `nargs="*"`, Textual key names to send (e.g., `j k enter slash`)
- `--size` — `default="120x40"`, terminal dimensions as `WxH`

**Entry point change** (in `if args.command == "ace":` block, ~line 230):

```python
if getattr(args, "agent", False):
    from sase.ace.agent_runner import run_agent_mode
    import asyncio
    w, h = (parse the --size arg)
    result = asyncio.run(run_agent_mode(...))
    print(result)
    sys.exit(0)
```

**Verification**: Run `sase ace --agent` from the command line and verify JSON output. Run `sase ace --agent --keys j j`
and check idx. `just check` passes.

### Phase 3: Remove tmux_sase + update docs

**Goal**: Clean up the old script and update documentation.

**Files**:

- **DELETE**: `src/sase/scripts/tmux_sase.py`
- **MODIFY**: `pyproject.toml` — remove `tmux_sase = "sase.scripts.tmux_sase:main"` from `[project.scripts]`
- **MODIFY**: `CLAUDE.md` — replace the `## End-to-End Testing w/ tmux_sase` section with new agent mode docs

**Verification**: `uv run tmux_sase` fails (entry point gone). `just check` passes. CLAUDE.md references
`sase ace --agent`.

---

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

## Critical File References

- `src/sase/ace/tui/app.py` — AceApp class, reactive properties (lines 175-185), bindings (lines 89-173), `__init__`
  (lines 187-309)
- `src/sase/ace/changespec/models.py:415` — ChangeSpec dataclass fields
- `src/sase/main/parser.py` — ace subparser argument definitions
- `src/sase/main/entry.py:230` — ace command handler
- `tests/test_ace_tui_app.py` — test pattern to follow (mock changespecs + pilot API)
- `src/sase/scripts/tmux_sase.py` — script being replaced (to delete in Phase 3)
