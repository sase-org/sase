---
create_time: 2026-03-25 19:08:39
status: wip
bead_id: sase-c
prompt: sdd/prompts/202603/vcs_abandon_change.md
---

# Plan: VCS-agnostic `abandon_change` hook for closing remote changes during revert

## Problem

When reverting a ChangeSpec that has an associated GitHub PR, the PR is left open on GitHub. The current
`revert_changespec()` flow calls `provider.prune()` which in `GitCommon` only does `git branch -D` (local branch
deletion). The PR on GitHub is orphaned.

By contrast, the Google/hg provider's `retired_mercurial_plugin_prune` script runs `hg cls-drop --prune` which handles both local and
remote CL cleanup in one step.

We need a VCS-agnostic hook that providers implement to close/abandon the remote change (PR, CL) during revert, so the
core revert logic doesn't need provider-specific knowledge.

## Design

Add a new **optional** VCS hook `vcs_abandon_change(cl, revision, cwd)` that closes the remote change associated with a
ChangeSpec being reverted or archived.

**Why a new hook instead of modifying `vcs_prune`?**

- `vcs_prune` semantics are "delete the local VCS revision/branch" - clean separation of concerns
- The remote change (PR/CL) is a distinct concept from the local branch
- `gh pr close` needs the CL URL/number, which `vcs_prune` doesn't receive (it only gets the resolved revision)

**Hook signature:**

```python
def vcs_abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]
```

- `cl`: The ChangeSpec's CL value (PR URL for GitHub, CL number for Google)
- `revision`: The resolved VCS revision/branch name
- `cwd`: Workspace directory

**Call site:** In `revert_changespec()`, call `provider.abandon_change()` **before** `provider.prune()` since
`gh pr close` may need the branch context to exist. Also add the call to `archive_changespec()` before
`provider.archive()` for the same reason.

## Changes

### Phase 1: Core hook infrastructure (sase_103)

#### 1.1 `src/sase/vcs_provider/_hookspec.py` - Add hookspec

Add under "VCS-agnostic operations" section:

```python
@hookspec(firstresult=True)
def vcs_abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]: ...
```

#### 1.2 `src/sase/vcs_provider/_base.py` - Add to abstract base

Add as an optional method with a no-op default (like `get_change_url`):

```python
def abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]:
    """Abandon/close the remote change (PR, CL) associated with a revision.

    Called during revert/archive before the local revision is pruned.
    The default implementation is a no-op — providers that manage remote
    changes (PRs, CLs) should override this.

    Returns ``(True, None)`` on success or no-op.
    """
    return (True, None)
```

#### 1.3 `src/sase/vcs_provider/_plugin_manager.py` - Add delegation

Add method that delegates to the pluggy hook, falling back to no-op when no plugin handles it:

```python
def abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]:
    result = self._pm.hook.vcs_abandon_change(cl=cl, revision=revision, cwd=cwd)
    if result is None:
        return (True, None)  # No plugin handles it — no-op
    return result
```

#### 1.4 `src/sase/ace/revert.py` - Call hook during revert

After resolving the revision and before calling `provider.prune()`, add:

```python
# Abandon remote change (close PR, drop CL, etc.)
success, error = provider.abandon_change(changespec.cl, resolved, workspace_dir)
if not success:
    return (False, f"Failed to abandon remote change: {error}")

if console:
    console.print(f"[green]Abandoned remote change: {changespec.cl}[/green]")
```

#### 1.5 `src/sase/ace/archive.py` - Call hook during archive

Same pattern, before `provider.archive()`:

```python
# Abandon remote change (close PR, drop CL, etc.)
success, error = provider.abandon_change(changespec.cl, resolved, workspace_dir)
if not success:
    return (False, f"Failed to abandon remote change: {error}")

if console:
    console.print(f"[green]Abandoned remote change: {changespec.cl}[/green]")
```

Note: `archive_changespec` already has `changespec.cl` available (it validates `cl is not None` at the top).

### Phase 2: GitHub implementation (sase-github)

#### 2.1 `src/sase_github/plugin.py` - Implement hook

Add to `GitHubPlugin`:

```python
@hookimpl
def vcs_abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]:
    """Close the GitHub PR and delete the remote branch."""
    # Close the PR using the CL URL (which is the PR URL for GitHub)
    out = self._run(["gh", "pr", "close", cl, "--delete-branch"], cwd)
    if not out.success:
        # PR may already be closed/merged — treat as success
        if "already" in out.stderr.lower() or "not found" in out.stderr.lower():
            return (True, None)
        return self._to_result(out, "gh pr close")
    return (True, None)
```

The `--delete-branch` flag on `gh pr close` also deletes the remote branch, so we don't need a separate
`git push origin --delete`.

If the PR is already closed or merged, we treat it as success (idempotent).

### Phase 3: Google implementation (retired Mercurial plugin)

#### 3.1 `src/retired_mercurial_plugin/plugin.py` - Implement hook

For Google, `vcs_prune` already calls `retired_mercurial_plugin_prune` which does `hg cls-drop --prune`. The `abandon_change` hook
should handle the CL-number removal part, while prune handles the local branch deletion.

However, since `retired_mercurial_plugin_prune` already bundles both operations, and refactoring it would be risky, the Google
implementation should be a **no-op with a comment** explaining that `vcs_prune` already handles remote CL cleanup:

```python
@hookimpl
def vcs_abandon_change(self, cl: str, revision: str, cwd: str) -> tuple[bool, str | None]:
    """No-op — retired_mercurial_plugin_prune (called via vcs_prune) already handles CL cleanup."""
    return (True, None)
```

Alternatively, if the user wants a cleaner separation, we could refactor `retired_mercurial_plugin_prune` to only handle local
pruning and move the `hg cls-drop` into `vcs_abandon_change`. But that's a riskier change and can be done as a
follow-up.

### Phase 4: Bare git default (sase_103)

#### 4.1 `src/sase/vcs_provider/plugins/_git_common.py` - No changes needed

`GitCommon` does **not** need to implement `vcs_abandon_change` — the `VCSPluginManager` falls back to no-op when no
plugin handles the hook, and bare git repos have no remote PRs.

## File change summary

| File                                       | Repo        | Change                                                   |
| ------------------------------------------ | ----------- | -------------------------------------------------------- |
| `src/sase/vcs_provider/_hookspec.py`       | sase_103    | Add `vcs_abandon_change` hookspec                        |
| `src/sase/vcs_provider/_base.py`           | sase_103    | Add `abandon_change` optional method                     |
| `src/sase/vcs_provider/_plugin_manager.py` | sase_103    | Add `abandon_change` delegation                          |
| `src/sase/ace/revert.py`                   | sase_103    | Call `provider.abandon_change()` before prune            |
| `src/sase/ace/archive.py`                  | sase_103    | Call `provider.abandon_change()` before archive          |
| `src/sase_github/plugin.py`                | sase-github | Implement `vcs_abandon_change` with `gh pr close`        |
| `src/retired_mercurial_plugin/plugin.py`                | retired Mercurial plugin | Implement `vcs_abandon_change` (no-op, prune handles it) |

## Testing

- Revert a GitHub ChangeSpec with an open PR: verify PR is closed and remote branch deleted
- Revert a GitHub ChangeSpec with no PR (CL is None): verify no abandon_change call
- Revert a GitHub ChangeSpec with already-closed PR: verify idempotent success
- Archive a GitHub ChangeSpec with an open PR: verify PR is closed
- Verify bare-git revert still works (no-op fallback)
- `just check` passes in all three repos
