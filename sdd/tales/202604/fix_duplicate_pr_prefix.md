---
create_time: 2026-04-12 12:36:34
status: done
prompt: sdd/prompts/202604/fix_duplicate_pr_prefix.md
---

# Fix Duplicate `[project]` PR Title Prefix

## Problem

PRs are consistently created with duplicate `[<project>]` prefixes in the title, e.g.:
`[bs_allow] [bs_allow] Implement MCR Advertiser Targeting UI Components`

## Root Cause

The prefix gets applied twice through two independent paths:

1. **Agent path**: When creating a PR, the agent writes a commit message. Agents frequently include a `[project]` prefix
   in the commit message itself (e.g., `[bs_allow] Implement MCR...`), since they see the project context and infer it's
   a convention.

2. **Workflow path**: `CommitWorkflow._apply_project_pr_prefix()` sets `_pr_title_prefix = "[bs_allow] "` in the
   payload. The GitHub plugin then constructs: `title = prefix + message.split("\n", 1)[0]`, blindly prepending the
   prefix to the first line of the message.

Result: `"[bs_allow] " + "[bs_allow] Implement MCR..."` = duplicate prefix.

### Key files in the flow:

- `src/sase/workflows/commit/workflow.py:331-344` — `_apply_project_pr_prefix()` sets `_pr_title_prefix`
- `../sase-github/src/sase_github/plugin.py:100-104` — constructs `title = prefix + first_line(message)`
- `src/sase/vcs_provider/config.py:53-65` — `strip_project_pr_prefix()` already exists but is unused in this flow

## Fix

Strip any existing `[...] ` prefix from the message inside `_apply_project_pr_prefix()`, right after setting
`_pr_title_prefix`. This is the correct location because:

- It's the centralized point where the prefix logic lives — all VCS plugins benefit
- The message is cleaned before it's used for the git commit, PR body, and PR title
- The existing `strip_project_pr_prefix()` utility does exactly this

### Phase 1: Core fix in `_apply_project_pr_prefix()`

**File**: `src/sase/workflows/commit/workflow.py`

After setting `_pr_title_prefix`, strip any existing prefix from the message to prevent duplication when the agent has
already included one.

### Phase 2: Add test coverage

**File**: `tests/test_project_pr_prefix.py`

Add a test that verifies the message is stripped when it already contains a `[project]` prefix — the exact scenario that
causes the duplication.

### Phase 3: Verify with `just check`

Run the full lint + test suite to confirm nothing breaks.
