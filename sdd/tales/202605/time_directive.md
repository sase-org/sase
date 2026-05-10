---
create_time: 2026-05-09 23:00:06
status: wip
prompt: sdd/prompts/202605/time_directive.md
---
# Plan: Add `%time` / `%t` Directive For Time-Based Waits

## Goal

Split the overloaded `%wait` directive into two clearer directives:

- `%wait` / `%w` waits for named agents or workflows to complete successfully.
- `%time` / `%t` waits for a duration or absolute wall-clock time.

The existing runtime fields and behavior for time waits should remain intact: parsed time waits should still populate
`wait_duration` or `wait_until`, write the same `agent_meta.json` / `waiting.json` fields, show the same WAITING UI
state, defer workspace allocation, and combine correctly with named `%wait` dependencies. The user-facing syntax and
validation should be clearer: `%wait:5m` should no longer be accepted as a duration wait; users should write `%time:5m`.

## Current State

Directive parsing lives in `src/sase/xprompt/directives.py` with shared names and aliases in
`src/sase/xprompt/_directive_types.py`.

Today:

- `_KNOWN_DIRECTIVES` includes `wait` but not `time`.
- `_MULTI_VALUE_DIRECTIVES` includes only `wait`.
- `_DIRECTIVE_ALIASES` maps `w -> wait` and currently maps `t -> tag`.
- `extract_prompt_directives()` parses `%wait` arguments and classifies each argument as:
  - empty/bare wait: resolve to the most recently named agent;
  - duration: `parse_duration()`;
  - absolute time: `parse_absolute_time()`;
  - otherwise: agent/workflow name.
- `PromptDirectives` already has separate storage for the resulting runtime concepts:
  - `wait: list[str]`
  - `wait_duration: float | None`
  - `wait_until: str | None`

The runner path already handles these fields cleanly:

- `src/sase/axe/run_agent_phases.py` writes `wait_for`, `wait_duration`, and `wait_until` into `agent_meta.json`.
- `wait_for_dependencies()` supports named dependencies plus duration/time floors, duration-only waits, and
  absolute-time-only waits.
- `src/sase/axe/run_agent_runner.py` starts waiting when any of `wait_names`, `wait_duration`, or `wait_until` exists.
- TUI metadata enrichment and display already understand `wait_duration` and `wait_until`.

The confusing part is entirely at the directive syntax layer and the launch-time early-detection helpers.

There is also an alias conflict: `%t` is currently the Python alias for `%tag`. The Rust core editor metadata has
already moved grouping metadata toward `%group` / `%g`, but Python still exposes `%tag` / `%t` in `_directive_types.py`,
docs, and tests. Giving `%t` to `%time` means `%tag` can remain canonical, but `%t` can no longer be a tag alias.

## Desired Semantics

### `%wait` / `%w`

- Accepts agent/workflow dependency names.
- Allows multiple occurrences, comma-separated colon args, and paren form.
- Bare `%wait` / `%w` keeps its existing behavior: resolve to the most recently named agent.
- Does not accept duration or absolute-time arguments.
- If an argument looks like a duration or absolute time, raise `DirectiveError` with a direct migration hint, for
  example: `"%wait:5m is a time wait; use %time:5m instead"`.

### `%time` / `%t`

- Accepts duration arguments using the existing `XhYmZs` grammar, such as `%time:5m`, `%t:1h30m`, and `%time:90s`.
- Accepts absolute time arguments using the existing formats:
  - `HHMM`
  - `yymmdd/HHMM`
- Allows multiple occurrences, comma-separated colon args, and paren form.
- Multiple durations take the maximum, preserving current `%wait` duration behavior.
- Multiple absolute times are rejected.
- A duration and an absolute time cannot be combined.
- Can be combined with named `%wait` dependencies; the agent waits for dependencies first and then observes the
  remaining duration or absolute-time floor using the existing `wait_for_dependencies()` behavior.
- Bare `%time` is invalid with a clear message.
- Non-time `%t:<value>` values should fail with a message that helps users who meant the old tag alias, for example:
  `"Invalid %time value 'review'; use %time:5m for time waits or %tag:review for tags"`.

## Implementation Plan

1. Update directive registration.
   - Add `time` to `_KNOWN_DIRECTIVES`.
   - Add `time` to `_MULTI_VALUE_DIRECTIVES`.
   - Change `_DIRECTIVE_ALIASES` so `t -> time`.
   - Remove `t -> tag`; keep canonical `%tag:<name>` working.
   - Keep `PromptDirectives` fields unchanged (`wait_duration` / `wait_until`) so downstream metadata and UI code do not
     need a data-model migration.

2. Split wait parsing from time parsing in `extract_prompt_directives()`.
   - Keep the bare `%wait` resolution logic only in the `%wait` branch.
   - Build `directives.wait` only from `%wait` values.
   - Parse `%time` values into `wait_duration` / `wait_until` using `parse_duration()` and `parse_absolute_time()`.
   - Add helper functions if needed, likely near `_directive_time.py`, so error messages and duplicate/combination rules
     are tested independently from the rest of directive extraction.
   - For `%wait` arguments that parse as duration or absolute time, raise a migration error instead of treating them as
     valid waits.
   - For `%time` arguments that are neither duration nor absolute time, raise a `%time`-specific invalid argument error
     instead of silently treating them as agent names.

