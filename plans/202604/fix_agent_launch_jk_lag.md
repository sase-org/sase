---
create_time: 2026-04-27 08:52:30
status: wip
---
# Fix Agent Launch j/k Lag

## Problem

After submitting an agent prompt in the ACE TUI, `j`/`k` navigation can still lag before it starts moving between
agent/workflow entries. A previous fix moved the heavy launch body (`_run_agent_launch_body`) to a worker thread, but
there is still synchronous work in the pre-handoff path:

1. `_finish_agent_launch()` calls `_unmount_prompt_bar()` on the Textual event-loop thread.
2. `_unmount_prompt_bar()` always calls `_save_bar_text_as_cancelled()` before focus transfer.
3. `_save_bar_text_as_cancelled()` synchronously writes prompt history and file-reference history.

For submitted prompts, that cancelled-save is redundant because `_run_agent_launch_body()` saves the submitted prompt as
non-cancelled in the worker thread. It also occurs before focus is transferred from the prompt text area back to the
agent list, so any disk latency in history/file-reference persistence directly delays the first post-submit `j`/`k`
keypress.

## Root Cause Hypothesis

The remaining lag is caused by synchronous cancelled-prompt persistence during launch prompt teardown, not by the launch
body itself. The launch body is already offloaded with `asyncio.to_thread`, but the prompt bar is still doing disk I/O
on the UI thread before the offload is scheduled.

## Implementation Plan

1. Change prompt-bar unmount semantics so callers can skip cancelled-history persistence when they are unmounting a
   successfully submitted prompt.
   - Add an optional keyword to `_unmount_prompt_bar()`, defaulting to the current safe behavior.
   - Keep cancellation, empty prompt, editor cancellation, feedback, approval, and remount paths saving draft/cancelled
     text as they do today.
   - In `_finish_agent_launch()`, call `_unmount_prompt_bar(save_cancelled=False)` because the submitted prompt is saved
     later by the worker-thread launch body.

2. Preserve focus behavior.
   - Focus transfer must still happen synchronously before forcibly detaching the prompt bar.
   - Skipping cancelled persistence should make focus transfer happen earlier, which is the key user-facing fix.

3. Add regression tests.
   - Extend the existing non-blocking launch coverage with a harness whose prompt-bar unmount path has a deliberately
     slow `_save_bar_text_as_cancelled()`.
   - Verify `_finish_agent_launch()` does not call the cancelled-save path on successful launch submission.
   - Verify cancelled/explicit unmount behavior still calls the cancelled-save path by default.
   - Keep the test focused on the root cause rather than spawning real agents.

4. Run targeted tests first, then repo checks.
   - Targeted: `pytest tests/ace/tui/test_agent_launch_non_blocking.py` plus any prompt-bar lifecycle tests added or
     touched.
   - Required final check for this repo after edits: `just check`.

## Expected Outcome

Submitting an agent prompt should immediately transfer focus back to the active list and schedule the launch worker,
without synchronous history/file-reference disk I/O in the critical keypress path. Cancelled/draft prompt preservation
remains intact for paths that actually dismiss or replace the prompt bar without launching.
