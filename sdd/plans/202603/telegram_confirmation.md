---
create_time: 2026-03-25 15:53:45
status: wip
prompt: sdd/prompts/202603/telegram_confirmation.md
---

# Plan: Telegram Confirmation Messages for Feedback & Custom Answers

## Problem

When a user completes a two-step feedback or custom answer flow via Telegram (pressing "Feedback"/"Custom" button, then
typing a text message), there is **no confirmation** sent back. The response file is silently written to disk and the
pending action is removed, but the user gets no visual acknowledgment that their input was received and forwarded to the
agent.

### Current flow (two-step):

1. User presses "💬 Feedback" or "💬 Custom" button on a notification
2. `answer_callback_query()` shows a brief popup: "Send your feedback as a text message"
3. Buttons are removed from the original notification message
4. User types and sends their feedback/answer as a text message
5. `_handle_text_message()` writes the response JSON, clears awaiting state, removes pending action
6. **Nothing is sent back to the user** ← the gap

### Contrast with one-shot callbacks:

One-shot button presses (Approve, Reject, Accept, Select Option) at least get a transient `answer_callback_query` popup
("Plan approved", "Rejected", etc.), even though that's also ephemeral.

## Approach

Add confirmation messages that **reply** to the user's text message after successfully writing the response. This
provides:

- Persistent confirmation in the chat history (vs transient popups)
- Visual link between the feedback and the acknowledgment (via Telegram's reply threading)
- Clear indication of what action was taken

## Changes

### 1. `telegram_client.py` — Add `reply_to_message_id` parameter

Add optional `reply_to_message_id: int | None = None` parameter to `_send_single_message()` and `send_message()`, passed
through to `bot.send_message()`. This enables replying to the user's text message.

### 2. `inbound.py` — Add confirmation text helper

Add a function `confirmation_text(response: ResponseAction) -> str` that maps response types to human-readable
confirmation strings:

| Action Type            | Confirmation Text                             |
| ---------------------- | --------------------------------------------- |
| `plan` (with feedback) | `✅ Feedback received — plan will be revised` |
| `hitl` (with feedback) | `✅ Feedback received`                        |
| `question` (custom)    | `✅ Answer received`                          |

This keeps the pure logic (no Telegram API calls) in `inbound.py`, consistent with the existing separation of concerns.

### 3. `sase_tg_inbound.py` — Send confirmation after two-step completion

Modify `_handle_text_message()` to accept the Telegram message object so we have access to `message_id` and `chat_id`.
After writing the response:

```python
def _handle_text_message(message: Any) -> None:
    text = reconstruct_code_markers(message.text, message.entities)
    response = process_text_message(text)
    if response is not None:
        _write_response(response)
        clear_awaiting_feedback()
        pending_actions.remove(response.notif_id_prefix)
        # Send confirmation reply
        _send_confirmation(response, message.message_id)
        return
    ...
```

The `_send_confirmation` helper sends a short confirmation message as a reply to the user's text, wrapped in a
try/except so failures are logged but don't crash the chop.

Update `main()` to pass the full message object instead of just the extracted text.

### 4. Update `main()` dispatch

Change:

```python
elif msg.text:
    text = reconstruct_code_markers(msg.text, msg.entities)
    _handle_text_message(text)
```

to:

```python
elif msg.text:
    _handle_text_message(msg)
```

Move the `reconstruct_code_markers` call inside `_handle_text_message`.

## Design Decisions

**Why reply instead of a standalone message?** Replying visually links the confirmation to the user's feedback text,
making it clear which input was acknowledged.

**Why not also confirm one-shot button presses?** The user specifically asked about feedback and custom answers sent
"via telegram messages" (the text message step). One-shot button presses already have `answer_callback_query` popups.
Adding persistent messages for every button press (approve, reject, select) could feel noisy. This can be revisited as a
follow-up if desired.

**Why keep confirmation text in `inbound.py`?** This module already contains all the pure response-building logic. The
confirmation text generation is a pure function (no Telegram API calls), so it belongs here alongside `process_callback`
and `process_text_message`.

**Error handling:** Confirmation sends are best-effort. If the Telegram API call fails, the response file has already
been written, so the agent proceeds regardless. We log the error but don't retry or raise.

## Files Modified

| File                                                         | Change                                                                                        |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `sase-telegram/src/sase_telegram/telegram_client.py`         | Add `reply_to_message_id` param to `send_message`/`_send_single_message`                      |
| `sase-telegram/src/sase_telegram/inbound.py`                 | Add `confirmation_text()` function                                                            |
| `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` | Add `_send_confirmation()`, update `_handle_text_message` signature, update `main()` dispatch |

## Testing

- Unit test `confirmation_text()` for each action type
- Verify `_handle_text_message` still correctly handles non-feedback text (command dispatch, agent launch)
- Manual test: press Feedback on a plan notification, send text, verify reply confirmation appears
- Manual test: press Custom on a question notification, send text, verify reply confirmation appears
