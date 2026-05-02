---
bead_id: sase-2
status: done
prompt: sdd/prompts/202603/multi_agent_prompts.md
---

# Multi-Agent Prompts: Implementation Plan

## Overview

Add support for triggering multiple agents from a single prompt using `---` as a segment separator, plus
user-prompt-level frontmatter for defining local xprompts. This applies to all agent launch modes: `sase run`,
`sase run --daemon`, and TUI `@` keybinding.

### Behavior Summary

- `---` on its own line separates agent prompt segments
- Agents launch sequentially: wait for agent N to be **named** before launching agent N+1
- Agents do NOT wait for completion between launches unless `%wait` is used
- Bare `%wait` in segment N+1 auto-resolves to the agent launched from segment N
- User prompts can have YAML frontmatter defining local xprompts (names must start with `_`, scoped to the prompt)

### Example

```
---
xprompts:
  _review_style: "Focus on correctness and readability"
---

%name:author
#gh:sase Fix the bug in parser.py. #_review_style

---

%wait
#gh:sase Add tests for the parser fix. #_review_style

---

%wait
#gh:sase Deploy the changes
```

This launches 3 agents sequentially. Agent 2 waits for agent 1 (`author`) to complete. Agent 3 waits for agent 2. All
three can use the `#_review_style` local xprompt.

---

## Phase 1: Multi-Prompt Parsing Module

**Goal**: Create a self-contained parsing module that splits a user prompt into frontmatter + segments.

### Key Design: Disambiguating `---`

The first `---` pair at the very start of the document is frontmatter (YAML between the `---` delimiters). After
frontmatter is consumed, subsequent `---` lines on their own are segment separators. If there is no frontmatter, ALL
`---` lines are segment separators.

Important: A prompt that has frontmatter but only one segment (no `---` separators after the frontmatter closing `---`)
is a single-agent prompt with local xprompts — not a multi-agent prompt.

### Files to Create

- **`src/sase/multi_prompt.py`** — Core parsing module
  - `MultiPrompt` dataclass: `frontmatter: dict | None`, `local_xprompts: dict[str, XPrompt]`, `segments: list[str]`
  - `parse_multi_prompt(text: str) -> MultiPrompt`:
    1. Call `parse_yaml_front_matter()` to extract frontmatter (if present)
    2. From the frontmatter dict, extract `xprompts` key and parse via `parse_xprompt_entries()`
    3. Validate local xprompt names start with `_` (reuse logic from `_validate_xprompt_names`)
    4. Split remaining body on `^---$` lines (regex: `r"^---\s*$"` with `re.MULTILINE`)
    5. Strip empty/whitespace-only segments
    6. Return `MultiPrompt`
  - `is_multi_prompt(text: str) -> bool` — quick check without full parsing (looks for `---` outside frontmatter)

- **`tests/test_multi_prompt.py`** — Unit tests
  - Single segment, no frontmatter → 1 segment, no xprompts
  - Two segments, no frontmatter → 2 segments
  - Frontmatter + single segment → 1 segment + xprompts
  - Frontmatter + multiple segments → N segments + xprompts
  - `---` inside fenced code blocks should NOT split (protect fenced blocks first)
  - Invalid xprompt names (no `_` prefix) → validation error
  - Empty segments are stripped
  - Whitespace handling around `---` separators
  - `is_multi_prompt` quick-check correctness

### Dependencies

- `sase.xprompt.loader_parsing.parse_yaml_front_matter`
- `sase.xprompt.loader_parsing.parse_xprompt_entries`
- `sase.xprompt._fenced_blocks.protect_fenced_blocks` / `unprotect_fenced_blocks`

---

## Phase 2: User Prompt Local XPrompts Integration

**Goal**: Wire up frontmatter-defined local xprompts so they work during prompt preprocessing in all modes.

### Key Design

When a user prompt has frontmatter with an `xprompts` key, those xprompts are passed as `extra_xprompts` to
`process_xprompt_references()`. This already supports an `extra_xprompts` parameter (used by workflow-local xprompts).
The same mechanism is reused.

### Files to Modify

