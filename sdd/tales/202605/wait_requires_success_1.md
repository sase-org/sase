---
create_time: 2026-05-06 19:25:13
status: done
prompt: sdd/prompts/202605/wait_requires_success_1.md
---
# Plan: Make `%wait` Dependencies Require Successful Completion

## Problem

Agents launched with `%wait` currently unblock when the waited-for name has any terminal `done.json`. That includes
agents killed by the user, failed agents, dismissed historical bundles, and other non-success outcomes. The waiting
agent then sees `ready.json` and starts even though the dependency did not complete successfully.

The desired behavior is:

- A waiting agent only starts after every named dependency has completed successfully.
- Killing, failure, dismissal, or other non-success terminal states do not satisfy the dependency.
- The wait is not permanently poisoned by a killed dependency. If the user later launches a new agent with the same
  waited-for name, that new agent's successful completion should satisfy the waiting agent.
- Existing duration-only and absolute-time `%wait` behavior should remain unchanged.

## Current Flow

1. `src/sase/axe/run_agent_phases.py::wait_for_dependencies()` writes `waiting.json` and polls for `ready.json`.
2. The `wait_checks` lumberjack chop runs `src/sase/scripts/sase_chop_wait_checks.py`.
3. `wait_checks` scans `waiting.json`, checks each name with:
   - `is_workflow_complete(name)` for workflow-name matches.
   - `find_named_agent(name)` otherwise.
4. `find_named_agent()` treats any artifact with `done.json` as `is_done=True` and preserves its `done.outcome`.
5. `wait_checks` only checks `agent.is_done`, so `outcome: "killed"` currently counts as satisfied.

## Design

Move the success policy into the wait-check resolution path, not into general name lookup.

`find_named_agent()` is used by other features where resolving killed, failed, or dismissed historical agents can still
be useful. Changing its generic `is_done` semantics would risk regressions in resume, display, dismissed bundles, and
reference lookup. Instead, `wait_checks` should explicitly ask: "Is there a currently matching dependency that has
completed successfully?"

The dependency resolver should behave as follows for each waited name:

- If a matching workflow exists:
  - Return unresolved while the workflow is still running.
  - Return resolved only if the relevant workflow/root completion outcome is successful.
  - Return unresolved for killed, failed, rejected, dismissed, or incomplete workflow states.
- If a matching named agent exists:
  - Return unresolved while a matching live agent is running.
  - Return resolved only when the newest matching terminal artifact has `done.json` with `outcome == "completed"`.
  - Return unresolved for terminal artifacts with non-success outcomes.
  - Keep scanning on later `wait_checks` ticks, so a newly launched same-name agent can supersede a killed/failed one
    once it completes successfully.
- If no matching agent exists:
  - Return unresolved.

This preserves the user's recovery path: after killing `foo`, `%wait:foo` remains waiting; when a new `foo` is launched
and writes `done.json` with `outcome: "completed"`, the next `wait_checks` tick writes `ready.json`.

## Implementation Steps

1. Add a small wait-specific dependency resolution helper near `sase_chop_wait_checks.py`.
   - It can stay local to the script unless tests or reuse suggest a tiny module.
   - It should read `done.json` outcomes and explicitly require `outcome == "completed"`.
   - It should not use dismissed-bundle fallback as a success signal.

2. For named-agent dependencies, avoid `find_named_agent(name).is_done` as the final condition.
   - Either call `find_named_agent(name)` only to detect live matches, then validate its outcome, or do a focused scan
     similar to existing name lookup.
   - Prefer the newest matching artifact so a later same-name run can satisfy the wait after an earlier killed/failed
     run.

3. For workflow-name dependencies, add success-aware handling.
   - Keep `is_workflow_complete(name)` unchanged for existing callers.
   - Add a wait-specific workflow check that distinguishes successful completion from terminal non-success.
   - Treat non-success workflow outcomes as unresolved, not satisfied.

4. Update `wait_checks` to write `ready.json` only when every dependency resolves successfully.
   - Continue skipping malformed `waiting.json`.
   - Continue leaving `ready.json` untouched when dependencies are unresolved.
   - Preserve existing logging and `resolved_deps` payload shape.

5. Add regression tests.
   - A waiting marker for `foo` is not resolved when the newest matching `foo` has `done.json` with `outcome: "killed"`.
   - A later same-name `foo` with `outcome: "completed"` resolves the wait.
   - A failed/killed workflow-name dependency does not resolve.
   - A successfully completed workflow-name dependency does resolve.
   - Existing success path for ordinary named agents still writes `ready.json`.

6. Run focused tests first, then the repository check command.
   - `pytest` for the new wait-check tests and any touched name-lookup tests.
   - Because this repo requires it after code changes: run `just install` if needed, then `just check`.

## Risks and Notes

- There may already be historical successful agents with the same name. The helper should prefer the newest matching
  artifact so a killed newer run is not accidentally satisfied by an older success.
- Dismissed bundles currently resolve through `find_named_agent()` with `outcome="dismissed"`. They should not satisfy
  `%wait`, because the requirement is successful completion.
- If an old non-success artifact remains the newest match and no replacement is ever launched, the waiting agent will
  keep waiting, matching the requested behavior.
- If users intentionally want to force a waiting agent to run, the existing TUI "run now" path writes `ready.json` with
  `unwait: true`; this plan does not change that manual override.
