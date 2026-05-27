---
create_time: 2026-05-27 13:03:21
status: done
prompt: sdd/prompts/202605/fix_finalizer_workspace_scope.md
---
# Plan: Scope Commit Finalizer Sibling Checks to Assigned Workspaces

## Problem

The failed `sase-47.2` agent ran in workspace `#10`, but the commit finalizer failed because it found dirty changes in
`sase_12`. That path is another checkout of the same primary repo, not the active workspace and not a configured sibling
repo resolved for workspace `#10`.

The likely regression is commit `b16698a5c` from May 26, 2026, which added "observed workspace" detection. That code
reads finalizer artifacts, extracts absolute paths from tool-call records, resolves same-remote git roots, and includes
dirty repositories outside the active workspace in the finalizer prompt. This can capture unrelated numbered workspaces
that appear in logs or tool output.

## Target Behavior

The finalizer should enforce commits only for:

1. The active project workspace resolved for the agent invocation.
2. Configured `sibling_repos` using the concrete `workspace_dir` assigned to the same workspace number by SASE workspace
   resolution, matching the path users get from `sase workspace open -p <sibling_repo> <workspace_num>`.

It should not scan or enforce arbitrary same-remote numbered workspaces merely because they were mentioned in
`tool_calls.jsonl`.

## Implementation Plan

1. Remove observed-workspace dirty enforcement from the commit finalizer state path.
   - Stop reading `tool_calls.jsonl` to discover extra repositories for commit enforcement.
   - Remove the `observed_workspace` dirty-repo kind from current behavior, unless compatibility aliases must remain for
     tests or imports.
   - Keep configured sibling checks based on `SASE_SIBLING_REPOS_JSON` first, then config fallback via
     `resolve_sibling_repos_for_project(..., materialize=False)`.

2. Preserve assigned sibling workspace semantics.
   - Ensure `_dirty_configured_sibling_repos` only checks `SiblingTarget.workspace_dir`.
   - Continue ignoring `workspace_strategy: none` entries for finalizer commit enforcement.
   - Confirm config fallback derives the workspace number from env or the active project path and resolves sibling paths
     through the same `WorkspaceStore` logic used by `sase workspace open`.

3. Add regression coverage.
   - Add a test where an agent in `sase_10` has finalizer artifacts mentioning dirty same-remote `sase_12`; the
     finalizer must report clean and not invoke the provider.
   - Keep or adjust existing configured-sibling tests to prove `sase-core_10` is still enforced.
   - Remove or rewrite tests that assert arbitrary observed same-repo workspaces trigger follow-up turns.

4. Update docs if needed.
   - Search documentation for the observed-workspace behavior introduced by the earlier commit.
   - Change finalizer docs to state that sibling repo enforcement is limited to configured sibling workspace
     directories.

5. Verify.
   - Run focused finalizer sibling tests.
   - Run `just install` if dependencies are not already prepared in this ephemeral workspace.
   - Run `just check` before finishing, because repo code changes are expected.

## Expected Outcome

An agent in workspace `#10` will no longer fail because another same-repo workspace such as `sase_12` has uncommitted
changes. Dirty configured sibling repositories still block finalization, but only at the workspace path resolved for the
agent's assigned workspace number.
