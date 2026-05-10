---
create_time: 2026-04-30 12:34:49
status: done
prompt: sdd/prompts/202604/gchat_plan_approval_without_plan_body.md
---
# Plan: Stop Inlining Google Chat Plan Bodies

## Goal

Google Chat plan approval notifications should stop embedding the plan file contents in the message body. Google Chat
does not support the same expandable/folded presentation that Telegram uses, so inlining the plan makes approval threads
too noisy. Telegram should keep its current behavior because it can fold medium/long plan content.

## Current Behavior

- `../retired chat plugin/src/retired_chat_plugin/formatting.py` formats `PlanApproval` notifications in `_format_plan_approval()`.
- When `Notification.files[0]` points at a readable plan file, the formatter reads the markdown, strips frontmatter,
  truncates or blockquotes it, and appends it to the message text.
- The same plan file is also returned in `FormattedMessage.attachments`, so outbound later uploads it, converting
  markdown plans to PDF when possible.
- `../sase-telegram/src/sase_telegram/formatting.py` also reads and embeds plan content, but it has Telegram-specific
  expandable blockquote handling. This should not change.

## Proposed Change

Update only the Google Chat formatter so `PlanApproval` messages include:

- The existing title, provider/model label, and agent name.
- The existing notes text from the notification.
- A short plan-reference line when a plan file is available, for example `📎 Plan attached: plan.md`.
- The existing numbered options block in the same order: Approve, Run, Epic, Reject, Feedback.
- The same attachment list as today, so the outbound script still uploads the plan file/PDF for review.

The message body should not contain the markdown plan contents, including headings or YAML-frontmatter-derived text.
Missing or unreadable plan files should still produce the title, notes, and options with no attachment, matching current
failure behavior.

## Implementation Steps

1. Modify `../retired chat plugin/src/retired_chat_plugin/formatting.py`.
   - Remove the plan-content read/strip/truncate/blockquote path from `_format_plan_approval()`.
   - Keep adding `n.files[0]` to `attachments` only when the file exists and is readable, preserving the current
     successful-upload path and missing-file behavior.
   - Add a concise attachment reference line to the message when a readable plan file exists.
   - Leave `_format_notes_text()`, `_wrap_blockquote()`, and `_truncate_to_pdf()` alone because they are still used by
     notes and other formatting paths.

2. Update Google Chat tests in `../retired chat plugin/tests/test_formatting.py`.
   - Replace expectations that short plans appear inline with expectations that plan headings/body do not appear.
   - Replace long-plan blockquote/truncation expectations with "not inline, still attached" expectations.
   - Keep tests for provider/model labels, agent name, option ordering, and missing plan files.
   - Adjust the YAML frontmatter test so it asserts neither frontmatter nor plan title/body leaks into `result.text`.

3. Review docs in `../retired chat plugin/README.md` and `../retired chat plugin/docs/outbound.md`.
   - Update the PlanApproval description from "plan text/body content" to "notes + numbered options + attached plan".
   - Keep docs for PDF attachment conversion because outbound should continue to upload plan files.

4. Do not modify `../sase-telegram`.
   - Telegram keeps embedded/folded plan content and its existing tests should remain valid.

5. Verification.
   - Run targeted Google Chat tests first, especially `tests/test_formatting.py` and the plan attachment integration
     tests.
   - Run `just check` in `../retired chat plugin` because the plugin repo instructions require it after modifications.
   - No `just check` is required in this `sase_100` repo unless the only local change is this submitted plan file.
