---
create_time: 2026-05-07 21:53:51
status: wip
prompt: sdd/prompts/202605/telegram_epic_legend_copy_confirmation.md
---
# Telegram Epic And Legend Copy Confirmations

## Context

Telegram plan approval notifications show six buttons: Tale, Approve, Epic, Legend, Reject, and Feedback. The inbound
Telegram handler writes `plan_response.json` for each one-shot callback, removes the original inline keyboard, and then
optionally sends a small follow-up message with a Telegram `CopyTextButton` for the plan path.

Today that follow-up copy message is only sent for accepted tale/plan flows:

- `📖 Tale` writes `{"action": "approve"}` and receives the follow-up copy button.
- `✅ Approve` writes `{"action": "approve", "commit_plan": false, "run_coder": true}` and also receives the follow-up
  copy button because the response action is still `approve`.
- `📋 Epic` writes `{"action": "epic"}` but does not receive the follow-up copy button.
- `🗺️ Legend` writes `{"action": "legend"}` but does not receive the follow-up copy button.

The relevant implementation is in the external Telegram plugin repo, `../sase-telegram`, not in the main `sase_101`
repo:

- `src/sase_telegram/scripts/sase_tg_inbound.py`
  - `_send_plan_confirmation()` builds the confirmation text and copy-text keyboard.
  - `_handle_callback()` decides which plan actions call `_send_plan_confirmation()`.
- `src/sase_telegram/inbound.py`
  - `process_callback()` already maps Epic and Legend buttons to the expected `epic` and `legend` response actions.

## Product Behavior

After tapping Epic or Legend in Telegram, the user should receive the same kind of compact confirmation message they get
after Tale/Approve:

- The original plan notification's inline keyboard is removed.
- Telegram answers the button tap with the existing callback text, `Epic created` or `Legend created`.
- A new chat message is sent with a short confirmation label.
- That message includes one copy-text button for the plan path, using the same relative-path logic as the existing Tale
  and Approve confirmation.

The confirmation should use action-specific wording so the message is not misleading:

- `approve`: `Plan approved`
- `commit`: `Plan committed` if still supported by this path
- `epic`: `Epic created`
- `legend`: `Legend created`

The copy button can continue to use the existing `📋 Plan` label because the copied text is the source plan path that
the follow-up epic/legend workflow will consume. If this feels ambiguous during implementation, a low-risk alternative
is to label it `📋 Epic plan` / `📋 Legend plan`, but the copied payload should remain the same path normalization
currently used for Tale/Approve.

## Implementation Plan

1. Update `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`.
   - Extend `_send_plan_confirmation()` so it has explicit labels for `approve`, `commit`, `epic`, and `legend`.
   - Keep the existing plan-file path normalization:
     - Use `action["plan_file"]`.
     - Prefer a path relative to `action["action_data"]["project_dir"]` when available.
     - Fall back to the basename when the plan is outside the project or project context is missing.
   - Keep the existing no-plan-file fallback: send the confirmation text without a keyboard.

2. Widen the callback confirmation gate in `_handle_callback()`.
   - Change the current `("approve", "commit")` action filter to include `("epic", "legend")`.
   - Continue to call `_send_plan_confirmation()` only for `response.action_type == "plan"` and only when the pending
     action entry is still available.

3. Add focused tests in `../sase-telegram`.
   - Add or extend an inbound script integration test that exercises `plan:<prefix>:epic` and verifies:
     - `plan_response.json` contains `{"action": "epic"}`.
     - `telegram_client.send_message()` is called with the Epic confirmation.
     - The reply markup contains a `CopyTextButton` with the expected normalized plan path.
   - Add the same coverage for `plan:<prefix>:legend`.
   - Preserve existing approve/run behavior; if the current approve integration test is too weak, assert that it still
     emits the copy confirmation.

4. Run validation in the modified repo.
   - Because this is cross-repo work, run commands from `../sase-telegram`.
   - Run `just install` first if the workspace may not be initialized.
   - Run targeted tests for inbound callback behavior.
   - Run `just check` in `../sase-telegram` before reporting completion, per the external repo memory.

## Risks And Edge Cases

- Telegram `CopyTextButton` has a short text limit, but this path already uses it today. The plan should preserve the
  existing behavior rather than changing truncation semantics in the same patch.
- The current confirmation path copies the original plan file path, not the later SDD `sdd/epics/...` or
  `sdd/legends/...` path that the main agent workflow may create after consuming the response. That is consistent with
  the existing Tale/Approve confirmation and avoids racing the follow-up workflow.
- The main `sase_101` host-side mobile bridge already archives approve/epic/legend plans consistently, so this fix
  should stay scoped to Telegram inbound confirmation rendering unless tests reveal a host-side regression.
