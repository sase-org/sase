---
create_time: 2026-03-28 14:38:38
status: done
prompt: sdd/prompts/202603/strip_pr_tags_from_description.md
---

# Plan: Strip PR Tags from ChangeSpec DESCRIPTION

## Problem

PR tags (e.g., `AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`, `R=startblock`, `WANT_LGTM=all`) appear in the
ChangeSpec DESCRIPTION field in the `sase ace` TUI. These are CL metadata that belong in the commit message but should
not be shown as part of the human-readable description.

## Root Cause

There are two paths where descriptions with PR tags enter the ChangeSpec system:

1. **`_sync_description_bg()`** (`src/sase/ace/handlers/reword.py:26`) — After a reword, calls
   `provider.get_description()` which returns the full CL description including trailing PR tags, then writes it
   directly to the `.gp` file via `update_changespec_description_atomic()` without stripping.

2. **`create_changespec_for_workflow()`** (`src/sase/workspace_provider/changespec.py:127`) — For non-git VCS, falls
   back to `commit_description` which is the full commit message (with tags appended by `_append_pr_tags()` in the
   commit workflow). For git VCS, this path is safe since `_get_commits_ahead()` only fetches subject lines
   (`--format=%s`).

## Approach

Create a `strip_pr_tags()` function and apply it at both entry points. The existing `_add_prettier_ignore_before_tags()`
in `reword.py` already has the exact regex pattern (`r"^[A-Z][A-Z0-9_]*="`) and scanning logic for detecting the
trailing tag block — the new function will reuse this pattern but remove the tags instead of inserting a comment before
them.

### Where to put `strip_pr_tags()`

`src/sase/vcs_provider/config.py` — this module already owns `get_pr_tags()` so it's the natural home for the inverse
operation. Both `reword.py` and `workspace_provider/changespec.py` already import from `sase.vcs_provider`.

### Changes

1. **`src/sase/vcs_provider/config.py`** — Add `strip_pr_tags(description: str) -> str` function that removes the
   trailing contiguous block of `KEY=value` lines (same regex as `_add_prettier_ignore_before_tags`). Also strip any
   trailing whitespace/blank lines left behind after removing tags.

2. **`src/sase/ace/handlers/reword.py:_sync_description_bg()`** — Call `strip_pr_tags()` on the description before
   passing it to `update_changespec_description_atomic()`.

3. **`src/sase/workspace_provider/changespec.py:create_changespec_for_workflow()`** — Call `strip_pr_tags()` on the
   `commit_description` fallback before using it (i.e., strip before passing to `_build_description()`).

4. **Tests** — Add unit tests for `strip_pr_tags()` covering: no tags, tags at end, mixed content, only tags, blank
   trailing lines before tags.
