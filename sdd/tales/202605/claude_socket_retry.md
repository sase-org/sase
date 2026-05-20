---
create_time: 2026-05-20 15:19:31
status: done
prompt: sdd/prompts/202605/claude_socket_retry.md
---
# Plan: Retry Claude Socket Closure Failures

## Problem

The reported run at `/home/bryan/.sase/projects/sase/artifacts/ace-run/20260520141624` failed in the `main` workflow
step after Claude Code returned exit code 1:

`API Error: The socket connection was closed unexpectedly. For more information, pass verbose: true in the second argument to fetch()`

SASE captured streamed assistant output in the error report, then treated the nonzero Claude CLI exit as a hard
`LLMInvocationError`. The outer ACE run retry loop did not retry because Claude's built-in retry configuration currently
only matches `"Prompt is too long"`.

## Root Cause

The transport failure is transient and already reaches the retry-capable ACE execution loop, but the provider retry
classifier is too narrow. The existing retry machinery can preserve the workspace, snapshot partial output, and retry.
It simply does not recognize Claude socket/API close messages as retryable.

There is also a secondary wording issue: Claude's built-in continuation prompt is specific to context-window failures.
If we add transport errors to the same built-in config, the continuation nudge should become accurate for both context
overflow and transient provider failures.

## Proposed Fix

1. Update Claude's built-in `llm_default_retry_config()` in `src/sase/llm_provider/claude.py`:
   - Keep `max_retries=3`, `wait_times=[0]`, and `preserve_workspace=True`.
   - Add retry patterns for the observed transient failure, including the stable substrings
     `"socket connection was closed unexpectedly"` and `"API Error"`.
   - Replace the context-only continuation nudge with a broader one that covers both context-window and provider
     transport failures while preserving the existing instruction to inspect `git status` / `git diff` and continue from
     on-disk work.

2. Extend retry configuration tests in `tests/test_llm_provider_retry_config.py`:
   - Assert Claude's built-in config contains the new socket/API retry patterns.
   - Assert the built-in config matches the exact error string from the artifact through `is_retryable_error()`.
   - Adjust the continuation-prompt expectation so it no longer requires context-only wording.

3. Validate narrowly first, then broadly:
   - Run the relevant retry config tests.
   - Because this repo requires it after non-bead changes, run `just install` and `just check` before final response.

## Expected Outcome

Future ACE runs that hit this Claude CLI socket-close failure will enter the existing retry path instead of failing
immediately. Partial output remains preserved in attempt snapshots, the workspace is kept intact, and the retry prompt
accurately tells the next attempt to inspect existing work before continuing.
