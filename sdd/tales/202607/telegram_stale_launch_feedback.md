---
create_time: 2026-07-06 16:19:14
status: wip
prompt: sdd/prompts/202607/telegram_stale_launch_feedback.md
---
# Plan: Fix Telegram Slash Commands Consumed by Stale Launch Feedback

## Problem

The Telegram screenshot shows a normal `/list` command receiving the reply `pending launch action is missing`. That text
is not produced by the `/list` handler. It comes from the LaunchApproval feedback path in the `sase-telegram` plugin.

The likely event chain is:

1. A LaunchApproval notification entered the two-step "send feedback as text" flow.
2. Telegram stored an awaiting-feedback entry for that action.
3. The matching pending action was later removed or handled elsewhere.
4. A later `/list` message was processed by the text-feedback path before slash-command dispatch.
5. The LaunchApproval resolver saw no pending action and raised `pending launch action is missing`, which the Telegram
   inbound script sent back to the chat as a plain reply.

The local state now matches that failure mode: the legacy Telegram pending-action store is empty, and the
awaiting-feedback file has already been cleared by the error path, so the visible bad reply was the cleanup side effect.

## Implementation Scope

Make the fix in the linked `sase-telegram` repo. No shared SASE backend changes are needed unless tests reveal a missing
host-side contract.

Primary files:

- `src/sase_telegram/scripts/sase_tg_inbound.py`
- `src/sase_telegram/inbound.py` only if a small pure helper is the cleaner place for state validation
- `tests/test_inbound.py`
- `tests/test_integration.py` if the end-to-end inbound loop needs coverage beyond the unit-level script tests

## Approach

1. Preserve slash-command precedence.

   In Telegram text handling, dispatch leading slash commands before generic awaiting-feedback completion. A
   user-visible command like `/list`, `/kill`, `/bead`, or `/update` should always be treated as a command, not as
   feedback for an older action.

2. Clean stale awaiting-feedback state without leaking internal errors.

   Add a narrow cleanup path for awaiting-feedback entries whose prefix no longer exists in Telegram pending actions.
   For an unkeyed stale entry, clear it and continue with the current message's normal behavior. For an explicit reply
   to a stale action message, clear the entry and send a friendly already-handled or expired response instead of
   launching a new agent.

3. Keep active feedback flows working.

   Existing keyed replies to PlanApproval, HITL, LaunchApproval, and UserQuestion flows must still complete normally.
   The fix should not remove the legacy single-flow fallback unless the message is a slash command or the referenced
   action is demonstrably stale.

4. Sanitize LaunchApproval error text shown in Telegram.

   Map `not_found` and other stale/missing-action LaunchApproval failures to a user-facing message such as
   `This action has already been handled` or `This request has expired`. The internal phrase
   `pending launch action is missing` should remain an implementation detail and should not be sent to Telegram chat.

## Tests

Add focused tests that reproduce the screenshot behavior:

- A stale single awaiting LaunchApproval entry exists, no matching pending action exists, and the user sends `/list`;
  assert `_handle_command("/list", message)` is called and no LaunchApproval error message is sent.
- The same stale single awaiting entry exists and the user sends ordinary non-command text without replying to an
  action; assert the stale awaiting entry is cleared and the text follows the normal launch path.
- A user replies directly to a stale awaiting action message; assert Telegram receives a friendly stale/already-handled
  message and no agent launch occurs.
- Existing keyed feedback tests still pass for active HITL, PlanApproval, LaunchApproval, and UserQuestion flows.

If the unit tests leave uncertainty about the full inbound polling loop, add one integration test around
`inbound_main(["--once"])` with a mocked Telegram `/list` update and stale awaiting state.

## Verification

Run in the `sase-telegram` repo:

```bash
just install
just check
```

For faster iteration before the full check, run the targeted inbound tests first:

```bash
pytest tests/test_inbound.py -q
```

## Acceptance Criteria

- Sending `/list` in Telegram always invokes the `/list` command path.
- Stale LaunchApproval awaiting-feedback state cannot consume unrelated slash commands.
- Stale awaiting-feedback state is cleaned up when discovered.
- Telegram no longer sends `pending launch action is missing` to the user.
- Existing active feedback, question, callback, and normal text-launch behavior remains intact.
