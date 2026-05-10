---
create_time: 2026-04-12 00:09:28
status: done
prompt: sdd/prompts/202604/fix_hg_commit_message.md
---

# Fix wrong Commit Message in agent details panel for hg-based agents

## Problem

The `sase ace` TUI agent details panel shows the wrong `Commit Message:` for agents that run on hg (Mercurial)
workspaces via the retired Mercurial plugin plugin. Instead of showing the specific commit entry message (e.g., "Restore
LINE_ITEM_BACKFILL validation to AdContentProtectionValidator"), it shows the overall CL description (e.g., "[bs_allow]
Extract AdvertiserBrandBlock validation into a standalone validator class.").

## Root Cause

The `hg.yml` xprompt in retired Mercurial plugin has a `diff` step that runs as a `finally` step after every agent run. When it
detects a commit (head hash changed), it sets `meta_commit_message` using:

```bash
commit_msg=$(hg log -r . --template '{desc|firstline}')
echo "meta_commit_message=$commit_msg"
```

In Mercurial, `hg log -r . --template '{desc|firstline}'` returns the **CL description** (the same for all amendments to
that CL), not the specific commit entry message the agent provided via `sase commit -m "..."`.

This output goes into `workflow_state.json` as the last step's output. When `extract_step_output_and_diff_path()` reads
the workflow state, it picks up the `diff` step's output (since it's the last step with dict output). The
`meta_commit_message` from the `diff` step is the CL description. The fallback to `commit_result.json` (which has the
correct agent message) never fires because `step_output` already has a truthy `meta_commit_message`.

### Data flow diagram

```
Agent calls: sase commit -m "Restore LINE_ITEM_BACKFILL validation..."
                |
                v
CommitWorkflow._write_result_marker()
  -> commit_result.json: { message: "Restore LINE_ITEM_BACKFILL..." }  (CORRECT)
                |
                v
hg.yml:diff (finally step, runs AFTER commit)
  -> hg log -r . --template '{desc|firstline}'
  -> meta_commit_message = "[bs_allow] Extract AdvertiserBrandBlock..."  (WRONG - CL desc)
  -> stored in workflow_state.json as last step output
                |
                v
extract_step_output_and_diff_path()
  -> step_output = diff step output (last step with dict output)
  -> step_output["meta_commit_message"] exists? YES -> skip commit_result.json fallback
  -> meta_commit_message = CL description (WRONG)
                |
                v
TUI displays: "Commit Message: [bs_allow] Extract AdvertiserBrandBlock..."  (WRONG)
```

## Fix

**File: `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/hg.yml`** (the `diff` step)

When `commit_result.json` exists in `SASE_ARTIFACTS_DIR`, read the commit message from it (first line of the `message`
field) instead of from `hg log`. Fall back to `hg log` only when `commit_result.json` doesn't exist (i.e., the agent
committed directly via `hg amend` without going through the sase commit workflow).

This ensures:

- **Commits via `sase commit`** (both `#commit` xprompt and stop hook): correct agent-provided message from
  `commit_result.json`
- **Commits outside sase** (agent ran `hg amend` directly): fallback to `hg log` CL description (best effort, same as
  today)
