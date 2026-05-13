---
create_time: 2026-05-13 15:35:54
status: done
prompt: sdd/prompts/202605/jump_to_stopped_cleanup.md
---
# Plan: Clean Up Stopped-Agent Jump Implementation

## Goal

Review and polish the existing `,J` stopped-agent navigation fix without changing its product behavior. The current
implementation appears behaviorally correct: `,J` now follows the shared `Stopped` status bucket, command availability
tracks stopped rows separately from unread completed rows, and tests cover `PLAN` / `QUESTION` rows versus `DONE` /
`FAILED` rows.

The remaining issue is mostly code clarity. Some names and module boundaries still reflect the old implementation, where
the stopped jump reused completed/unread semantics.

## Current Assessment

What is good and should be preserved:

- The stopped predicate delegates to `status_bucket_for_values()`, so the keybinding matches the Agents tab's visible
  `▲ Stopped` bucket instead of duplicating `PLAN` / `QUESTION` status lists.
- `,j` and `,J` are now separate concepts:
  - `,j` targets unread completed/dismissable rows and acknowledges notifications.
  - `,J` targets stopped rows and does not mutate unread or notification state.
- Command palette availability uses a separate `stopped_agent_count`, which keeps palette visibility aligned with the
  actual `,J` behavior.
- The focused tests cover stopped recency ordering, wrapping, panel focus, and ignoring non-stopped terminal rows.

Cleanup opportunities:

- `_jump_to_next_completed_agent()` is now a generic visible-row jump helper, but its name and docstring still say
  "completed". That makes the `,J` call site look like a special case bolted onto completed-agent behavior.
- `is_stopped_agent_status()` lives in `_unread.py`, even though stopped status semantics are used by command context
  extraction as well as unread/navigation code. That makes the command system import status helpers through the Agents
  action mixin layer.
- The stopped-jump tests still seed `_unread_completed_agent_ids` in one case even though stopped jumping no longer
  reads that state. The assertion is useful, but the setup can be clearer if it proves the state is untouched without
  implying it is required.

## Implementation Plan

1. Add a neutral TUI agent-status semantics module.
   - Create a small module under `src/sase/ace/tui/models/` for TUI-facing agent status predicates.
   - Move or expose `DISMISSABLE_STATUSES`, `is_unread_completed_status(status)`, and `is_stopped_agent_status(status)`
     there.
   - Keep existing imports from `actions/agents/_loading_helpers.py` and `actions/agents/_core.py` working by
     re-exporting the moved names, so this remains a low-risk cleanup rather than a broad import migration.

2. Update direct consumers to use the neutral module where it matters.
   - `commands/context.py` should import the predicates from the neutral status module instead of importing through
     `actions.agents._core`.
   - `_unread.py` should import the same predicates, while keeping stopped jump timing local because that timing is a
     navigation policy, not a generic status predicate.
   - Avoid changing unrelated `DISMISSABLE_STATUSES` imports unless the compatibility re-export makes the change obvious
     and mechanical.

3. Rename the generic jump helper.
   - Rename `_jump_to_next_completed_agent()` to a name that describes what it actually does, such as
     `_jump_to_next_matching_agent_by_time()`.
   - Update its docstring and local variable names from "completion time" to "jump time" or "recency time".
   - Keep `_jump_to_next_unread_done_agent()` and `_jump_to_next_stopped_agent()` as the two public behavior-specific
     wrappers.

4. Tighten tests without broadening behavior.
   - Adjust tests only where the new module boundary or helper name affects imports.
   - Remove misleading stopped-test setup that populates `_unread_completed_agent_ids` solely for stopped navigation, or
     rewrite it as an explicit "unread state is ignored/preserved" assertion.
   - Keep the existing behavior coverage for `PLAN`, `QUESTION`, `DONE`, `FAILED`, recency ordering, wrapping, panel
     focus, command availability, and command context extraction.

5. Validate.
   - Run the focused suite:

     ```bash
     .venv/bin/pytest tests/ace/tui/test_agent_unread_navigation.py tests/test_command_availability.py tests/test_command_palette_wiring.py
     ```

   - Because this repository requires full validation after code changes, run:

     ```bash
     just install
     just check
     ```

## Non-Goals

- Do not change which statuses belong to the `Stopped`, `Done`, or dismissable sets.
- Do not move shared backend status bucket behavior out of `sase.agent.status_buckets`.
- Do not change keybindings, footer labels, notification acknowledgement behavior, or command catalog labels.
- Do not refactor broader agent cleanup, dismissal, or loading behavior.

## Acceptance Criteria

- `,J` behavior remains unchanged from the approved fix: it cycles visible stopped rows by stopped recency and does not
  acknowledge notifications.
- `,j` behavior remains unchanged: it cycles unread completed rows and acknowledges the selected row.
- Command context and command availability still distinguish stopped rows from unread completed rows.
- The implementation reads cleanly: stopped status predicates live outside the unread mixin, and the shared jump helper
  no longer carries completed-only naming.
- Focused tests and `just check` pass after implementation.