- **`src/sase/axe_run_agent_phases.py`** — `extract_directives_and_write_meta()`
  - Before expanding xprompts, call `parse_multi_prompt()` to extract frontmatter
  - Pass `extra_xprompts=multi_prompt.local_xprompts` to `process_xprompt_references()`
  - This handles daemon-mode and TUI-launched agents

- **`src/sase/main/query_handler/_query.py`** — `run_query()`
  - Before creating the anonymous workflow, parse frontmatter from the query
  - Pass local xprompts through to the workflow execution (either via `extra_xprompts` on the anonymous workflow object,
    or by expanding them inline before workflow creation)

- **`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`** — `_finish_agent_launch()`
  - Before xprompt expansion (line ~158), parse frontmatter and pass local xprompts
  - Ensure the raw prompt saved for history still includes the frontmatter

### Files to Create

- **`tests/test_user_frontmatter.py`** — Integration tests
  - Frontmatter xprompts expand correctly in prompts
  - `_`-prefixed names only
  - Local xprompts don't leak to other prompts
  - Works in agent runner context

### Important: Check `process_xprompt_references` signature

The function in `src/sase/xprompt/processor.py` already accepts `extra_xprompts: dict[str, XPrompt] | None = None`.
Verify this and use it. If it doesn't exist, add it (matching the workflow runner's approach).

---

## Phase 3: Multi-Agent Sequential Launch Orchestration

**Goal**: When a prompt splits into multiple segments, launch each as a separate agent with naming-wait between
launches.

### Key Design: Naming Wait

After launching agent N, poll for its `agent_meta.json` to contain a `"name"` field before launching agent N+1. This
ensures bare `%wait` in segment N+1 can resolve to agent N's name.

Polling parameters: 0.5s interval, 30s timeout (naming should happen within seconds of launch).

The naming-wait is distinct from the `%wait` directive's dependency wait (which waits for **completion**). The
naming-wait only ensures the agent is registered and named.

### Files to Create

- **`src/sase/multi_prompt_launcher.py`** — Sequential launch orchestration
  - `launch_multi_prompt_agents(segments: list[str], local_xprompts: dict[str, XPrompt], ...)`:
    1. For each segment: a. Inject local xprompts into the segment (either via env var or by prepending a synthetic
       frontmatter) b. Call the appropriate single-agent launch function c. Poll the launched agent's `agent_meta.json`
       for the `"name"` field d. Store the name for potential bare `%wait` resolution in the next segment
    2. Return list of launch results
  - `wait_for_agent_naming(artifacts_dir: str, timeout: float = 30) -> str | None`:
    - Poll `agent_meta.json` for `"name"` key
    - Return the name when found, or None on timeout

### Strategy for passing local xprompts to sub-agents

Two approaches:

**Option A: Environment variable** — Serialize the local xprompts dict to a temp JSON file and pass the path via
`SASE_AGENT_LOCAL_XPROMPTS` env var. The agent runner reads this and passes to `process_xprompt_references()`.

**Option B: Inline expansion** — Before launching each segment, expand local xprompt references inline (replace `#_foo`
with its content). This avoids the need to pass xprompts to the subprocess but loses the xprompt structure.

**Recommended: Option A** — It preserves the xprompt semantics (inputs, hooks, etc.) and is more robust for complex
xprompts with arguments.

### Files to Modify

- **`src/sase/agent_launcher.py`**
  - `spawn_agent_subprocess()`: Accept optional `local_xprompts_file` parameter, set env var
  - `launch_agent_from_cwd()`: Call `parse_multi_prompt()`, if multi-prompt, use `launch_multi_prompt_agents()`

- **`src/sase/axe_run_agent_phases.py`** — `extract_directives_and_write_meta()`
  - Read `SASE_AGENT_LOCAL_XPROMPTS` env var if present
  - Load and merge with any existing extra xprompts

- **`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`** — `_finish_agent_launch()`
  - Before launching, call `parse_multi_prompt()`
  - If multi-prompt: call multi-prompt launcher instead of single `_launch_background_agent()`
  - Similar pattern to `_launch_multi_model_agents()` but with naming-wait between launches

