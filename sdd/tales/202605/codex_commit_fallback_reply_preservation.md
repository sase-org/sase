---
create_time: 2026-05-14 20:59:44
status: done
prompt: sdd/prompts/202605/codex_commit_fallback_reply_preservation.md
---
# Plan: Preserve Codex Agent Replies Across Commit Fallback Turns

## Problem

When a Codex agent finishes with uncommitted changes, SASE may run an in-band Codex follow-up turn that asks the agent
to commit those changes. The TUI Agents tab then appears to lose or clear the reply from the original turn that made the
file edits.

The suspected root cause is in the Codex provider streaming path:

- `CodexProvider.invoke()` calls `_run_subprocess()` for the original turn.
- If dirty files remain, `_maybe_run_commit_fallback_turn()` calls `_run_subprocess()` again for the commit-stop
  follow-up.
- Each subprocess parser opens `live_reply.md` and `live_reply_timestamps.jsonl` through `open_live_reply_file()` /
  `open_live_reply_timestamps_file()`.
- Those helpers currently open the files with write mode, which truncates the first turn’s reply when the fallback turn
  starts.
- The TUI selected-agent panel prefers timestamped live-reply chunks over `response_path`, so even if the final saved
  chat contains accumulated text, the visible panel can show only the second turn or no reply.

## Approach

Fix the artifact streaming contract so multiple subprocess cycles within the same agent attempt append to the existing
live-reply artifacts rather than replacing them.

1. Update the live reply artifact helpers to preserve existing content:
   - Open `live_reply.md` in append mode.
   - Open `live_reply_timestamps.jsonl` in append mode.
   - Consider doing the same for Codex thinking artifacts so the second turn does not erase first-turn reasoning.

2. Adjust stream text writing so separate subprocess cycles remain readable:
   - The current code inserts a blank separator only when the current parser invocation has already seen assistant text.
   - With append mode, a later invocation starts with an empty in-memory `assistant_texts` list but a non-empty file.
   - Treat a non-empty live-reply file position as needing the same separator before writing the next assistant message.

3. Add focused regression coverage:
   - Simulate two Codex assistant-message writes to the same `SASE_ARTIFACTS_DIR` through separate file opens.
   - Assert the first reply remains, the second reply is appended, and timestamp entries are not overwritten.
   - Keep this test near the Codex subprocess/fallback tests so the scenario is explicit.

4. Run targeted tests first:
   - The new regression test.
   - Existing Codex fallback tests.
   - Existing agent-display tests that exercise timestamped reply rendering.

5. Run the repo-required validation:
   - `just install` first if needed for this ephemeral workspace.
   - `just check` before final response because this change touches repo files.

## Risks

- Opening live-reply files in append mode assumes each artifacts directory starts fresh for a new attempt. That is
  already how SASE creates agent artifacts, and retry attempts snapshot/clear live-reply files before reuse.
- Timestamp offsets are written before the separator today, so appended chunks may include leading blank separators just
  like multi-message chunks already can. This is acceptable for rendering and avoids changing timestamp semantics
  broadly.

## Expected Outcome

After a Codex commit fallback turn, the Agents tab should retain the original agent reply and append the commit
follow-up reply instead of replacing or clearing the original visible response.
