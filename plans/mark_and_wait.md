---
bead_id: sase-gdt
status: done
---

# Plan: `%name:<name>` and `%wait:<name>` Prompt Directives

## Context

Agents launched via `sase ace` currently execute independently with no way to express ordering dependencies. This plan
adds two new prompt directives:

- **`%name:<name>`** — Assigns a name to an agent, written to `agent_meta.json` and `done.json`.
- **`%wait:<name>`** — Blocks an agent until the named agent reaches DONE status.

The agent runner writes a `waiting.json` marker when `%wait` directives are present. A new lumberjack chop
(`wait_checks`) resolves dependencies and writes a `ready.json` signal. The agent runner polls for that signal.

The TUI's `n` key (already bound to `action_rename_cl` on changespecs tab) is extended to open a name-input modal on the
Agents tab, writing directly to `agent_meta.json`.

---

## Phase 1: Directive Parsing + Data Model (foundational — must land first)

### 1a. Add `name` and `wait` to directive parser

**File**: `src/sase/xprompt/directives.py`

- Add `"name"` and `"wait"` to `_KNOWN_DIRECTIVES` (line 32)
- Introduce `_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})` — directives that allow duplicates
- Update `PromptDirectives` dataclass:
  ```python
  name: str | None = None
  wait: list[str] = field(default_factory=list)
  ```
- Update `extract_prompt_directives()`:
  - Add `seen_multi: dict[str, list[str]] = {}` alongside existing `seen`
  - In the duplicate check: if `name in _MULTI_VALUE_DIRECTIVES`, append to `seen_multi[name]` instead of raising
    `DirectiveError`
  - After xprompt expansion, build `wait` list from `seen_multi`
  - Construct: `PromptDirectives(model=..., name=..., wait=...)`

### 1b. Add `agent_name` field to Agent model

**File**: `src/sase/ace/tui/models/agent.py`

- Add field after `vcs_provider` (~line 114):
  ```python
  agent_name: str | None = None
  ```

### 1c. Persist `name` and `wait_for` in agent runner

**File**: `src/sase/axe_run_agent_runner.py`

- After directive extraction (~line 192), capture:
  ```python
  agent_name = directives.name
  agent_wait_names = directives.wait
  ```
- Add to `agent_meta` dict (~line 204): `"name"` and `"wait_for"` keys
- Add `name` to `done_marker` (~line 278) and `error_done` (~line 311)

### 1d. Read `agent_name` in artifact loaders

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

- In `_enrich_agent_from_meta()` (reads `agent_meta.json`): set `agent.agent_name`
- In `_load_done_agents()` (reads `done.json`): pass `agent_name` to Agent constructor

### 1e. Tests

**File**: `tests/test_directives.py`

- `test_name_directive` — `%name:builder` → `name="builder"`
- `test_wait_directive_single` — `%wait:builder` → `wait=["builder"]`
- `test_wait_directive_multiple` — two `%wait` lines → `wait=["a", "b"]`
- `test_name_and_wait_combined` — both in one prompt
- `test_duplicate_name_raises` — two `%name` raises `DirectiveError`
- `test_name_colon_and_backtick_syntax` — `%name:\`my-agent\`` works

---

## Phase 2: TUI Display + Manual Naming (parallel with Phase 3)

### 2a. Display `agent_name` in agent list

**File**: `src/sase/ace/tui/widgets/agent_list.py`

- In `_format_agent_option()`: after the CL name, append ` @{agent_name}` in gold (`#FFD700`)
- Also show `WAITING` status in a distinct color (pink `#FF87D7`)

### 2b. Create `AgentNameModal`

**New file**: `src/sase/ace/tui/modals/agent_name_modal.py`

- Simple `ModalScreen[str | None]` modeled after `CommandInputModal`
- Single text input, pre-filled with current `agent_name` if set
- Returns the entered name on Enter, `None` on Escape
- Register in `src/sase/ace/tui/modals/__init__.py`

### 2c. Extend `n` key for Agents tab

**File**: `src/sase/ace/tui/actions/rename.py`

- `action_rename_cl()` already guards with `current_tab != "changespecs"` and returns early. Change this to dispatch by
  tab:
  - `changespecs` → existing rename CL logic
  - `agents` → new `_set_agent_name()` method
- `_set_agent_name()` opens `AgentNameModal`, then writes `"name"` to `agent_meta.json` via the agent's artifacts dir
  (`agent.get_artifacts_dir()`)
