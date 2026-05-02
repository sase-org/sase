---
create_time: 2026-03-29 17:54:14
status: done
---

# Fix missing PLAN drawer for workflow-created ChangeSpecs

## Context

Some ChangeSpecs created by coder-agent workflows include an initial synthetic COMMITS entry like
`(1) [run] Initial Commit` with CHAT/DIFF drawers but no `| PLAN:` drawer, even when the run involved an approved plan.

## Diagnosis strategy

1. Trace all code paths that create COMMITS entries and compare plan propagation behavior.
2. Confirm whether parser/rendering is broken vs. writer omission.
3. Validate whether workflow-created ChangeSpecs use a distinct writer that drops plan metadata.

## Findings to validate

- Parsing/rendering already supports `| PLAN:`.
- `add_commit_entry_with_id` and `add_proposed_commit_entry` already accept `plan_path`.
- `create_changespec_for_workflow` -> `add_changespec_to_project_file(initial_commits=...)` currently does not carry
  plan path in tuple shape, so synthetic initial commits cannot render PLAN.

## Implementation plan

1. Extend `add_changespec_to_project_file` initial commit tuple handling to accept optional `plan_path` (without
   breaking existing tuple formats).
2. In `create_changespec_for_workflow`, derive display-ready plan path from `SASE_PLAN` (HOME-shortened like other
   paths) and pass it in `initial_commits` when present.
3. Add/adjust focused tests in `tests/workspace_provider/test_changespec.py` and/or
   `tests/workflows/commit/changespec_operations` to assert PLAN propagation for workflow-created ChangeSpecs while
   preserving existing behavior when absent.
4. Run targeted tests for changed modules, then run full `just check` per repo instructions.

## Risks and mitigations

- Risk: tuple positional compatibility break for existing callers/tests.
  - Mitigation: parse by optional trailing elements and preserve existing first four positions.
- Risk: inconsistent path formatting (`~` vs absolute).
  - Mitigation: keep current display convention by shortening HOME-prefixed plan path before writing drawer.
