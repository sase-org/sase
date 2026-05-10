---
create_time: 2026-05-01 23:54:47
status: done
prompt: sdd/prompts/202605/tale_approval_labels.md
---
# Plan: Rename Normal Approval CTA to Tale

## Goal

Change the user-facing normal plan approval control from "Approve" to "Tale" in:

- ACE TUI plan review flow in this repo.
- Telegram plan approval messages in `../sase-telegram`.
- Google Chat plan approval messages in `../retired chat plugin`.

This should align the normal approval action with the new SDD artifact name: normal approved plans are tales, while
alternate plan actions remain Run, Epic, Legend, Reject, and Feedback.

## Key Findings

- The internal action name is still `approve` across the main repo and chat integrations.
- Telegram and Google Chat both serialize the normal action as payload/action `approve` in `plan_response.json`.
- SASE's runner, tests, auto-approve path, and legacy `commit` compatibility expect the internal action to remain
  `approve`.
- The requested change should therefore be presentation-only: labels and current docs/tests that describe those labels.
- Historical SDD files and unrelated `%approve` directive documentation should not be swept. `%approve` is an autonomy
  directive, not the plan review button.

## Scope

### Main SASE repo: TUI

Update the current plan review UI copy:

- `src/sase/ace/tui/modals/plan_approval_modal.py`
  - Binding label for `a` from `Approve` to `Tale`.
  - Footer hint from `a=Approve` to `a=Tale`.
  - Keep `action_approve()` and `PlanApprovalResult(action="approve")` unchanged.

Update the options dialog copy so it does not keep a stale "Approve" label next to the new "Tale" CTA:

- `src/sase/ace/tui/modals/approve_options_modal.py`
  - Binding label for Enter from `Approve` to `Tale`.
  - Title from `Approve with Options` to `Tale Options` or `Tale with Options`.
  - Footer hint from `enter=Approve` to `enter=Tale`.
  - Keep class names, dataclasses, method names, and result types unchanged to avoid a broad internal refactor.

Update current docs/tests that describe the TUI controls:

- `docs/ace.md`
  - Plan approval keybinding table: `a` becomes "Tale the plan" or "Save as tale and continue".
  - `A` description and options section should use the new user-facing term without changing internal behavior.
- Add or update lightweight tests in `tests/test_plan_approval_modal_title.py` and/or
  `tests/test_approve_options_modal.py` to assert the display labels changed while internal actions still return
  `approve`.

### Telegram plugin

Update the current plan approval button label:

- `../sase-telegram/src/sase_telegram/formatting.py`
  - First plan approval button from `✅ Approve` to `📖 Tale`.
  - Keep callback payload `approve` unchanged.

Update label expectations and docs:

- `../sase-telegram/tests/test_formatting.py`
  - Expect the first button text to contain `Tale`, while callback data still ends in `:approve`.
- `../sase-telegram/README.md`
- `../sase-telegram/docs/outbound.md`
  - Replace current button lists that say `Approve / Run / Epic / Legend / Reject / Feedback` with
    `Tale / Run / Epic / Legend / Reject / Feedback`.

Do not change inbound handling:

- `../sase-telegram/src/sase_telegram/inbound.py` should continue accepting `approve` callbacks and writing
  `{"action": "approve"}`.
- Confirmation text such as "Plan approved" can stay unless a later product decision asks to rename statuses and
  confirmations.

### Google Chat plugin

Update the current numbered option label:

- `../retired chat plugin/src/retired_chat_plugin/formatting.py`
  - First plan approval option from `✅ Approve` to `📖 Tale`.
  - Keep payload `approve` unchanged.

Update tests and docs that hard-code the numbered option:

- `../retired chat plugin/tests/test_inbound.py`
- `../retired chat plugin/tests/test_integration.py`
- `../retired chat plugin/tests/test_externally_handled_cleanup.py`
- `../retired chat plugin/tests/test_formatting.py` where the assertion covers the PlanApproval option set.
- `../retired chat plugin/README.md`
- `../retired chat plugin/docs/outbound.md`

Do not change inbound handling:

- Numeric replies should still resolve the first option to payload `approve`.
- `plan_response.json` should still contain `{"action": "approve"}` for the normal tale action.
- Confirmation text such as "Plan approved" can stay unless we decide to rename statuses/confirmations in a separate
  change.

## Implementation Order

1. Update the main repo TUI labels and docs.
2. Update Telegram formatter labels, tests, and docs.
3. Update Google Chat formatter labels, tests, and docs.
4. Run focused searches in the three repos for live PlanApproval display strings:
   - `✅ Approve`
   - `1. ✅ Approve`
   - `a=Approve`
   - `Approve with Options`
5. Leave intentional matches for:
   - internal `approve` action/payload/method names,
   - `%approve` directive docs/tests,
   - historical SDD artifacts,
   - confirmation/status wording.

## Validation

Main repo:

- `just install`
- Focused tests:
  - `pytest tests/test_plan_approval_modal_title.py tests/test_approve_options_modal.py tests/test_plan_utils.py tests/test_plan_rejection_response.py`
- Final repo check after implementation:
  - `just check`

Telegram plugin:

- `just install`
- Focused tests:
  - `pytest tests/test_formatting.py tests/test_inbound.py tests/test_integration.py`
- Final repo check:
  - `just check`

Google Chat plugin:

- `just install`
- Focused tests:
  - `pytest tests/test_formatting.py tests/test_inbound.py tests/test_integration.py tests/test_externally_handled_cleanup.py`
- Final repo check:
  - `just check`

## Risks and Guardrails

- Do not rename internal `approve` identifiers. That would make this a protocol migration across SASE core, notification
  response files, existing pending actions, and plugin inbound handlers.
- Do not change `%approve`; it means autonomous execution and is unrelated to SDD tales.
- Keep pending-action compatibility. Existing pending Telegram/GChat approvals with payload `approve` should still work
  after deployment.
- Keep the UI taxonomy clear: Tale, Run, Epic, Legend are sibling choices in plan review; Run remains the "approve but
  do not commit the tale first" path.