- Add `_agents: list[Agent]` to `RenameMixin` type hints

### 2d. Update help modal

**File**: `src/sase/ace/tui/modals/help_modal/bindings.py`

- Add `("n", "Name agent")` to the Agents tab section

### 2e. Update keybinding footer

**File**: `src/sase/ace/tui/widgets/keybinding_footer.py`

- In agent bindings: show `n name` when an agent is selected

### 2f. Propagate `agent_name` through agent deduplication

**File**: `src/sase/ace/tui/models/agent_loader.py`

- In merge/dedup logic: preserve `agent_name` when merging agent entries

---

## Phase 3: Wait Coordination via Lumberjack (parallel with Phase 2)

### 3a. Agent name resolution utility

**New file**: `src/sase/agent_names.py`

- `find_named_agent(name: str) -> NamedAgent | None` — scans `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`
  for matching `"name"` field
- `NamedAgent` dataclass: `name`, `artifacts_dir`, `is_done`, `outcome`
- Checks `done.json` existence to determine completion (both "completed" and "failed" count)

### 3b. Wait logic in agent runner

**File**: `src/sase/axe_run_agent_runner.py`

After writing `agent_meta.json` and before `execute_workflow()` (~line 240):

1. If `agent_wait_names` is non-empty:
   - Write `waiting.json` with `{"waiting_for": [...], "cl_name": ..., "timestamp": ...}`
   - Poll for `ready.json` in the same artifacts dir (created by lumberjack chop)
   - Poll interval: 2s, with a configurable max timeout (default 24h)
   - On `ready.json` found: delete both `waiting.json` and `ready.json`, proceed
   - Handle SIGTERM: existing handler should interrupt sleep

### 3c. New lumberjack chop: `wait_checks`

**New file**: `src/sase/axe/chops/wait_checks.py`

```python
@register_chop("wait_checks")
def run_wait_checks(ctx: ChopContext) -> None:
    """Resolve wait dependencies for blocked agents."""
```

Logic:

1. Scan all `~/.sase/projects/*/artifacts/ace-run/*/waiting.json`
2. For each waiting agent, check each name in `waiting_for` list
3. Use `find_named_agent(name)` to check if each dependency is done
4. If ALL dependencies satisfied, write `ready.json` to that agent's artifacts dir
5. Log resolution for observability

Register in `src/sase/axe/chops/__init__.py`.

### 3d. Add `wait_checks` to the `hooks` lumberjack

**File**: `src/sase/axe/config.py`

- Add `"wait_checks"` to the `hooks` lumberjack's chop list (runs every 1s — fast enough for responsive unblocking)

### 3e. Display WAITING status in TUI

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

- In the running-agent loader functions: after constructing an agent, check for `waiting.json` in its artifacts dir. If
  present, set `agent.status = "WAITING"`
- Optionally store `waiting_for` names on the Agent for display in the detail panel

### 3f. Agent detail panel: show wait info

**File**: `src/sase/ace/tui/widgets/agent_detail.py`

- When agent status is "WAITING", show the names being waited on in the detail panel

---

## Phase Dependency Graph

```
Phase 1 (Parsing + Data Model)
    ├──> Phase 2 (TUI Display + Manual Naming)
    └──> Phase 3 (Wait Coordination + Lumberjack)
```

Phases 2 and 3 touch mostly disjoint files and can run in parallel after Phase 1 lands.

**Overlap**: `_artifact_loaders.py` is touched by both — Phase 2 reads `mark_name`, Phase 3 reads `waiting.json`. These
are different functions and merge cleanly.

---

## Verification

1. **Directive parsing**: `just test` — new tests in `test_directives.py`
2. **Name via prompt**: Launch agent with `%name:builder` prompt, verify `agent_meta.json` contains `"name": "builder"`,
   TUI shows `@builder` annotation
3. **Name via TUI**: Select running agent on Agents tab, press `n`, enter name, verify `agent_meta.json` updated and
   display refreshes
4. **Wait + name end-to-end**: Launch two agents:
   - Agent A: `%name:fetcher Do the fetching work`
   - Agent B: `%wait:fetcher %name:processor Do the processing work`
   - Verify Agent B shows "WAITING" until Agent A completes, then proceeds
5. **Multiple waits**: Agent with `%wait:a %wait:b` blocks until both `a` and `b` are DONE
6. **Linting**: `just lint` passes
7. **TUI agent test**: `.venv/bin/sase ace --agent` shows agents with names correctly
