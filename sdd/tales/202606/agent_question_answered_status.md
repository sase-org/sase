---
create_time: 2026-06-17 08:11:28
status: done
prompt: sdd/prompts/202606/agent_question_answered_status.md
---
# Plan: Fix Answered Question Agent Status

## Problem

In the Agents tab screenshot, `92.f1--code` still displays `QUESTION` after the corresponding user question has already
been answered. The real artifacts show:

- The question notification was written at `2026-06-17 08:00:05` for `agent_timestamp=20260617074954` and
  `agent_root_timestamp=20260617070857`.
- The response exists at `/home/bryan/.sase/user_question/0f39a143-3de1-482d-93eb-6e23cf10af5d/question_response.json`.
- The follow-up artifact `92.f1--code-0` has `question_request_path`, `question_response_path`, and
  `question_session_id`.
- The interrupted artifact `92.f1--code` has `questions_submitted_at` but is missing the response metadata.

The source-level root cause is in `record_workflow_metadata()`: `handle_questions_marker()` passes
`question_request_path`, `question_response_path`, and `question_session_id`, but the allow-list in
`record_workflow_metadata()` drops those fields. That leaves the interrupted row looking like a completed question with
no answer. The TUI status override path can then keep or re-derive `QUESTION` for the asking row even though the answer
and continuation exist.

## Goals

1. Persist question response metadata on the artifact that originally asked the question.
2. Ensure the TUI does not keep a stale `QUESTION` override once an answer is visible through the interrupted row or a
   same-family continuation.
3. Preserve the current transient `ANSWERED` behavior while the runner has seen the response but has not fully moved
   past the question handoff.
4. Keep TUI refresh work inside the existing loader/finalize paths; do not add synchronous filesystem work to Textual
   event handlers.

## Proposed Changes

1. Update question metadata persistence.
   - Extend `record_workflow_metadata()` to retain `question_request_path`, `question_response_path`, and
     `question_session_id`.
   - This makes the interrupted artifact self-describing and prevents completed question rows from being classified as
     unanswered.

2. Add targeted tests for the runner metadata handoff.
   - Cover `handle_questions_marker()` or `record_workflow_metadata()` behavior so the original/interrupted artifact
     receives all question metadata after a response.
   - Keep the test focused on persisted metadata, not UI rendering.

3. Strengthen TUI stale override reconciliation.
   - Add a pure helper in the finalize path that recognizes when a `QUESTION` override has been superseded by loaded
     answer metadata or by a newer same-family continuation with `question_response_path`.
   - Apply the same logic in both the worker-computed finalize plan and the synchronous fallback path so behavior stays
     identical.
   - Avoid disk reads; operate only on loaded `Agent` objects already produced by the loader.

4. Add TUI finalize tests.
   - Reproduce the screenshot shape: an original code child with a stale `QUESTION` override and a newer same-family
     continuation carrying `question_response_path`.
   - Assert the stale `QUESTION` override is removed or replaced with the correct answered/progress state, and that
     `_agent_pre_question_status` is cleaned up.
   - Keep existing behavior where an explicit `ANSWERED` override beats a loader-produced `QUESTION` row until progress
     is observed.

5. Verify.
   - Run focused tests for question metadata, pending-question enrichment, and agent finalize override behavior.
   - Run `just install` if needed, then `just check` because implementation files will be changed.

## Risks And Tradeoffs

- The safest source fix is persisting the response metadata on the interrupted artifact. It corrects historical
  classification without requiring the TUI to infer too much from sibling rows.
- The TUI reconciliation helper should remain narrow: only clear `QUESTION` overrides when the loaded graph proves the
  question was answered. Broadly clearing question overrides on any family activity could hide real unanswered
  questions.
- If existing tests expect completed answered code rows to become `PLAN DONE` or `TALE DONE`, keep that terminal
  normalization unless the product requirement is explicitly that answered question rows remain visibly `ANSWERED`
  forever.
