---
create_time: 2026-06-06 10:49:47
status: done
prompt: sdd/prompts/202606/wait_family_handoff.md
---
# Fix Wait-Check Resolution for Plan-Chain Handoff Artifacts

## Problem

Agent `33.r1.f1` exists in project `bob-cli` but remains `WAITING` even though the visible upstream agent `33.r1` is
`DONE`. Its runner wrote:

- `waiting.json` with `waiting_for: ["33.r1"]`
- no `ready.json`

The wait runner is doing what it is told: it blocks until the `wait_checks` chop writes `ready.json`. The failing piece
is the wait dependency resolver used by `src/sase/scripts/sase_chop_wait_checks.py`.

## Evidence

A read-only check using the current resolver against the live `bob-cli` artifacts produced:

- `named: _WaitCandidate(timestamp='20260606094012', is_resolved=True)`
- `workflow: _WaitCandidate(timestamp='20260606094012', is_resolved=False)`
- `family: _FamilyCandidate(timestamp='20260606100411', is_resolved=False)`
- `resolved: False`

The `33.r1` family contains:

- `20260606094012`: `33.r1`, root, `done.json` outcome `completed`
- `20260606095139`: `33.r1--2`, feedback/plan-review phase, no `done.json`
- `20260606100411`: `33.r1--code`, code phase, `done.json` outcome `completed`

The resolver chooses the latest candidate among named/workflow/family resolution paths. Although the named root is
resolved, the newer family candidate is unresolved because `33.r1--2` lacks a successful `done.json`.

## Root Cause

`_WaitDependencyIndex.family_candidate()` currently treats every family artifact in the root generation as a terminal
agent that must have `done.json` outcome `completed`.

That assumption is false for plan-chain handoff phases. Feedback/question/planner handoff artifacts can be finalized via
`workflow_state.json` and metadata, then superseded by later phases, while only the final active phase writes the
runner's terminal `done.json`. Those completed handoff artifacts should not keep a family dependency unresolved after
the family has progressed to a completed terminal phase.

## Implementation Plan

1. Reproduce the bug in `tests/test_axe_chop_wait_checks.py` with a fixture matching the live state: a root family
   artifact with completed `done.json`, an intermediate feedback artifact with `workflow_state.json` completed but no
   `done.json`, and a completed `--code` child. Assert that a waiter on the family receives `ready.json`.

2. Update `src/sase/scripts/sase_chop_wait_checks.py` so family/workflow dependency resolution distinguishes:
   - successful terminal artifacts: `done.json` outcome `completed`
   - completed handoff artifacts: plan-chain metadata plus completed `workflow_state.json` and no failure marker
   - unresolved or failed artifacts: missing completion evidence, non-completed workflow state, or failed/killed
     `done.json`

3. Keep failure semantics conservative:
   - a failed or killed child still blocks the family
   - a live/running child without completed workflow state still blocks the family
   - non-plan-chain artifacts without `done.json` remain unresolved

4. Add focused tests for:
   - the live regression shape resolves
   - failed/killed plan-family children still block
   - running/incomplete handoff artifacts still block

5. Validate with the focused wait-check tests first, then run `just install` and `just check` as required by the project
   instructions after code changes.

6. After validation, unblock the current `33.r1.f1` wait:
   - verify `sase agents status -a -j` still reports it as `WAITING`
   - let the waits lumberjack tick with the installed fix or run the wait-check chop once if needed
   - confirm `ready.json` is written or `waiting.json` is removed, and `33.r1.f1` transitions out of `WAITING`

## Risks

The main risk is over-resolving a family while a real child is still running. The fix should avoid that by only treating
a missing-`done.json` artifact as resolved when it is clearly a plan-chain handoff artifact with completed workflow
state.
