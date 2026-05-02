---
create_time: 2026-04-12 12:29:34
status: done
prompt: sdd/prompts/202604/inherit_parent_pr_tags.md
---

# Plan: Inherit PR Tags from Parent PR

## Problem

When `sase commit` creates a new PR that is a child of an existing PR, it only includes PR tags from the user's
`sase.yml` config (`pr_tags`) and the `BUG` environment variable. Tags that were set on the parent PR (e.g. `FOO=bar`)
are lost, requiring manual re-entry.

## Goal

Automatically inherit all PR tags from the parent PR's description when creating a child PR. Explicitly configured tags
(from config or BUG) should take precedence over inherited ones.

## Design

The existing `_append_pr_tags()` method in `CommitWorkflow` already assembles tags from config and BUG. We extend it to
first fetch the parent PR's body, extract its tags, then layer config/BUG tags on top.

**Tag precedence (lowest to highest):**

1. Parent PR tags (inherited)
2. Config `pr_tags` from `sase.yml`
3. BUG tag from payload/env

### Phase 1: Add `extract_pr_tags()` utility

**File:** `src/sase/vcs_provider/config.py`

Add an `extract_pr_tags(description: str) -> dict[str, str]` function — the read counterpart of the existing
`strip_pr_tags()`. It scans the trailing contiguous block of `KEY=value` lines (using the existing `_TAG_PATTERN` regex)
and returns them as a dict.

### Phase 2: Add `get_change_body` to the VCS provider interface

Three files need the new method, following the existing pattern (e.g. `get_change_url`):

1. **`src/sase/vcs_provider/_hookspec.py`** — add
   `vcs_get_change_body(change_ref: str, cwd: str) -> tuple[bool, str | None]` hookspec
2. **`src/sase/vcs_provider/_base.py`** — add `get_change_body()` default that raises `NotImplementedError`
3. **`src/sase/vcs_provider/_plugin_manager.py`** — add delegation via `_call_or_raise`

**GitHub plugin** (`../sase-github/src/sase_github/plugin.py`): implement using
`gh pr view <change_ref> --json body -q .body`.

### Phase 3: Wire up inheritance in `CommitWorkflow._append_pr_tags()`

**File:** `src/sase/workflows/commit/workflow.py`

Modify `_append_pr_tags()` to:

1. Check `self._parent_cl_name`
2. Look up parent ChangeSpec via `get_changespec_from_file()` to get its `cl` URL
3. Call `provider.get_change_body(cl_url, cwd)` to fetch the parent PR body
4. Call `extract_pr_tags(body)` to get parent tags
5. Merge: `{**parent_tags, **config_tags}`, then apply BUG override on top
6. Wrap in try/except — parent tag fetch is best-effort, never blocks PR creation

### Phase 4: Tests

**File:** `tests/test_pr_tags.py`

- Unit tests for `extract_pr_tags()` (simple tags, mixed content, no tags, empty string)
- Workflow integration tests:
  - Parent tags inherited into child PR message
  - Config tags override same-named parent tags
  - BUG tag overrides parent BUG tag
  - Graceful no-op when parent body fetch fails
