---
create_time: 2026-05-14 23:06:01
status: done
prompt: sdd/prompts/202605/tui_slowdown.md
---
# Plan: Diagnose and Fix Current ACE TUI Slowdown

## Context

The visible symptom is that `sase ace` feels extremely slow, but live process inspection points at AXE background chops
saturating CPU rather than a Textual render loop alone.

Observed evidence:

- `sase_chop_wait_checks` and `sase_chop_workflow_checks` are repeatedly running at about 100% CPU.
- `wait_checks` is configured for a 10 second interval, but recent runs take roughly 45-55 seconds.
- `workflow_checks` is configured inside the 5 second `hooks` lumberjack, but recent runs take roughly 30-40 seconds.
- Current wait-check logs show about `projects=22 artifacts=11256 waiting=83 unresolved=78`.
- Current workflow-check logs show `changespecs=2003 updates=0 started=0`.

The practical result is that AXE keeps launching expensive background work faster than those chops can complete. That
loads the machine and the same SASE state files that the TUI also needs to read, so the UI feels globally sluggish.

## Root Cause Hypothesis

### `wait_checks`

`src/sase/scripts/sase_chop_wait_checks.py` resolves each dependency by calling `_is_wait_dependency_resolved()`. That
function calls both `_find_latest_workflow_dependency()` and `_find_latest_named_dependency()`, and each of those walks
all `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` entries. With 78 unresolved waiting markers and 11k+
artifact directories, one tick can do hundreds of thousands to millions of JSON/file operations.

This is an algorithmic issue: dependency lookup is effectively `O(waiting_dependencies * artifacts)`.

### `workflow_checks`

`src/sase/ace/scheduler/workflows_runner/starter.py:start_stale_workflows()` calls `count_agent_runners_global()` before
checking whether the current ChangeSpec has any CRS, fix-hook, or summarize-hook workflow eligible to start.
`count_agent_runners_global()` reparses/scans all project ChangeSpecs. Since `workflow_checks` invokes
`start_stale_workflows()` for every filtered ChangeSpec, the current no-op tick still does roughly
`O(changespecs * all_project_scan)`.

This is also algorithmic: the expensive global concurrency count should only happen after local eligibility proves that
there is something to start.

## Implementation Plan

1. Optimize `wait_checks` dependency resolution.
   - Build one in-memory index from a single artifact scan per chop run.
   - Index latest named-agent candidates by `agent_meta.name`.
   - Index workflow candidates by `agent_meta.workflow_name`, preserving the current semantics:
     - use the newest root workflow artifact when roots exist;
     - require the root `done.json` outcome to be `"completed"`;
     - require all children for that root to have successful done outcomes;
     - keep the legacy fallback for workflow-name-only child artifacts with no root.
   - Resolve all `waiting_for` names against that index instead of rescanning disk per dependency.
   - Preserve the existing summary fields and `ready.json` write behavior.

2. Optimize `workflow_checks` no-op ticks.
   - In `start_stale_workflows()`, compute CRS, fix-hook, and summarize-hook eligible lists before calling
     `count_agent_runners_global()`.
   - Return immediately when all three eligible lists are empty.
   - Reuse the precomputed eligible lists in the subsequent start loops so behavior stays consistent and work is not
     duplicated.
   - Keep completion checking unchanged, since running workflow completion detection is separate from starting stale
     workflows.

3. Add focused regression coverage.
   - Add/extend `tests/test_axe_chop_wait_checks.py` to prove multiple waiting markers/dependencies do not trigger
     repeated full artifact scans, while retaining named-agent and workflow dependency behavior.
   - Add a workflow starter regression test proving `count_agent_runners_global()` is not called when a ChangeSpec has
     no eligible workflow entries.
   - Keep tests narrow; this is a hot-path algorithm change, not a UI rendering change.

4. Verify locally.
   - Run the targeted wait-check and workflow-check tests.
   - Run the optimized `wait_checks` script against the current real context with `PYTHONPATH=src` and compare runtime
     and summary against the previous behavior.
   - Run `just install` if needed, then `just check` before final response because this repo requires it after file
     changes.

## Expected Outcome

`wait_checks` should drop from tens of seconds per tick to a single artifact scan plus cheap map lookups.
`workflow_checks` should avoid global runner recounts on no-op ticks and stop burning CPU across thousands of
ChangeSpecs. Together, the AXE background processes should stop monopolizing CPU, which should remove the current
TUI-wide sluggishness.
