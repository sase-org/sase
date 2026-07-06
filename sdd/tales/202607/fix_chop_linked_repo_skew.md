---
create_time: 2026-07-06 14:21:54
status: done
prompt: sdd/prompts/202607/fix_chop_linked_repo_skew.md
---
# Fix Chop-Launched Agent Failures from Stale Linked Repos

## Diagnosis

The configured `sase_fix_just` chop resolves correctly and launches the expected prompt:

```text
%n:sase_fix_just-@ #gh:sase %g:chop #!sase/fix_just
```

The launched workflow fails in its first hidden step, `_just_install`, because that step runs `just install`. The
`Justfile` prefers `SASE_LINKED_REPO_SASE_CORE_DIR` for local development and validates the linked `sase-core` checkout
before building `sase_core_rs`. The failed run saw `sase-core` source version `0.2.0`, while `pyproject.toml` requires
`sase-core-rs>=0.3.2,<0.4.0`.

The primary agent workspace is cleaned and updated before the agent runs, but linked repository workspaces are currently
only resolved/materialized and exported through env/meta. Existing linked workspaces are not cleaned, checked out to
their default parent, or synced. That allows a stale linked `sase-core` checkout to poison `just install` even though
the primary `sase` workspace is fresh.

## Goal

Make normal agent launches prepare suffix-strategy linked repository workspaces before the agent workflow can consume
them, so configured chops and regular launches see a consistent primary-plus-linked workspace set.

## Implementation Plan

1. Add a linked-repo preparation helper in the agent runner setup path.
   - Reuse the existing `prepare_workspace()` behavior so linked repos get the same clean, checkout, and sync semantics
     as the primary workspace.
   - Prepare only workspace-backed linked repos, not static `workspace.strategy: none` entries.
   - Use each linked repo's own default parent revision rather than trying to apply the primary repo's branch name
     across repositories.
   - Surface a clear failure if linked repo preparation fails, so bootstrap failures point at the stale linked workspace
     cause directly.

2. Call the helper in the same lifecycle windows as primary workspace prep.
   - For regular non-home, non-deferred, non-retry-preserved launches, prepare linked repos after the primary workspace
     has been prepared and linked repo env/meta has been refreshed.
   - For deferred `%wait` launches, prepare linked repos after the deferred workspace is actually claimed and refreshed.
   - Preserve retry-spawn behavior that intentionally keeps in-progress workspace edits.

3. Keep metadata and environment behavior stable.
   - Continue writing canonical `linked_repos` metadata and compatibility `sibling_repos` metadata.
   - Do not change chop configuration, the `fix_just` xprompt, or memory/config files.

4. Add focused regression coverage.
   - Verify suffix-strategy linked repos are prepared with the default revision sentinel.
   - Verify static linked repos are not prepared.
   - Verify a linked prep failure aborts before workflow execution with an actionable error.
   - Keep existing linked repo env/meta tests passing.

5. Verify.
   - Run the targeted unit tests for linked repo runner setup.
   - Because this changes repo files, run `just install` and then `just check`.
   - After the code fix, repair the currently stale linked checkout or rerun the chop under the updated launcher to
     confirm `just install` reaches the Rust build using a compatible `sase-core`.