- **`src/sase/main/query_handler/_daemon.py`** — `run_query_daemon()`
  - Split on multi-prompt; launch multiple agents if needed

- **`src/sase/main/query_handler/special_cases.py`** — `handle_run_special_cases()`
  - If `sase run` (non-daemon) detects multi-prompt, automatically switch to daemon mode
  - Print message: "Multi-prompt detected — launching N agents in daemon mode"

- **`src/sase/main/query_handler/_query.py`** — `run_query()`
  - If multi-prompt detected, redirect to daemon-style launch (multi-prompt inherently requires async)

### Files to Create

- **`tests/test_multi_prompt_launcher.py`** — Tests for sequential launch
  - Mock `spawn_agent_subprocess` to verify sequential calls
  - Verify naming-wait polling behavior
  - Test timeout handling
  - Test local xprompts passed via env var

---

## Phase 4: End-to-End Testing and Polish

**Goal**: Comprehensive E2E tests, edge case handling, and any remaining integration work.

### E2E Tests

Using `sase ace --agent` for headless TUI testing:

- Submit a multi-prompt via the TUI prompt bar
- Verify multiple agents appear in the agents tab
- Verify naming propagation

### Edge Cases to Handle

- **Frontmatter-only (no segments)**: Treat as single segment with local xprompts
- **VCS refs across segments**: Each segment can have its own VCS ref (different projects)
- **Mixed directives**: `%model`, `%name`, `%wait` within individual segments
- **`%wait` without prior segment**: First segment with bare `%wait` should resolve to the most recent external agent
  (existing behavior)
- **Multi-model within multi-prompt**: `%m(opus,sonnet)` in a segment should still create multi-model agents for that
  segment
- **Resume mode (`sase run -r`)**: Multi-prompt in resume mode — should we support it? Probably not initially; error if
  resume + multi-prompt.
- **Bulk launch**: Multi-prompt in bulk launch mode — error or expand each CS × each segment

### Files to Modify (polish)

- **`src/sase/axe_run_agent_runner.py`**: Ensure local xprompts env var cleanup after reading
- **`src/sase/xprompt/directives.py`**: Ensure `has_wait_directive()` works correctly when used to check individual
  segments (not the full multi-prompt)

### Files to Create

- **`tests/test_multi_prompt_e2e.py`** — E2E integration tests

---

## Architecture Summary

```
User Prompt (with optional frontmatter + --- separators)
    │
    ▼
parse_multi_prompt()  ──→  MultiPrompt(frontmatter, local_xprompts, segments)
    │
    ├── Single segment: normal flow (local xprompts available if frontmatter present)
    │
    └── Multiple segments: launch_multi_prompt_agents()
            │
            ├── Segment 1 → spawn_agent_subprocess() → wait for naming → "agent_a"
            ├── Segment 2 → spawn_agent_subprocess() → wait for naming → "agent_b"
            └── Segment 3 → spawn_agent_subprocess() → done
```

## Key Files Reference

| File                                                       | Role                                                    |
| ---------------------------------------------------------- | ------------------------------------------------------- |
| `src/sase/multi_prompt.py`                                 | **NEW** — Parsing module                                |
| `src/sase/multi_prompt_launcher.py`                        | **NEW** — Sequential launch orchestration               |
| `src/sase/agent_launcher.py`                               | Subprocess spawning (modify for local xprompts env var) |
| `src/sase/axe_run_agent_phases.py`                         | Agent lifecycle phases (modify for local xprompts)      |
| `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` | TUI agent launch (modify for multi-prompt)              |
| `src/sase/main/query_handler/_daemon.py`                   | Daemon launch (modify for multi-prompt)                 |
| `src/sase/main/query_handler/special_cases.py`             | CLI routing (modify for auto-daemon)                    |
| `src/sase/main/query_handler/_query.py`                    | Sync query (modify for auto-daemon redirect)            |
| `src/sase/xprompt/directives.py`                           | Directive parsing (reference only)                      |
| `src/sase/xprompt/processor.py`                            | XPrompt expansion (uses extra_xprompts)                 |
| `src/sase/xprompt/loader_parsing.py`                       | Frontmatter parsing (reuse)                             |
