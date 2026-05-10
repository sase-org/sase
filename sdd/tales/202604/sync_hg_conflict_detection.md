---
create_time: 2026-04-01 12:25:24
status: done
prompt: sdd/prompts/202604/sync_hg_conflict_detection.md
---

# Plan: Fix #sync xprompt merge conflict detection for hg VCS provider

## Problem

The `#sync` xprompt workflow fails to detect merge conflicts from the hg VCS provider. When `hg sync` encounters merge
conflicts, the workflow reports `has_conflicts: false`, causing the resolve agent step to be skipped. The sync is then
misclassified as a "non-conflict error."

## Root Cause

Two bugs work together to produce this failure:

### Bug 1: `retired_mercurial_plugin_sync` aborts the rebase before conflict detection can run

The `retired_mercurial_plugin_sync` bash script (in retired Mercurial plugin repo) has this flow:

```bash
if ! hg sync "$@"; then
    status_output=$(hg status)
    if echo "$status_output" | grep -q "Unresolved merge conflicts"; then
        echo "Error: hg sync failed due to unresolved merge conflicts. Aborting rebase..." >&2
        hg rebase --abort    # <-- THIS IS THE PROBLEM
    fi
    exit 1
fi
```

After `hg sync` fails with merge conflicts, the script **aborts the rebase** before returning control to
`sync_attempt.py`. When `sync_attempt.py` then calls `provider.is_sync_in_progress(cwd)` (which runs
`hg resolve --list`), the rebase has already been aborted — there are no unresolved files to detect. So
`has_conflicts=false`.

This script predates the `#sync` workflow's resolve agent. The abort-on-conflict behavior was correct when there was no
automated conflict resolution, but now it destroys the state the resolve agent needs.

### Bug 2: Mercurial resolve instructions are missing `hg rebase --continue`

The sync workflow's resolve agent instructions for Mercurial stop at `hg resolve --mark`:

```
4. **Mark resolved**: Run `hg resolve --mark <file>` for EACH resolved file
5. **Check**: Run `hg resolve --list` again — if all show `R`, set `all_resolved=true`
```

Compare with the git instructions, which include continuing the rebase:

```
4. **Stage resolved files**: Run `git add <file>` for EACH resolved file
5. **Continue rebase**: Run `git -c core.editor=true rebase --continue`
   - If this produces MORE conflicts, set `all_resolved=false`
   - If this succeeds (exit code 0), set `all_resolved=true`
```

Without `hg rebase --continue`, the resolve agent would mark conflicts as resolved but never finish the rebase. A
multi-commit rebase could hit conflicts at each commit boundary — the repeat loop handles this for git but not for hg.

## Fix

### Phase 1: Stop aborting the rebase in `retired_mercurial_plugin_sync` (retired Mercurial plugin repo)

**File**: `src/retired_mercurial_plugin/scripts/retired_mercurial_plugin_sync`

When merge conflicts are detected, exit with failure but **do not** abort the rebase. This leaves the workspace in a
conflicted state that `sync_attempt.py` can detect.

The conflict message should still be printed (it appears in the TUI output), but without the "Aborting rebase..." part.

### Phase 2: Add `hg rebase --continue` to resolve instructions (sase_101 repo)

**File**: `src/sase/xprompts/sync.yml`

Update the Mercurial conflict resolution instructions in the resolve agent step to include continuing the rebase after
marking all files resolved, mirroring the git flow:

```
4. **Mark resolved**: Run `hg resolve --mark <file>` for EACH resolved file
5. **Continue rebase**: Run `hg rebase --continue`
   - If this produces MORE conflicts, set `all_resolved=false`
   - If this succeeds (exit code 0), set `all_resolved=true`
6. **Verify**: Run `hg resolve --list` to check for remaining conflicts
```
