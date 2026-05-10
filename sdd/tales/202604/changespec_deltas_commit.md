---
create_time: 2026-04-30 11:21:59
status: done
prompt: sdd/prompts/202604/changespec_deltas_commit.md
---
# Plan: Populate DELTAS for ChangeSpecs Created by `sase commit`

## Problem

New ChangeSpecs created by the `sase commit` `create_pull_request` flow can be written without a `DELTAS:` field. This
is especially visible on machines using the adjacent `retired Mercurial plugin` plugin for Mercurial/Fig workspaces.

## Root Cause

There are two coupled gaps:

1. Core `sase` creates the new ChangeSpec through `create_changespec_for_workflow()` and writes an initial `COMMITS:`
   block via `add_changespec_to_project_file()`, but it does not call the DELTAS refresh path afterward. Existing
   follow-up commit/proposal entry paths call `refresh_deltas_after_commits_change()`, but initial ChangeSpec creation
   bypasses that hook.

2. The `retired Mercurial plugin` Mercurial VCS plugin implements committed and uncommitted diff helpers, but does not implement
   `vcs_diff_name_status`. The DELTAS computation path requires that hook to turn a parent/head revision pair into
   file-level `A/M/D` entries. Without it, any refresh attempted in an hg workspace is best-effort skipped.

The result is: core does not request a DELTAS refresh for newly-created ChangeSpecs, and even if it did, `retired Mercurial plugin`
currently lacks the provider hook needed for the refresh to succeed.

## Implementation Plan

1. Add core DELTAS refresh after successful new ChangeSpec creation.
   - In `src/sase/workspace_provider/changespec.py`, after `add_changespec_to_project_file()` returns a ChangeSpec name,
     invoke `refresh_deltas_after_commits_change(project_file, result, workspace_dir=os.getcwd())`.
   - Treat refresh as best-effort and non-blocking, matching the existing DELTAS lifecycle behavior for commit-entry
     updates.
   - Do not fail ChangeSpec creation if DELTAS cannot be computed.

2. Add targeted core tests.
   - Verify `create_changespec_for_workflow()` calls DELTAS refresh when a ChangeSpec is created.
   - Verify no refresh is attempted when no ChangeSpec is created.
   - Keep existing assertions around `create_changespec()` call shape updated if needed.

3. Add Mercurial name-status support in `../retired Mercurial plugin`.
   - Implement `vcs_diff_name_status(parent_ref, head_ref, cwd)` using `hg status --rev <parent_ref> --rev <head_ref>`.
   - Translate Mercurial status letters to the Git-style letters expected by core DELTAS:
     - `M` -> `M`
     - `A` -> `A`
     - `R` -> `D`
     - skip clean/unknown/ignored/copy-source helper lines
     - conservatively map unexpected non-empty status letters to `M`
   - Raise `VCSOperationError("diff_name_status", ...)` on command failure, consistent with Git provider behavior.
   - Leave line stats unsupported for now; core already treats `diff_line_stats` as optional and will still write
     file-level DELTAS.

4. Add `retired Mercurial plugin` tests.
   - Unit-test `vcs_diff_name_status()` parsing for modified, added, removed, ignored helper lines, and unexpected
     status letters.
   - Unit-test command failure raises `VCSOperationError`.

5. Verify.
   - Run focused core tests for commit ChangeSpec creation and DELTAS persistence/refresh.
   - Run focused `retired Mercurial plugin` hg plugin tests.
   - Because both repos will be modified, run `just check` in `sase_100` and `../retired Mercurial plugin` after `just install` if
     needed.
