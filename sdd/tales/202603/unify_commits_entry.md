---
status: done
create_time: 2026-03-27 13:48:35
prompt: sdd/prompts/202603/unify_commits_entry.md
---

# Plan: Unify COMMITS entry creation in CommitWorkflow

## Problem

The recent fix (commit d32aeac) introduced a `SASE_DEFER_COMMITS_ENTRY` mechanism that splits COMMITS entry creation
between two places:

1. **CommitWorkflow** (`workflow.py`) — skips entry creation when `SASE_DEFER_COMMITS_ENTRY` is set
2. **Xprompt post-steps** (`commit.yml` / `propose.yml` `_append_entry` step) — calls `append_post_commit_entry()` after
   the agent finishes

This breaks the principle that `sase commit` should be the single source of truth for all commit functionality. A human
running `sase commit` directly and an agent's stop hook calling `sase commit` should produce identical results.

## Root Cause

The deferral was introduced because the xprompt's `prompt_step_*.json` markers (which contain `response_path`) aren't
available until after the agent finishes. But `SASE_AGENT_CHAT_PATH` is already set as an env var at commit time and
serves as a fallback in `append_post_commit_entry()`. The diff is captured pre-commit by `_capture_pre_commit_diff()`.
So all the information needed is available when CommitWorkflow runs — no deferral is needed.

## Phase 1: Remove deferral from CommitWorkflow

**File: `src/sase/workflows/commit/workflow.py`**

- Remove the `SASE_DEFER_COMMITS_ENTRY` env var check (line 131)
- Always call `_append_commits_entry()` for commit/proposal methods
- The diff_path is already available via `self._diff_path` -> `commit_result.json`
- The chat_path is available via `SASE_AGENT_CHAT_PATH` env var (fallback in `append_post_commit_entry()`)

## Phase 2: Simplify xprompts

**File: `src/sase/xprompts/commit.yml`**

- Remove `SASE_DEFER_COMMITS_ENTRY: "1"` from environment
- Remove `_append_entry` step (lines 44-59)
- The `_emit_commit_id` step still works because CommitWorkflow now writes `entry_id` to `commit_result.json`

**File: `src/sase/xprompts/propose.yml`**

- Remove `SASE_DEFER_COMMITS_ENTRY: "1"` from environment
- Remove `_append_entry` step (lines 61-76)
- The `_emit_proposal_id` step still works for the same reason

## Phase 3: Clean up post_commit.py

**File: `src/sase/workflows/commit_utils/post_commit.py`**

- Remove `_find_best_response_path()` function — prompt_step markers are an xprompt-specific mechanism that shouldn't be
  involved in commit entry creation
- Remove `_find_best_diff_path()` function — same reason; diff_path comes from `commit_result.json`
- Simplify `append_post_commit_entry()` to read diff_path from `commit_result.json` directly and chat_path from
  `SASE_AGENT_CHAT_PATH` env var only
- Update docstring to reflect that this is called by CommitWorkflow (not xprompts)

## Phase 4: Update tests

- Update any tests that mock `SASE_DEFER_COMMITS_ENTRY`
- Verify existing tests for `append_post_commit_entry` still pass after removing prompt_step scanning
