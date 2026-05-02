---
create_time: 2026-05-01 17:26:32
status: done
prompt: sdd/prompts/202605/overwrite_agent_wait_conditions.md
---
# Plan: make Agents-tab `w` fully overwrite wait conditions

## Problem

On the Agents tab, the `w` key maps to the `reword` action. For a WAITING agent, `AgentWaitResumeMixin._apply_wait()`
updates `waiting.json` by loading the existing file, replacing only `waiting_for`, and writing the same object back.
That means older wait-condition fields such as `wait_duration` and `wait_until` survive the edit. From the user's point
of view, the new wait target is added to the previous wait conditions instead of replacing them.

There is a second nearby correctness issue: `WaitModal` pre-fills multiple dependency names as `"a, b"`, but
`_apply_wait()` stores submitted text as `[name]`, so a comma-separated edit becomes one literal dependency name. The
rest of the wait directive system treats comma-separated `%wait` arguments as multiple wait names, so the TUI edit path
should match that behavior for simple names.

## Goals

- Pressing `w` on a WAITING agent and entering a non-empty wait target should replace the active wait conditions with
  the submitted agent-name dependencies only.
- Old `wait_duration` and `wait_until` fields must be removed from `waiting.json` and cleared from the in-memory
  `Agent`.
- Existing non-condition metadata in `waiting.json`, such as `cl_name` and `timestamp`, should be preserved.
- Empty submission should keep the existing “run now” behavior by writing `ready.json`.
- Tests should pin the overwrite behavior and comma-separated dependency parsing.

## Proposed Implementation

1. Update `src/sase/ace/tui/actions/agents/_wait_resume.py`.
   - Add a small helper near the wait action code to parse modal input into dependency names.
   - Split on commas, trim whitespace, and drop empty segments, matching common `%wait:a,b` behavior for the modal path.
   - Keep this helper intentionally simple; the modal accepts agent names, not full `%wait` directive syntax, so it
     should not parse durations or absolute times.

2. Change `_apply_wait()` for non-empty input.
   - Load the existing `waiting.json` only to preserve non-condition metadata.
   - Explicitly remove condition fields that should not survive an overwrite: `waiting_for`, `wait_duration`, and
     `wait_until`.
   - Write a fresh `waiting_for` list from the parsed input.
   - Update the selected `Agent` optimistically: `agent.waiting_for = parsed_names`, `agent.wait_duration = None`, and
     `agent.wait_until = None`.
   - Keep notification and display refresh behavior, but show the normalized comma-joined target list.

3. Add focused tests.
   - Extend `tests/ace/tui/test_agent_marking.py` or add a narrowly scoped test file under `tests/ace/tui/` for
     `AgentWaitResumeMixin._apply_wait()`.
   - Cover overwriting `waiting.json` that already has `waiting_for`, `wait_duration`, and `wait_until`.
   - Assert that `cl_name`/`timestamp` survive, condition fields are fully replaced, and the in-memory `Agent` mirrors
     the new state.
   - Cover comma-separated modal input such as `"alice, bob,, "` producing `["alice", "bob"]`.

4. Verify.
   - Run the focused wait/agent TUI tests first.
   - Because this repo’s memory requires it after changes, run `just install` if needed, then `just check` before
     reporting back.

## Risks and Notes

- This does not alter the runner’s `wait_for_dependencies()` semantics. If a running process is already inside a
  duration-only sleep branch, editing `waiting.json` cannot currently interrupt that sleep; this fix targets the active
  marker semantics the TUI controls and displays.
- The RUNNING-agent restart path currently prepends `%w:<name>` to the old raw prompt, so any old wait directives in
  that prompt may still coexist after restart. The reported issue is specifically the Agents-tab `w` edit path that
  mutates wait conditions for WAITING agents; if desired, the restart path can be treated as a separate behavior change.
