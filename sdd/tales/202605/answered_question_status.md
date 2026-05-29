---
create_time: 2026-05-29 13:54:48
status: done
prompt: sdd/prompts/202605/answered_question_status.md
---
# Fix Answered Planner Question Status

## Context

The ACE snapshot shows a completed planner-phase agent row (`@i-plan`) still rendering as `QUESTION` even though a later
follow-up row (`@i-2`) exists and the question was answered. In the TUI loader, `QUESTION` can come from two places:

- active `pending_question.json` enrichment for rows that are currently blocked on user input
- relationship/status normalization in `src/sase/ace/tui/models/_agent_status_overrides.py`

The local reproduction points at the second path. A root plan-family row with `questions_times` and a later feedback
child (`-2`) produces a concrete planner child whose status is still `QUESTION`. The code path is
`_sync_planner_child_from_parent()` -> `_planner_child_status()`. That helper calls
`_has_unanswered_completed_question(parent)` before accounting for the existence of a later family follow-up child, so
legacy or incomplete question response metadata can keep the planner child looking blocked even after continuation.

## Goal

Show the planner phase as terminal (`DONE`) once the family has progressed to a follow-up continuation, while preserving
`QUESTION` for genuinely unanswered completed questions and for active pending-question markers.

## Plan

1. Add focused regression coverage in `tests/test_agent_loader_status_override_questions.py`.
   - Recreate the observed plan-family shape: root plan workflow, concrete planner child carrying `questions_times`, and
     a later `-2` follow-up child.
   - Assert that the concrete planner child becomes `DONE`, not `QUESTION`.
   - Keep existing tests for unanswered completed questions and answered `.q`/response-path cases intact.

2. Fix the planner-child normalization in `src/sase/ace/tui/models/_agent_status_overrides.py`.
   - Teach `_planner_child_status()` to treat an existing family follow-up child as evidence that the planner question
     was answered and continuation happened.
   - Keep active `parent.status == "QUESTION"` behavior for live pending-question markers.
   - Avoid relying only on `question_response_path`, because older artifacts or external answer flows can lack that
     metadata while still having the follow-up continuation.

3. Re-run focused tests around question and feedback status normalization.
   - `tests/test_agent_loader_status_override_questions.py`
   - `tests/test_agent_loader_status_override_feedback.py`

4. Run the required repository check after code changes.
   - Per `memory/short/build_and_run.md`, run `just install` first if needed, then `just check`.

## Risks

The main risk is incorrectly hiding an actually pending question if a stale or unrelated follow-up child exists. The fix
should use the existing family-parent relationship (`parent_timestamp`) rather than loose name matching, and should
continue to honor explicit active `QUESTION` state from pending-question enrichment.
