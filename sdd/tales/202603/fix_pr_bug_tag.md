---
create_time: 2026-03-28 14:50:42
status: done
prompt: sdd/prompts/202603/fix_pr_bug_tag.md
---

# Fix Missing BUG=<bug_id> PR Tag in #pr Xprompt Workflow

## Problem

When creating PRs via the `#pr` xprompt with a non-zero `bug_id` input, the `BUG=<bug_id>` tag is NOT added to the PR
description. The default PR tags from config (e.g., retired Mercurial plugin's `AUTOSUBMIT_BEHAVIOR`, `MARKDOWN`, etc.) ARE added
correctly.

## Root Cause

The `#pr` xprompt sets `SASE_BUG_ID` as an environment variable. The commit workflow has two separate consumers of
bug-related data, and neither adds `BUG=` to the PR description:

1. **`_append_pr_tags()`** (workflow.py:276-286) — reads static tags from `vcs_provider.pr_tags` config. Does NOT read
   `SASE_BUG_ID` from the environment. This is what adds `AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, etc.

2. **`_create_changespec()`** (workflow.py:368-385) — reads `SASE_BUG_ID` and passes it to
   `create_changespec_for_workflow()` as the `bug` parameter. This adds `BUG: http://b/<id>` to the ChangeSpec, NOT to
   the PR description.

The workspace provider's `ws_format_commit_description` hook (retired Mercurial plugin's workspace_plugin.py:123-149) DOES add
`BUG=<bug_id>` — but only for `workflow_type == "hg"`, and it's never called from the commit workflow's
`create_pull_request` path. It's a leftover from the pre-VCS-agnostic architecture.

### Overwrite Concern

The default PR tags do NOT overwrite BUG — `_append_pr_tags()` simply never adds BUG in the first place. There's no
conflict or overwriting; BUG was just never wired into this code path.

## Fix

Modify `_append_pr_tags()` to inject `BUG=<bug_id>` from the `SASE_BUG_ID` environment variable (when set and non-zero)
into the tags dict before rendering the tag lines.

### Phase 1: Add BUG tag injection to `_append_pr_tags()`

**File:** `src/sase/workflows/commit/workflow.py`

In `_append_pr_tags()`, after reading `get_pr_tags()`, read `SASE_BUG_ID` from the environment. If it's set and
non-zero, inject `BUG=<bug_id>` into the tags dict. Place it before the other tags so it appears near the top of the tag
block (matching the position in `ws_format_commit_description`).

Key considerations:

- Only inject when `SASE_BUG_ID` is set, non-empty, and not "0"
- Even if `get_pr_tags()` returns an empty dict, we should still append the BUG tag (handles the GitHub-only case where
  no default pr_tags are configured)
- If the config already includes a static `BUG` key, the env var should take precedence (dynamic > static)

### Phase 2: Add test coverage

**File:** `tests/test_pr_tags.py`

Add test cases:

- `SASE_BUG_ID` set → `BUG=<id>` appears in appended tags
- `SASE_BUG_ID=0` → no BUG tag
- `SASE_BUG_ID` unset → no BUG tag
- `SASE_BUG_ID` set with existing pr_tags → BUG appears alongside config tags
- `SASE_BUG_ID` set with static BUG in config → env var wins

### Phase 3: Deduplicate retired Mercurial plugin `ws_format_commit_description` (follow-up)

The retired Mercurial plugin workspace plugin's `ws_format_commit_description` hardcodes the same tags now available via
`vcs_provider.pr_tags` config (AUTOSUBMIT_BEHAVIOR, MARKDOWN, R, STARTBLOCK_AUTOSUBMIT, WANT_LGTM) plus BUG. Now that
`_append_pr_tags()` handles both config tags and BUG injection, the hardcoded tags in the workspace plugin are redundant
for the PR creation path. This is a separate cleanup concern and can be addressed later.
