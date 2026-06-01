---
create_time: 2026-06-01 10:26:29
status: done
prompt: sdd/prompts/202606/epic_created_status_1.md
---
# Fix Epic Follow-Up Terminal Statuses

## Context

The `sase ace` snapshot shows an agent family root `@bqu` and its `@bqu-epic` follow-up both displayed as `DONE` after
the epic bead was created. The expected display status is `EPIC CREATED` for the completed epic follow-up, and because
agent-family roots mirror their newest logical child, the `@bqu` root should also display `EPIC CREATED`.

I verified the live artifacts under:

- `~/.sase/projects/bob-cli/artifacts/ace-run/20260601100300`
- `~/.sase/projects/bob-cli/artifacts/ace-run/20260601100641`

The family root has `plan_action: "epic"`, `plan_chain_root: true`, and `agent_family: "bqu"`. The follow-up child has
`role_suffix: "-epic"`, `agent_family_role: "epic"`, `parent_timestamp: "20260601100300"`, and a completion timestamp.
The loader correctly identifies the parent/child relationship, but the status override pass only special-cases completed
`-code` and feedback follow-ups. Completed `-epic` follow-ups remain plain `DONE`, so root mirroring propagates `DONE`.

## Root Cause

`src/sase/ace/tui/models/_agent_status_overrides.py` normalizes completed approved-plan handoff children through
`_is_completed_plan_handoff_child()` and `_done_handoff_status()`, but that logic only covers:

- coder follow-ups (`-code` / legacy `.code`)
- answered feedback follow-ups (`-2`, `.2`, etc.)

Epic follow-ups (`-epic` / legacy `.epic`) are handled only for timestamp propagation (`parent.epic_time`) and are never
converted from raw loader status `DONE` to the semantic terminal status `EPIC CREATED`. The later family-root mirroring
step is working as designed; it is mirroring the wrong child status.

There are already tests whose names/docstrings describe the desired `EPIC CREATED` behavior, but their assertions still
expect `DONE`. Those tests did not catch the regression because their expectations encode the bug.

## Implementation Plan

1. Add explicit completed-epic follow-up normalization in `_agent_status_overrides.py`.
   - Detect canonical `PLAN_CHAIN_EPIC_SUFFIX` for family follow-up children.
   - When such a child completes with `DONE`, set its display status to `EPIC CREATED`.
   - Keep failed epic follow-ups as `FAILED` so root mirroring continues to surface failure.
   - Run this before follow-up attachment and root mirroring so the root picks up `EPIC CREATED` naturally.

2. Keep the existing code/tale handoff behavior intact.
   - Preserve `-code` completed mapping to `PLAN DONE` / `TALE DONE`.
   - Preserve feedback-child handling and question normalization order.
   - Avoid changing loader, artifact schema, or Rust scanner behavior; this is a TUI display-status normalization issue
     in the existing Python status override layer.

3. Update regression tests.
   - Change the existing completed epic follow-up tests to assert both child and parent become `EPIC CREATED`.
   - Add or adjust coverage for the exact `plan_action="tale"` case from the existing tale regression test so epic
     completion wins over the tale branch.
   - Leave failed-epic and newer-code-wins coverage intact so status precedence remains explicit.

4. Verify with targeted tests first, then the repo check.
   - Run the focused status override tests:
     `pytest tests/test_agent_loader_status_override_followups.py tests/test_agent_loader_status_override_tale.py`.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Expected Result

After the change, a completed epic follow-up row like `@bqu-epic` displays `EPIC CREATED`. Since the family root mirrors
its newest logical child after normalization, `@bqu` also displays `EPIC CREATED` without adding a separate
root-specific override.
