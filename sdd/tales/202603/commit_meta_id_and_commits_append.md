---
create_time: 2026-03-26 11:54:48
status: done
prompt: sdd/prompts/202603/commit_meta_id_and_commits_append.md
---

# Plan: Fix commit post-step entry append + meta_commit_id emission

## Problem Summary

The provided logpack (`~/tmp/260326_114608`) shows commit post-steps running for `#commit`, but:

1. `meta_commit_id` is not emitted.
2. No new `COMMITS` entry is appended.

Evidence:

- `prompt_step_commit___append_entry.json` has `entry_id: ""`.
- Workflow log contains: `add_commit_entry failed: module 'calendar' has no attribute 'day_abbr'`.
- `commit_result.json` has `result: null` (Mercurial amend path), which should still be accepted.

## Root Causes

1. **Runtime failure while formatting CHAT duration in Google3 workspaces**
   - `add_commit_entry()` calls `format_chat_line_with_duration()`.
   - Duration parsing relies on timestamp helpers that invoke `datetime.strptime`.
   - In Google3 there is a local `calendar` module shadowing stdlib `calendar`, which can break `strptime` internals and
     raises `AttributeError` (`day_abbr`).
   - This exception currently bubbles out of `add_commit_entry()`, so the commit entry is never appended.

2. **No commit entry ID propagation in commit mode**
   - `append_post_commit_entry(mode="commit")` calls `add_commit_entry()` which currently returns only `bool`.
   - Therefore `PostCommitResult.entry_id` remains `None` in commit mode, so `_emit_commit_id` cannot emit
     `meta_commit_id` even when append succeeds.

## Implementation Plan

1. **Harden duration formatting path**
   - In `format_chat_line_with_duration()`, guard duration calculation behind a broad exception boundary and fall back
     to plain `CHAT` line if parsing fails.
   - Keep behavior unchanged when duration calc succeeds.

2. **Add a commit-entry API that returns entry ID**
   - Introduce `add_commit_entry_with_id(...) -> tuple[bool, str | None]` in `entries.py`.
   - Refactor current logic into that function and return the numeric entry ID (`"1"`, `"2"`, ...).
   - Preserve existing `add_commit_entry(...) -> bool` as a compatibility wrapper around the new function.

3. **Wire post-commit commit mode to returned ID**
   - Update `append_post_commit_entry(mode="commit")` to call `add_commit_entry_with_id`.
   - Return `PostCommitResult(success=ok, entry_id=entry_id)` so `_emit_commit_id` can output `meta_commit_id`.

4. **Update/add tests**
   - Update commit-mode post-commit test to assert returned `entry_id` for commit mode.
   - Add/adjust tests for the new `add_commit_entry_with_id` helper.
   - Add a regression test ensuring `format_chat_line_with_duration()` gracefully falls back when duration parsing
     raises (simulating Google3 `calendar` shadowing).

5. **Validate**
   - Run focused tests for `commit_utils` and xprompt commit flow assertions.
   - Run lint/format checks if needed for touched files.

## Expected Outcome

- `#commit` post-step appends `COMMITS` entry even in environments with stdlib module shadowing.
- `meta_commit_id` is emitted for successful commit-mode appends.
- Existing callers of `add_commit_entry()` remain compatible.
