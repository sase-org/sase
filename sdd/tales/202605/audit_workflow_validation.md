---
create_time: 2026-05-12 15:46:31
status: done
prompt: sdd/prompts/202605/audit_workflow_validation.md
---
# Fix audit workflow validation failures

## Problem

The `ace(run)` workflow fails before execution with:

```
Workflow 'sase/audit_recent_bugs' validation failed:
  - Step 'launch_bug_audit_agent' has output 'launched', 'launched_agent_name' but is never referenced
```

The same pattern exists in `xprompts/audit_recent_improvements.yml`.

The workflow validator intentionally rejects non-final steps that declare outputs but are never consumed by later steps.
This catches stale output declarations and misspelled template references. `xprompts/refresh_docs.yml` already follows
the intended pattern by using the launch step's `launched` output in the marker-update condition.

## Approach

1. Keep the validator behavior intact. The validator has explicit coverage for unused outputs, and the current error is
   a valid application of that rule.

2. Fix the bundled audit workflows. Update the marker steps in:
   - `xprompts/audit_recent_bugs.yml`
   - `xprompts/audit_recent_improvements.yml`

   Their marker update conditions should require both:
   - the commit threshold condition, and
   - the corresponding launch step reporting `launched > 0`

   This mirrors `refresh_docs.yml` and prevents marker advancement unless the launch step actually completed.

3. Remove or narrow unneeded declared output fields if they are not part of the workflow contract. `launched_agent_name`
   is printed for operator visibility, but no workflow step uses it. If no later logic needs it, do not declare it as
   structured output.

4. Add regression coverage for the bundled workflows. Add focused tests that load the real `audit_recent_bugs.yml` and
   `audit_recent_improvements.yml` files and assert `validate_workflow()` accepts them. This catches future drift
   between checked-in workflows and validator rules.

5. Verify. Run the focused workflow validation tests first, then run `just install` if needed and `just check` as
   required by the repository instructions after source changes.

## Expected result

`#!sase/audit_recent_bugs` and `#!sase/audit_recent_improvements` should validate before execution. The marker files
should only advance after the audit-launch step succeeds, and the validator's unused-output guard should remain active
for real workflow mistakes.
