---
create_time: 2026-06-03 03:14:11
status: done
prompt: sdd/prompts/202606/telegram_kill_redo.md
---
# Telegram Kill Redo Button Plan

## Context

The Telegram plugin has two user-facing retry surfaces:

- Launch confirmation: `_send_launch_notification()` builds Fork, Wait, Kill, and Retry controls. Its Retry button calls
  `_build_retry_prompt_for_agent()`, which allocates a fresh retry name and rewrites or prepends a `%n:<retry>`
  directive. This is the "other Retry button" and must keep its current label and prompt rewriting behavior.
- Kill confirmation: `_send_kill_result()` is used after a Telegram Kill button or `/kill <name>` succeeds. It currently
  also calls `_build_retry_prompt_for_agent()`, so the kill confirmation button is labeled Retry and its copy/callback
  prompt is rewritten with a fresh `%n:<retry>` directive.

The requested behavior is only for the kill confirmation surface: rename that button from "Retry" to "Redo" and stop
adding the retry name directive to the text it copies or sends back through the long-prompt callback.

## Plan

1. Add a kill-specific prompt builder near the existing retry helper.
   - It should accept the same source prompt and return the trimmed original prompt when present.
   - It should not allocate a retry name.
   - It should not call `rewrite_retry_prompt_name()`.
   - It should preserve existing empty-prompt behavior by returning `None` for missing or whitespace-only prompts.

2. Change `_send_kill_result()` to use the kill-specific builder.
   - Rename local variables from retry-oriented names where useful so the two paths remain easy to distinguish.
   - For short prompts, render the kill confirmation button with visible text "Redo" and
     `CopyTextButton(text=<original prompt>)`.
   - For long prompts, store the original prompt in `pending_actions` so `_handle_retry_from_callback()` sends exactly
     that original text when the user taps the callback-backed button.
   - Keep the existing callback action type/key shape (`retry-<agent>`, callback data `retry:<agent>:go`) unless a test
     exposes a reason to change it. This avoids touching callback decoding and preserves compatibility for the existing
     long-prompt send-back mechanism.

3. Leave launch confirmation retry untouched.
   - `_send_launch_notification()` should continue to call `_build_retry_prompt_for_agent()`.
   - The launch confirmation button should remain labeled "Retry".
   - Existing launch tests should continue to assert `%n:<retry>` rewriting.

4. Update focused tests in `tests/test_inbound.py`.
   - Change `TestSendKillResult.test_short_prompt_includes_retry_button` to expect the "Redo" label and the unmodified
     prompt text.
   - Change the long-prompt kill confirmation test to expect pending action storage of the unmodified prompt and a
     "Redo" callback button.
   - Change the artifact fallback test to assert an existing `%n:` directive is preserved, not rewritten.
   - Keep the launch retry tests as-is so they guard against accidentally changing the other Retry button.
   - Add or adjust test names/comments to reflect Redo vs Retry behavior without broad test churn.

5. Update user-facing docs where they describe the kill confirmation button.
   - README and docs that list "Agent Killed" or `/kill <name>` as sending a Retry button should say Redo.
   - Leave launch confirmation docs saying Retry.

6. Verify with targeted tests first, then the plugin's standard check if practical.
   - Run the focused inbound tests around launch retry, kill result, and retry callback behavior.
   - Run the full Telegram plugin test suite or `just test` if the focused tests pass and the environment has
     dependencies available.

## Risks And Guardrails

- The callback handler name and pending action action value can remain "retry" even though the visible kill confirmation
  button says "Redo"; this is an internal transport detail and avoids a callback-data migration.
- The no-name-directive behavior applies only to the killed-agent Redo prompt. Launch Retry must continue allocating and
  injecting a new retry name to avoid duplicate agent names.
- The long-prompt path must be checked explicitly because it does not use Telegram copy text; it sends a stored prompt
  in chat after the callback.
