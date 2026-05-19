---
create_time: 2026-05-19 08:00:23
status: done
prompt: sdd/prompts/202605/agent_family_status_fix_1.md
---
# Plan: Agent Family Question and Done Status Fix

## Goal

Fix the agent-family status model so completed family continuations that followed an answered question do not remain
stuck as `QUESTION`, and so the root family row mirrors the corrected newest child status. The concrete regression
target is the historical `aj5` family from the `sase ace` snapshot: the root row and newest child row should display
`PLAN DONE`, not `PLAN APPROVED` or `QUESTION`.

## Requirements Checked

The original `sdd/prompts/202605/agent_families_2.md` prompt and the `sase-3r` epic plan establish these invariants:

- The root row name remains the stable family name, such as `aj5`.
- Child/phase rows use family names such as `aj5-plan`, `aj5-code`, and numeric continuations.
- The root row status always equals the most recently launched child row status.
- `QUESTION` should represent a row blocked on user input, not a completed continuation after the input was answered.

The `aj5` artifacts show that the latest continuation, `aj5-5`, has both `questions_submitted_at` and
`question_response_path`. That means the user answered the question and this row is the resumed work, so the current
`DONE -> QUESTION` heuristic is too broad.

## Implementation Plan

1. Preserve question response metadata in the TUI agent model.
   - Add `question_request_path`, `question_response_path`, and `question_session_id` fields to `Agent`.
   - Populate them in both filesystem and wire metadata enrichment paths so indexed and direct scans behave the same.

2. Narrow the completed-question heuristic.
   - Replace the raw `questions_times and no followup` test with a helper that only marks a completed row as `QUESTION`
     when no follow-up exists and no `question_response_path` was recorded.
   - Keep the existing `pending_question.json` handling as the authoritative active-row signal.

3. Restore terminal plan-family labels on completed handoff rows.
   - Normalize completed family follow-up rows from plain `DONE` to `PLAN DONE` or `TALE DONE` when they represent a
     completed approved-plan handoff.
   - Keep active rows mirrored as `RUNNING` and failed rows mirrored as `FAILED`.
   - Keep the root status mirror as the last step after child statuses are normalized.

4. Add focused regression tests.
   - Cover answered vs unanswered completed questions.
   - Cover a completed numeric continuation with `question_response_path` becoming `PLAN DONE`.
   - Cover root mirroring of the newest corrected child status.

5. Verify.
   - Run the focused status override tests first.
   - Run `just check` because this repo requires it after code changes.
   - Launch `sase ace --tmux`, emulate navigation/search as needed, and capture the tmux pane to verify the `aj5` root
     and latest child display `PLAN DONE`.
