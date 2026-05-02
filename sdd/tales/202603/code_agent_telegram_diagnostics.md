---
create_time: 2026-03-24 18:15:49
status: done
prompt: sdd/prompts/202603/code_agent_telegram_diagnostics.md
---

# Plan: .code Agent Telegram Completion Diagnostics

## Investigation Findings

Thorough analysis of the full notification pipeline for `.code` agent completions:

1. **Notifications ARE being created** — confirmed by matching PlanApproval timestamps with JumpToAgent timestamps in
   `notifications.jsonl`. The `notify_workflow_complete()` call in `run_agent_runner.py` fires for `.code` agents.

2. **Outbound IS processing them** — the lumberjack telegram debug log shows "Sending 1 notification(s)" entries that
   correspond to `.code` completion timestamps.

3. **No send failures logged** — no warning/error messages appear in the telegram log for these sends.

4. **Formatted message is valid** — test-formatted a real `.code` completion notification: valid MarkdownV2, 639 chars
   (well under 4096 limit).

**Conclusion**: The messages appear to be sent successfully through the pipeline. However, there is a gap in
observability — no post-send success logging exists to definitively confirm Telegram API delivery. The current code logs
before sending but not after, and `mark_sent()` is called unconditionally (even on failure).

## Proposed Changes

### 1. Add post-send success logging in sase-telegram outbound

**File**: `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py`

In the `try` block after `send_message()` succeeds, add a debug log confirming delivery with the Telegram message ID.
This closes the observability gap — we'll know definitively whether messages reached Telegram.

```python
try:
    msg = send_message(chat_id, text, reply_markup=keyboard, parse_mode="MarkdownV2")
    rate_limit.record_send()
    log.debug("Sent notification %s → message_id=%s", n.id[:8], msg.message_id)
except Exception:
    log.warning("Failed to send notification %s to Telegram", n.id[:8], exc_info=True)
```

### 2. Only advance high-water mark on successful sends

**File**: `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py`

Currently `mark_sent([n])` is called unconditionally after the try/except, meaning failed sends still advance the
high-water mark and the notification is permanently skipped. Move `mark_sent()` inside the `try` block so failed
notifications are retried on the next outbound cycle.

```python
try:
    msg = send_message(chat_id, text, reply_markup=keyboard, parse_mode="MarkdownV2")
    rate_limit.record_send()
    log.debug("Sent notification %s → message_id=%s", n.id[:8], msg.message_id)
    mark_sent([n])
except Exception:
    log.warning("Failed to send notification %s to Telegram", n.id[:8], exc_info=True)
```

This is the most impactful fix — if any transient Telegram API error causes a send failure, the notification will be
retried rather than silently dropped.

## Implementation Steps

1. In `sase_tg_outbound.py`: add post-send debug log line with message_id confirmation
2. In `sase_tg_outbound.py`: move `mark_sent([n])` inside the `try` block (before `except`)
3. Verify no other callers depend on the unconditional `mark_sent()` behavior
