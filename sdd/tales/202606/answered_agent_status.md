---
create_time: 2026-06-15 16:11:45
status: done
prompt: sdd/prompts/202606/answered_agent_status.md
---
# Plan: ANSWERED agent status for answered questions

## Goal

Add a transient `ANSWERED` status for rows in the `sase ace` Agents tab when an agent asked a user question and the user
has already written the corresponding answer, but the agent has not yet visibly progressed past the question state.

Today the UI can show `QUESTION` until the runner consumes `question_response.json` and removes `pending_question.json`.
The desired behavior is:

- `QUESTION`: the agent is blocked and still needs user input.
- `ANSWERED`: the user already answered; the agent/runner is expected to resume or finish shortly.
- Once a fresh load shows real progress or a terminal state, `ANSWERED` should clear and the normal status should show.

## Status Semantics

Treat `ANSWERED` as an active/progress state, not an input-needed state.

- It should not be in `AGENT_ASKING_STATUSES`, `_STOPPED_STATUSES`, `_NEEDS_INPUT_STATUSES`, `DISMISSABLE_STATUSES`, or
  resumable done statuses.
- BY_STATUS grouping should place it in the `Running` bucket.
- `attention:true` and `needs:input` queries should not match it.
- Runtime suffix behavior should match active rows where possible: if the agent has a `run_start_time`, the row can keep
  ticking rather than showing the user-paused hand marker.
- It should not enable "answer question" affordances or stopped/input counts.

## Implementation Shape

1. Add an `ANSWERED` status constant or locally consistent literal usage near the existing TUI-facing status helpers,
   depending on the prevailing style in the touched module.

2. Update question-marker enrichment:
   - In filesystem-backed enrichment, when `pending_question.json` exists for an active row, parse the marker enough to
     find `request_path`.
   - If the sibling `question_response.json` exists, set `agent.status = "ANSWERED"`; otherwise keep the current
     `QUESTION` behavior.
   - Mirror the same logic in wire/snapshot enrichment using `PendingQuestionMarkerWire.request_path`.
   - Keep this work inside loader/enrichment paths, which already run off the Textual event loop.

3. Update immediate TUI response handling:
   - After `UserQuestionModal` successfully writes `question_response.json`, set the matched agent's in-memory override
     to `ANSWERED` instead of restoring the pre-question status immediately.
   - Pop the stale `_agent_pre_question_status` entry at that point; it is no longer needed to display the transient
     answered state.
   - Preserve the existing notification dismissal behavior.
   - Cover both normal notification-driven question handling and the dismissed-notification fallback that opens from
     `pending_question.json`.

4. Update override reconciliation:
   - Ensure an `ANSWERED` override applies over a loader-produced `QUESTION` row while `pending_question.json` is still
     present.
   - Clear an `ANSWERED` override when the fresh loaded row reaches a progress status such as `RUNNING`,
     `PLAN APPROVED`, `TALE APPROVED`, `EPIC APPROVED`, `LEGEND APPROVED`, `PLAN COMMITTED`, or any dismissable terminal
     state.
   - Keep the existing stale-override safeguards and precomputed finalize-plan invalidation behavior.

5. Add distinct Agents-row highlighting:
   - Add an explicit `ANSWERED` branch to `src/sase/ace/tui/widgets/_agent_list_render_agent.py`.
   - Use a color that is visually separate from `QUESTION` amber, `RUNNING` gold, and approved-plan teal; proposed
     style: bold bright cyan/azure such as `bold #5FD7FF`.
   - Update adjacent status displays that share Agents context, such as workflow detail or zoom/jump modals, only where
     they would otherwise fall back to generic dim text.

6. Keep behavior local to the TUI/Python agent-loader layer.
   - This change does not require new CLI flags or keymaps.
   - It should not require Rust core changes unless implementation reveals that daemon-backed provider snapshots already
     derive pending-question status in Rust. If that appears during implementation, update the Rust wire/API
     consistently rather than creating divergent frontend behavior.

## Tests

Add or update focused tests:

- Pending-question enrichment:
  - active row + `pending_question.json` + no response file -> `QUESTION`;
  - active row + `pending_question.json` + `question_response.json` -> `ANSWERED`;
  - same behavior for wire/snapshot enrichment.

- Modal response handling:
  - answering a `UserQuestion` writes the response, dismisses the notification, and sets the agent override to
    `ANSWERED`;
  - marker fallback also sets `ANSWERED` for the corresponding selected/matched agent.

- Override finalization:
  - `ANSWERED` override applies over loaded `QUESTION`;
  - `ANSWERED` clears when loaded status progresses to `RUNNING` or a terminal status.

- Status semantics:
  - BY_STATUS bucket for `ANSWERED` is `Running`;
  - `needs:input` and `attention:true` do not match `ANSWERED`.

- Rendering:
  - formatted Agents row includes `ANSWERED` with the explicit non-dim style.
  - Add/update PNG visual snapshots only if existing snapshot coverage exercises this status; otherwise keep this to
    unit-level rendering tests.

## Verification

After implementation:

1. Run targeted pytest for the changed areas, likely:
   - `pytest tests/test_enrich_agent_pending_question.py tests/test_plan_rejection_response.py tests/test_agents_tab_finalize_plan.py tests/test_agent_query_evaluator.py tests/ace/tui/models/test_agent_groups_grouping_mode_status.py tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
2. Because this repo requires it after file changes, run `just install` if needed, then `just check`.
