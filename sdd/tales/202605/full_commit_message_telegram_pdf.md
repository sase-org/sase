---
create_time: 2026-05-23 13:57:47
status: done
prompt: sdd/prompts/202605/full_commit_message_telegram_pdf.md
---
# Plan: Full Commit Messages in Telegram Completion PDFs

## Goal

When an agent completes after creating a commit, the Telegram completion PDF should include the full commit message,
including the body, not just the subject line.

This should apply to new agent completion notifications generated after the fix. The plan does not try to rewrite old
notifications that were already persisted with only a subject line.

## Current Understanding

The completion path spans the core `sase` repo and the `sase-telegram` plugin.

In `sase`:

- `src/sase/workflows/commit/commit_tracking.py::write_result_marker()` writes `commit_result.json`.
- That marker stores `message` from the commit payload, which should be the full message when the agent used
  `sase_git_commit -M ...`.
- `src/sase/xprompts/commit.yml` has a hidden `report` step that reads `commit_result.json` and emits
  `meta_commit_message`.
- `src/sase/axe/run_agent_helpers.py::extract_step_output_and_diff_path()` falls back to `commit_result.json` only when
  `step_output` does not already have `meta_commit_message`.
- `src/sase/axe/run_agent_runner_finalize.py::send_completion_notification()` forwards `meta_commit_message` as
  `action_data["commit_message"]`.

In `sase-telegram`:

- `src/sase_telegram/formatting.py::_format_workflow_complete()` returns the notification attachments unchanged.
- `src/sase_telegram/scripts/sase_tg_outbound.py::_run_outbound()` detects chat-history attachments, extracts the
  response Markdown, appends `action_data["commit_message"]` via `_prepend_commit_message_to_markdown()`, appends diff
  content, then converts that response Markdown to PDF.
- `_prepend_commit_message_to_markdown()` already writes the whole string it receives, so the Telegram side is probably
  not intentionally truncating the body. The most likely bug is that the core notification metadata sometimes contains
  only the subject line.

## Product Scope

Include the full commit message in the response PDF that Telegram creates from the agent chat response.

Do not modify other generated PDF attachments, such as PDFs created from Markdown files the agent edited. Those are
source-document artifacts and should remain faithful to their source files.

Keep the Telegram message text compact. The full commit message belongs in the attached PDF, not in the Telegram chat
message body.

## Implementation Plan

1. Add a small core helper for commit-result metadata.

   Create or refactor a helper near `src/sase/axe/run_agent_helpers.py` that reads `<artifacts_dir>/commit_result.json`
   and returns JSON-safe metadata:
   - full commit message from `message`
   - commit result/hash from `result`
   - ChangeSpec name from `changespec_name` or `name`
   - diff path from `diff_path`

   The helper should tolerate missing, malformed, or non-dict JSON and simply return no metadata.

2. Prefer `commit_result.json["message"]` for notification commit text.

   Update `extract_step_output_and_diff_path()` so when `commit_result.json` exists, its `message` is the authoritative
   value for `meta_commit_message`, even if a workflow step already emitted a shorter value.

   This preserves the full message in completed-agent `done.json` as well as in completion notifications.

3. Add a finalizer fallback for non-happy paths.

   Update `send_completion_notification()` to derive `commit_message` from the same helper when:
   - `step_output` is missing, or
   - `step_output["meta_commit_message"]` is present but shorter/truncated relative to `commit_result.json`.

   This covers agents that made a commit but then failed before normal workflow-state extraction completed.

4. Harden Telegram Markdown injection.

   In `sase-telegram`, keep the existing behavior of appending the commit message before diff content, but make the
   fenced block robust for arbitrary commit bodies. A safe option is to choose a fence length longer than any run of
   backticks in the commit message, then write:

   `````text
   ## Commit Message

   ````...
   full message
   ````...
   `````

   This prevents commit bodies containing Markdown code fences from breaking the PDF source.

5. Add core tests in `sase`.

   Add focused tests that prove:
   - `extract_step_output_and_diff_path()` preserves a multiline `commit_result.json["message"]`.
   - `extract_step_output_and_diff_path()` replaces a subject-only `meta_commit_message` from workflow state with the
     full message from `commit_result.json`.
   - `send_completion_notification()` passes the full message in `action_data["commit_message"]`.

6. Add Telegram tests in `sase-telegram`.

   Add focused tests that prove:
   - `_prepend_commit_message_to_markdown()` writes the full multiline message, including blank lines and body lines.
   - `_run_outbound()` appends the full commit message to the extracted response Markdown before calling `md_to_pdf()`.
   - Commit messages containing backtick fences do not break the generated Markdown wrapper.

7. Verification.

   In the `sase` workspace, run:

   ```bash
   just install
   just test tests/test_done_agent_loader.py tests/test_run_agent_runner_notifications.py tests/test_commit_report_meta_changespec.py
   ```

   If implementation files changed in `sase`, finish with:

   ```bash
   just check
   ```

   In the numbered `sase-telegram` workspace, run:

   ```bash
   just install
   just test tests/test_outbound.py
   just check
   ```

## Risks and Notes

- The ChangeSpec `COMMITS` drawer should keep using the first line as the visible commit entry note. That behavior is
  separate from Telegram completion PDFs and should not be changed here.
- Existing notifications already stored with a truncated `action_data["commit_message"]` will still render truncated
  PDFs if resent. The fix targets notifications created after the core metadata change.
- The implementation should avoid runtime-specific branches. Commit metadata is produced by the shared commit workflow
  and should work uniformly for Codex, Claude, Gemini, and other supported runtimes.
