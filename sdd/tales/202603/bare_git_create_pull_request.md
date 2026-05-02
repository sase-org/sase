---
status: done
create_time: 2026-03-31 12:56:33
prompt: sdd/prompts/202603/bare_git_create_pull_request.md
---

# Fix: Allow `create_pull_request` with bare_git VCS provider

## Problem

When `SASE_COMMIT_METHOD=create_pull_request` on a `#git` project that resolves to `bare_git` (no GitHub remote), the
commit workflow fails: _"create_pull_request requires a VCS plugin (e.g. sase-github) but only bare_git is available."_

The agent then falls back to `create_commit`, which bypasses ChangeSpec creation — losing traceability. The desired
behavior is: bare_git `create_pull_request` should create a branch, commit, push, and create a ChangeSpec (without a PR
URL, since there's no GitHub repo).

## Root Cause

Two guards in `src/sase/workflows/commit/workflow.py` block the flow:

1. **Early blocker (lines 91-102)**: Calls `detect_vcs(cwd)`, sees `bare_git`, and immediately returns `False`.
2. **Post-dispatch PR URL check (lines 167-174)**: Requires a truthy `result` (PR URL) from the VCS provider. But
   bare_git's `vcs_create_pull_request()` returns `(True, None)` — it created the branch and committed, but has no PR
   URL to return.

Both guards assumed `create_pull_request` only makes sense with a PR-capable provider (GitHub). But bare_git already
implements the method correctly: branch → commit → push → `(True, None)`. And `add_changespec_to_project_file` already
handles `cl_url=None` (omits the CL line).

## Plan

### Phase 1: Remove the early `bare_git` blocker

**File:** `src/sase/workflows/commit/workflow.py` (lines 91-102)

Delete the block that checks `detect_vcs(cwd) == "bare_git"` and returns `False`. Also remove the now-unused
`detect_vcs` import if it becomes unused.

### Phase 2: Remove the post-dispatch PR URL check

**File:** `src/sase/workflows/commit/workflow.py` (lines 167-174)

Delete the block that checks `not result` after `create_pull_request` and errors. The
`_create_changespec(cl_url=result)` call on line 180 already handles `cl_url=None` correctly.

### Phase 3: Update tests

Check for existing tests that assert the old blocking behavior and update them to expect success. Add a test for the
bare_git + `create_pull_request` path confirming ChangeSpec creation with no CL URL.

### Phase 4: Run `just install && just check`
