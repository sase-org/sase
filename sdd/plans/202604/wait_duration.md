---
create_time: 2026-04-10 22:16:58
status: done
prompt: sdd/prompts/202604/wait_duration.md
---

# Plan: Duration-based `%wait` support

## Goal

Add support for duration arguments (`XhYmZs`) to the `%wait` directive. When a user writes `%wait:5m` or `%wait:1h30m`,
the agent sleeps for that duration before starting, rather than waiting for another agent to complete. This enables use
cases like "wait 10 minutes for a deploy to propagate, then run tests."

## Design decisions

### Duration vs agent-name disambiguation

Duration arguments start with a digit (`5m`, `1h30m15s`); agent names start with a letter or underscore. This makes
disambiguation unambiguous at parse time — no new syntax needed.

Supported duration format: one or more groups of `<number><unit>` where unit is `h` (hours), `m` (minutes), or `s`
(seconds). Examples: `5m`, `90s`, `1h`, `2h30m`, `1h30m15s`. Units must appear in h > m > s order (no `5s3h`). Each unit
can appear at most once.

### Data model

Add a `wait_duration: float | None` field to `PromptDirectives` (seconds). This is separate from the `wait: list[str]`
field that holds agent names. Rationale:

- Duration is semantically different from agent-name dependencies — it's a timer, not a dependency.
- Only one duration makes sense per prompt (multiple durations would be confusing — just use the longest).
- If both `%wait:agent` and `%wait:5m` appear, both should be honored: we wait for the agent AND at least the duration.

### Execution model

When both agent-name waits and a duration wait are present, the duration runs concurrently with the agent-name polling.
The duration is simply a minimum floor — the agent won't start before the duration elapses, even if all named
dependencies finish earlier. This is implemented by tracking elapsed time during the existing polling loop and adding a
final `time.sleep()` for any remaining duration after `ready.json` appears.

When only a duration wait is present (no agent names), we skip the `waiting.json`/`ready.json` mechanism entirely and
just sleep directly (with kill-signal checks).

## Phases

### Phase 1: Duration parsing utility

Add a `parse_duration(s: str) -> float | None` function to `src/sase/xprompt/directives.py`.

- Returns total seconds as a float if the string matches the `XhYmZs` pattern, or `None` if it doesn't match.
- Pattern: `^(\d+h)?(\d+m)?(\d+s)?$` with at least one group required.
- Validates ordering (h before m before s) and no duplicate units.
- This is a pure function, easy to unit test.

### Phase 2: Directive extraction updates

Modify `extract_prompt_directives()` in `src/sase/xprompt/directives.py`:

- When processing `%wait` arguments in the `seen_multi["wait"]` loop, call `parse_duration()` on each raw argument.
- If it's a duration, accumulate it into a duration total (take the max if multiple durations somehow appear).
- If it's not a duration, treat it as an agent name (existing behavior).
- Bare `%wait` (no argument) continues to resolve to the most recently named agent — unchanged.

Add `wait_duration: float | None` to `PromptDirectives` dataclass.

Update the `_DIRECTIVE_PATTERN` regex if needed — currently the colon-arg character class is
`[a-zA-Z0-9_#/.()-]*[a-zA-Z0-9_#/()-]` which already allows digits, so `%wait:5m` should parse correctly.

### Phase 3: Propagate duration through \_AgentInfo and agent_meta

In `src/sase/axe/run_agent_phases.py`:

- Add `wait_duration: float | None` to `_AgentInfo`.
- In `extract_directives_and_write_meta()`, read `directives.wait_duration` and pass it through.
- Write `wait_duration` to `agent_meta.json` when present (for observability).

### Phase 4: Duration sleep in wait_for_dependencies

In `src/sase/axe/run_agent_phases.py`, modify `wait_for_dependencies()`:

- Accept an optional `duration: float | None` parameter.
- **Duration-only case** (no agent names): Sleep for the duration in a loop (checking `was_killed()` each poll
  interval), then return. Skip `waiting.json`/`ready.json` entirely.
- **Both duration and agent names**: Write `waiting.json` as before. Track elapsed time during the polling loop. After
  `ready.json` appears, if elapsed time < duration, sleep for the remainder.
- Write `wait_duration` into `waiting.json` when present (so TUI can display it).

### Phase 5: Runner integration

In `src/sase/axe/run_agent_runner.py`:

- Pass `info.wait_duration` to `wait_for_dependencies()`.
- The `has_wait` / deferred workspace logic in the launcher (`src/sase/agent/launcher.py`) already keys off
  `has_wait_directive()` which will continue to match `%wait:5m`, so no changes needed there.

### Phase 6: Tests

In `tests/test_directives.py`, add tests for:

- `parse_duration()`: valid durations (`5m`, `1h`, `90s`, `2h30m`, `1h30m15s`), invalid inputs (`abc`, `5x`, `5m3h`,
  ``, `5m5m`), edge cases (`0s`, `0h0m0s`).
- `extract_prompt_directives()` with duration args: `%wait:5m` sets `wait_duration=300.0` and `wait=[]`.
- Mixed: `%wait:agent\n%wait:5m` sets both `wait=["agent"]` and `wait_duration=300.0`.
- `has_wait_directive()` still detects `%wait:5m`.

### Phase 7: Lint and check

Run `just install && just check` to ensure everything passes.

## Out of scope

- TUI display of duration countdown (can be added later).
- TUI interactive modification of duration waits (the `WaitModal` currently handles agent names; duration support there
  is a follow-up).
- `wait_checks` chop changes — duration waits are handled entirely in-process, the chop only deals with agent-name
  dependencies.
