---
create_time: 2026-03-30 16:03:35
status: done
---

# Plan: Prevent test pollution from creating phantom ChangeSpec COMMITS entries

## Problem summary

During agent execution, unit tests that call `CommitWorkflow.run()` can inherit runtime environment context
(`SASE_AGENT_PROJECT_FILE`, `SASE_AGENT_CL_NAME`) and unintentionally append real COMMITS entries to the active
ChangeSpec. This produces synthetic entries like `(2) test`, `(3) fix: bug`, `(3a) propose: new feature`, which then
causes the next real commit to be numbered `(4)`.

## Root-cause hypothesis

`CommitWorkflow.run()` always attempts to append a COMMITS entry for `create_commit` and `create_proposal` via
`_append_commits_entry()`. In tests that only verify dispatch/validation (not COMMITS persistence), this path is not
isolated. In an agent workspace, env vars point to a real project `.gp`, so mocked provider success triggers real file
mutation.

## Implementation plan

1. Reproduce and document the leak path in relevant tests.
   - Confirm which tests call `run()` with `create_commit`/`create_proposal` and do not stub `_append_commits_entry()`.
   - Map those payloads to observed phantom entries.

2. Isolate dispatch/changespec tests from COMMITS persistence side effects.
   - In `tests/test_commit_workflow_dispatch.py` and `tests/test_commit_workflow_changespec.py`, extend autouse fixtures
     to patch `CommitWorkflow._append_commits_entry` to a no-op (`None`) because these suites are not asserting COMMITS
     mutation behavior.
   - Keep existing provider dispatch assertions intact.

3. Add a targeted regression test.
   - Add a test ensuring `run()` dispatch still succeeds when `_append_commits_entry` is stubbed by fixture and does not
     require real ChangeSpec env context.
   - Keep scope narrow to avoid duplicating commit-entry unit coverage already present in
     `test_commit_workflow_artifacts.py`/`test_commit_add.py`.

4. Validate quality gates.
   - Run focused pytest for changed test modules.
   - Run full `just check` per repo instruction before finishing.

## Expected outcome

- Test runs no longer mutate active ChangeSpecs in agent contexts.
- Phantom COMMITS entries stop appearing.
- Real commit numbering remains contiguous and correct.
