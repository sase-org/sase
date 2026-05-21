---
create_time: 2026-05-21 14:04:52
status: done
prompt: sdd/prompts/202605/tale_approved_status_reconstruction.md
---
# Plan: Preserve Tale Approval Status During Code Handoff

## Problem

After a user approves a plan with the "tale" action, `sase ace` initially has enough information to show
`TALE APPROVED`. On refresh, the reconstructed agent rows show both the root plan-family entry and the active `1/1-code`
child as `RUNNING`.

The immediate notification path already maps a tale approval to `TALE APPROVED`, and the runner persists
`plan_action="tale"` in `agent_meta.json`. The regression is in the loader/status-reconstruction path: active follow-up
children are left with their raw execution status (`RUNNING`), and plan-family roots mirror the newest logical child.
Because the active code child remains `RUNNING`, the root also becomes `RUNNING`.

## Intended Behavior

- An active code follow-up for a normal approved plan should display as `PLAN APPROVED`.
- An active code follow-up for a tale-approved plan should display as `TALE APPROVED`.
- The root plan-family entry should mirror that approved handoff status while the code follow-up is active.
- Completed code follow-ups should keep the existing terminal behavior: `PLAN DONE` or `TALE DONE`.
- Higher-priority states such as `QUESTION`, failures, and non-code follow-ups should keep their current semantics.

## Implementation Strategy

1. Add a focused helper in `src/sase/ace/tui/models/_agent_status_overrides.py` for active approved-plan handoff rows.
   - It should recognize non-workflow follow-up children whose canonical suffix is the coder suffix.
   - It should only apply while the child is still actively executing, primarily when the child status is `RUNNING`.
   - It should return `TALE APPROVED` when either the parent or child has `plan_action == "tale"` or the parent already
     carries a tale-approved/tale-done status.
   - Otherwise it should return `PLAN APPROVED`.

2. Normalize active code follow-up child status before root mirroring.
   - Place this after question normalization, so a real blocked question remains `QUESTION`.
   - Place it before the completed handoff and root-mirroring passes, so the root mirrors
     `PLAN APPROVED`/`TALE APPROVED` instead of raw `RUNNING`.

3. Update regression tests.
   - Fix existing tests whose docstrings already describe `PLAN APPROVED`/`TALE APPROVED` but whose assertions currently
     expect `RUNNING`.
   - Add coverage that the active code child itself is relabeled, not just the parent.
   - Keep existing completed child tests for `PLAN DONE`/`TALE DONE` intact.

4. Verify with focused tests first, then run the repository check required by the workspace instructions.
   - Run targeted pytest for `test_agent_loader_status_override_tale.py`,
     `test_agent_loader_status_override_followups.py`, and `test_agent_loader_status_override_questions.py`.
   - Run `just install` if needed, then `just check` before finishing because source/test files changed.

## Risk

The main behavioral risk is accidentally relabeling active non-code work, such as epic or commit follow-ups. Keeping the
helper constrained to the canonical coder suffix avoids changing those paths. Another risk is masking active question
states; placing the normalization after unanswered-question handling and only changing `RUNNING` keeps `QUESTION`
precedence intact.
