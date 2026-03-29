---
create_time: 2026-03-29 19:23:58
status: done
---

# Plan: Fix rename action to persist branch alias for immutable-branch providers

## Problem

When renaming a ChangeSpec via the `n` keymap in `sase ace`, the `_execute_rename` method in
`src/sase/ace/tui/actions/rename.py` always calls `provider.rename_branch(new_name, workspace_dir)` which does
`git branch -m new_name` locally. This is wrong for GitHub because:

1. GitHub branches are immutable once pushed with a PR (`vcs_can_rename_branch` returns `False` in the sase-github
   plugin)
2. The remote branch still has the old name after the local rename
3. No `branch_map.json` entry is written, so `resolve_revision` cannot find the branch using the new ChangeSpec name
4. Future operations (checkout, diff, rebase) on the renamed ChangeSpec will fail

## Existing Pattern

The `handle_suffix_strip` and `handle_suffix_append` functions in `src/sase/status_state_machine/suffix.py` already
handle this correctly:

```python
if not provider.can_rename_branch(workspace_dir):
    # Branch is immutable — persist alias instead of renaming
    branch_map = read_branch_map(project_basename)
    actual_branch = branch_map.get(old_name)
    if actual_branch:
        remove_branch_alias(project_basename, old_name)
        write_branch_alias(project_basename, new_name, actual_branch)
    else:
        old_branch = resolved.removeprefix("origin/")
        write_branch_alias(project_basename, new_name, old_branch)
else:
    # Mutable — rename locally and push
    rename_ok, rename_err = provider.rename_branch(new_branch, workspace_dir)
    if rename_ok:
        _push_branch_rename(workspace_dir, new_branch, resolved)
        remove_branch_alias(project_basename, new_name)
```

## Fix

Modify `_execute_rename` in `src/sase/ace/tui/actions/rename.py` to follow the same pattern:

1. After checking out the old branch, check `provider.can_rename_branch(workspace_dir)`
2. **If immutable (GitHub)**: Check if old name has an existing alias in `branch_map.json`. If so, re-key it to the new
   name. Otherwise, use the resolved branch name as the actual branch and write a new alias.
3. **If mutable**: Keep existing `rename_branch` call, but also push the rename to remote via `_push_branch_rename`
   (currently missing) and clean up any stale alias.

### Files to change

| File                                 | Change                                                                |
| ------------------------------------ | --------------------------------------------------------------------- |
| `src/sase/ace/tui/actions/rename.py` | Add `can_rename_branch` check + branch_map logic in `_execute_rename` |

### Testing considerations

- Existing `tests/test_branch_map.py` covers branch_map CRUD
- The rename action's VCS interaction is hard to unit-test (requires real git repos), but the logic follows the
  already-proven suffix.py pattern