3. Preserve launch deferral for time-only prompts.
   - Add a new cheap helper such as `has_deferred_start_directive(prompt)` or `has_wait_or_time_directive(prompt)` that
     detects either `%wait/%w` or `%time/%t`.
   - Keep `has_wait_directive(prompt)` focused on `%wait/%w` if practical, so its name matches its new semantics.
   - Update launch paths that use early wait detection for workspace deferral to call the new helper:
     - `src/sase/agent/launch_cwd.py`
     - `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
     - multi-model / repeat launch helpers that accept a `has_wait` flag for deferred workspace decisions
   - Preserve bare-wait chain logic in `src/sase/agent/multi_prompt_references.py`; `%time` should not participate in
     bare previous-agent rewrites.

4. Update Rust core where the behavior crosses the backend boundary.
   - In `../sase-core/crates/sase_core/src/editor/directive.rs`, add `%time` with alias `%t` to directive metadata.
   - In `../sase-core/crates/sase_core/src/agent_launch/mod.rs`, add `t -> time` to canonical directive normalization
     and update any wait/deferred-start detection that should recognize time waits.
   - Keep Rust multi-prompt bare `%wait` behavior limited to `%wait/%w`; `%time` is not a predecessor dependency.
   - Add/update Rust tests for alias resolution and fanout/deferred-start metadata where applicable.

5. Update completion and docs.
   - In `src/sase/ace/tui/widgets/directive_completion.py`, add `%time` metadata:
     - argument hint like `:duration or :HHMM`
     - description like `defer launch until a duration or wall-clock time`
   - Update `%wait` metadata to describe agent/workflow dependencies only.
   - Update `%tag` metadata to remove `%t` as an alias.
   - Update `docs/xprompt.md`:
     - supported-directives table;
     - syntax examples;
     - `%wait` prose;
     - multi-value examples.
   - Search docs, SDD examples, and generated prompt examples for user-facing `%t:` references and change SASE tag
     examples to `%tag:` unless they intentionally refer to `%time`.

6. Update tests.
   - Directive extraction:
     - `%time:5m`, `%t:5m`, `%time:1h30m`, `%time:90s` set `wait_duration`.
     - multiple durations take the maximum.
     - `%time:0000` and `%time:260415/0900` set `wait_until`.
     - `%time` bare is invalid.
     - `%time:agent` is invalid.
     - `%time` can combine with `%wait:agent`.
     - duration plus absolute time still errors.
     - multiple absolute times still error.
     - `%wait:5m`, `%wait:1430`, and `%wait:260415/0900` error with a migration hint.
     - `%wait:agent` and bare `%wait` still work.
     - `%tag:review` still works, while `%t:review` no longer sets `tag` and should produce a helpful `%time` error.
   - Helper tests:
     - `has_wait_directive()` detects `%wait/%w` only.
     - the new deferred-start helper detects both `%wait/%w` and `%time/%t`.
   - Launch tests:
     - a time-only prompt gets deferred workspace behavior just like the old `%wait:5m` path.
     - multi-prompt bare `%wait` rewrites are unchanged.
   - Completion tests:
     - `%t` completes to `%time`.
     - `%tag` remains listed.
     - `%wait` description no longer says time/duration.
   - Rust tests:
     - editor alias resolution includes `t -> time`.
     - directive completion includes `%time`.
     - any core launch wait/deferred-start helper recognizes `%time` as needed.

7. Verification.
   - Run targeted Python tests first:
     - `uv run pytest tests/test_directives_types.py tests/test_directives_extract.py tests/test_directives_has_helpers.py tests/ace/tui/widgets/test_directive_completion.py`
     - launch-focused tests touched by helper changes.
   - If `../sase-core` is modified, run its targeted Rust tests from that repo, then its required check command.
   - Because this repo requires it after source changes, run `just install` first if the workspace is stale, then
     `just check` before final handoff.

## Risks And Decisions

- `%t` alias reassignment is intentionally breaking for old `%t:<tag>` prompts. The least surprising migration is to
  keep `%tag:<name>` valid and make `%t:<non-time>` fail loudly with a message that names `%tag:<name>`.
- `has_wait_directive()` is currently used for both semantic wait detection and workspace-deferral detection. Renaming
  or splitting that concept is important so `%time` does not accidentally become a bare previous-agent dependency.
- Rust core and Python currently disagree about tag/group directive metadata. This task should not broaden into a full
  `%tag` to `%group` migration, but any touched directive registry should leave `%t` consistently owned by `%time`.
- Existing persisted metadata does not need migration because runtime storage remains `wait_duration` and `wait_until`.
- Existing `waiting.json` / `ready.json` coordination does not need a format change; named dependencies and time floors
  are already represented separately.
