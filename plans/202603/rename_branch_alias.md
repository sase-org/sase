---
create_time: 2026-03-29 18:41:32
status: done
---

# Plan: Fix missing branch alias write when renaming a ChangeSpec on GitHub

## Problem

When a user renames a ChangeSpec via the `n` keymap in `sase ace`, the rename action calls `provider.rename_branch()`
unconditionally. On GitHub, branches can't be renamed once a PR is open (`can_rename_branch()` returns `False`), so the
local `git branch -m` may succeed but the remote branch stays unchanged. Critically, **no branch alias is written**, so
`resolve_revision()` can no longer find the branch under the new ChangeSpec name.

The `suffix.py` module already handles this correctly: it checks `can_rename_branch()` first and falls back to
`write_branch_alias()` for immutable-branch providers. The rename action needs the same pattern.

## Scope

Single file change: `src/sase/ace/tui/actions/rename.py`

## Changes

### Phase 1: Add immutable-branch handling to `_execute_rename()`

In the `run_handler()` closure (around line 162), replace the unconditional `provider.rename_branch()` call with the
same check-then-alias pattern used in `suffix.py`:

1. After resolving and checking out the old branch, call `provider.can_rename_branch(workspace_dir)`.
2. **If immutable** (`False`): call `write_branch_alias(project_basename, new_name, resolved_branch)` where
   `resolved_branch` is the actual branch name (with `origin/` prefix stripped). Skip the `rename_branch()` call
   entirely — the local branch rename is pointless when the remote can't follow.
3. **If mutable** (`True`): call `provider.rename_branch()` as today, and clean up any stale alias via
   `remove_branch_alias()`.

### Phase 2: Verify with tests

Add a test (or extend existing rename tests) that mocks `can_rename_branch()` returning `False` and asserts that
`write_branch_alias()` is called with the correct arguments and `rename_branch()` is NOT called.
