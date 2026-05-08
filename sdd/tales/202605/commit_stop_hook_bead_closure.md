---
title: Commit Stop Hook Bead Closure Ordering
create_time: 2026-05-07 23:42:10
status: done
prompt: sdd/prompts/202605/commit_stop_hook_bead_closure.md
---

# Commit Stop Hook Bead Closure Ordering

## Context

The commit stop hook blocks an agent when uncommitted changes remain at the end of a response. When `SASE_BEAD_ID` is
set, the hook currently tells the agent to use the resolved commit skill first and then run `sase bead close <id>`
afterward. That ordering leaves the bead closure outside the commit that the hook asked the agent to create.

The hook cannot prove ownership of the dirty files from VCS state alone. Its user-facing contract must therefore make
the ownership gate explicit: the agent should act only when it made the detected changes, and should ignore the warning
when the changes belong to the user or another agent.

## Plan

1. Update `src/sase/scripts/sase_commit_stop_hook.py` so `_build_commit_instruction_message()` expresses the workflow
   as:
   - first decide whether the listed uncommitted changes were made by the current agent;
   - if not, ignore the warning for the session;
   - if yes and `SASE_BEAD_ID` is set, run `sase bead close <id>` before invoking the commit skill;
   - then use the resolved commit skill with the existing commit-method guidance.

2. Preserve existing behavior that omits all bead-close wording when no bead ID is available, and preserve the method
   override warning for `create_commit`, `create_proposal`, and `create_pull_request`.

3. Add or adjust focused tests in `tests/test_commit_stop_hook.py` to pin the corrected contract:
   - bead closure appears before the commit-skill instruction;
   - bead closure is explicitly gated on the agent having made the detected changes;
   - blank bead IDs still omit bead-close instructions;
   - existing non-PR and PR commit-message scope behavior remains intact.

4. Run focused verification:
   - `uv run pytest tests/test_commit_stop_hook.py`
   - any directly affected init-skills or commit-skill tests only if the implementation touches generated skill sources.

5. Run repo verification after source edits:
   - `just install` if needed for this workspace;
   - `just check`.

## Out of Scope

- Do not add automatic provenance detection for dirty files; VCS status does not identify whether the current agent,
  another agent, or the user made a change.
- Do not edit generated installed skill files directly. If generated skill source files become part of the fix, update
  only `src/sase/xprompts/skills/` and follow the generated-skill workflow.
