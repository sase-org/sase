---
create_time: 2026-04-11 02:53:05
status: done
prompt: sdd/prompts/202604/repeat_directive.md
---

# Plan: `%repeat` Directive (alias `%N`)

## Overview

Add a new `%repeat` directive (alias `%N`) that takes a positive integer argument and runs the prompt that many times in
sequence. Each iteration re-executes the same prompt against the same workspace, enabling use cases like iterative
refinement, batch processing, and repeated code review sweeps.

**Example usage:**

```
%N:3 #gh:sase Fix all TODO comments in this module
```

This runs the prompt 3 times in sequence. If any iteration fails, the remaining iterations are skipped.

## Design Decisions

### Naming

- **Canonical name:** `repeat` (follows existing convention: `wait`, `model`, `name`, etc.)
- **Alias:** `N` (uppercase, distinct from lowercase `n` which aliases `name`)

### Execution model

The repeat loop lives in `run_agent_runner.py`, wrapping the existing `run_execution_loop()` call. This means:

- Single process, single workspace — iterations run sequentially in the same environment
- Each iteration sees the cumulative changes from prior iterations (iterative refinement)
- A failed iteration stops the loop (fail-fast)
- A user kill (SIGTERM) stops the loop

### Progress tracking

A `repeat_state.json` file in the artifacts directory tracks live progress:

```json
{
  "repeat_count": 5,
  "current_iteration": 3,
  "completed_iterations": 2
}
```

The TUI polls this file the same way it polls `waiting.json` for wait status.

### Interaction with other directives

- `%repeat:3 %wait:agent1` — wait resolves first, then all 3 iterations run
- `%repeat:3 %name:foo` — agent is named "foo" throughout all iterations
- `%repeat:3 %model:opus` — all iterations use the same model
- `%repeat:3 %approve+` — auto-approve is active for all iterations
- Multi-model `%m(opus,sonnet) %repeat:3` — each model-split agent independently repeats 3 times

### TUI display

**Agent list row** — compact repeat annotation after status (follows retry pattern):

```
[agent] sase (RUNNING) ↻2/5 @foo
```

The `↻2/5` uses the same circular arrow glyph as retries but adds the total.

**Agent detail header** — dedicated "Repeat" field with progress bar:

```
Repeat:     ██████░░░░ 3/5
```

When complete: `Repeat: 5/5 done`

## Implementation

### Phase 1: Directive parsing (`src/sase/xprompt/directives.py`)

1. Add `"repeat"` to `_KNOWN_DIRECTIVES`
2. Add `"N": "repeat"` to `_DIRECTIVE_ALIASES`
3. Add `repeat_count: int | None = None` field to `PromptDirectives`
4. In `extract_prompt_directives()`, parse the `repeat` argument as a positive integer:
   - Validate it's a valid integer > 0
   - Raise `DirectiveError` for non-integer or <= 0 values
5. Add `has_repeat_directive()` fast-check function (same pattern as `has_wait_directive`)

### Phase 2: Runner metadata (`src/sase/axe/run_agent_phases.py`)

1. Add `repeat_count: int | None` to `_AgentInfo`
2. Write `repeat_count` to `agent_meta.json` when present
3. Return `repeat_count` from `extract_directives_and_write_meta()`

### Phase 3: Runner repeat loop (`src/sase/axe/run_agent_runner.py`)

1. After `extract_directives_and_write_meta()`, check for `info.repeat_count`
2. When `repeat_count` is set (> 1), wrap the `run_execution_loop()` call in a for-loop:
   - Before each iteration: write/update `repeat_state.json` with `current_iteration` (1-based)
   - After each iteration: update `completed_iterations`
   - On failure or kill: break out of loop, record partial progress
3. The `done.json` marker should reflect whether all iterations completed or only some
4. Cleanup: remove `repeat_state.json` after all iterations complete (the final state is captured in `done.json`)

### Phase 4: TUI agent model (`src/sase/ace/tui/models/agent.py`)

1. Add two fields to `Agent` dataclass:
   - `repeat_count: int | None = None` — total iterations from `%repeat` directive
   - `repeat_iteration: int | None = None` — current iteration (1-based), live-updated

### Phase 5: TUI artifact loading (`src/sase/ace/tui/models/_loaders/_artifact_loaders.py`)

1. In `enrich_agent_from_meta()`:
   - Read `repeat_count` from `agent_meta.json`
   - Read `repeat_state.json` if it exists to get `current_iteration` and `completed_iterations`
   - For done agents, set `repeat_iteration = repeat_count` (all done)

### Phase 6: TUI detail display (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`)

1. In `build_header_text()`, add a "Repeat" field (after "Waiting for", before "Retries"):
   - Running: `Repeat: ██████░░░░ 3/5` (progress bar + fraction)
   - Done: `Repeat: 5/5 done` (all completed)
   - Partial (failed mid-repeat): `Repeat: 3/5 (stopped)`

### Phase 7: TUI list display (`src/sase/ace/tui/widgets/agent_list.py`)

1. In `_format_agent_option()`, add repeat annotation after status (before fold annotation):
   - Running: ` ↻2/5` styled in bold cyan (#00D7D7) — distinct from retry's orange
   - Done: ` ↻5/5` styled in green (#5FD75F)
   - Partial: ` ↻3/5` styled in orange (#FF8700) — signals incomplete

### Phase 8: Tests

1. **Directive parsing tests** — parsing `%repeat:3`, `%N:5`, validation errors (0, -1, "abc"), interaction with other
   directives
2. **Runner repeat tests** — mock `run_execution_loop`, verify it's called N times, verify `repeat_state.json` is
   written correctly, verify early exit on failure
