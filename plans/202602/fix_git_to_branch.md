---
bead_id: sase-g61
---

# Fix: ChangeSpec name ≠ git branch name across all VCS call sites

## Context

ChangeSpec names (e.g., `sase_dull_basin__1`) differ from actual git branch names (e.g., `dull-basin`) for ChangeSpecs
created via xprompt workflows. The xprompt `create_changespec_for_workflow()` never renames the branch to match (unlike
the interactive commit workflow). This breaks any code that passes `changespec.name` to git as a revision — currently
~15 call sites.

## Design

### Core approach: `resolve_revision()` on VCS provider

After fixing the root cause (renaming branches in `create_changespec_for_workflow`), new ChangeSpecs will have matching
branch names but old ones won't. A blind transformation would break renamed branches. So we add a `resolve_revision()`
method to the VCS provider:

- **`_base.py`**: Default returns `changespec_name` as-is (correct for hg)
- **`_git.py`**: Checks if `changespec_name` is a valid git ref (`git rev-parse --verify --quiet`); if yes, returns it;
  if not, derives the branch name via `changespec_name_to_branch()`

Each call site then does:

```python
revision = provider.resolve_revision(changespec.name, changespec.project_basename, cwd)
provider.checkout(revision, cwd)
```

---

## Phase 1: Foundation + original bug fix

**Goal**: Add shared infrastructure and fix the user's immediate bug.

### 1a. Add `changespec_name_to_branch()` to `src/sase/sase_utils.py`

Extract from `git_submit.py:29-39` into a shared utility. Takes `(name: str, project_basename: str) -> str`.

### 1b. Update `src/sase/git_submit.py`

Replace private `_changespec_name_to_branch()` with import from `sase_utils`.

### 1c. Add `resolve_revision()` to VCS provider

- `src/sase/vcs_provider/_base.py` — optional method, default returns name as-is
- `src/sase/vcs_provider/_git.py` — check `git rev-parse --verify --quiet <name>`, fall back to
  `changespec_name_to_branch()`

### 1d. Add `show_revision()` to VCS provider

- `src/sase/vcs_provider/_base.py` — optional method
- `src/sase/vcs_provider/_git.py` — `git show <revision>`

### 1e. Fix `src/sase/ace/handlers/show_diff.py`

Use `resolve_revision()` + `show_revision()` instead of `diff_revision(changespec.name)`.

### 1f. Fix root cause — `src/sase/workspace_changespec.py`

After `add_changespec_to_project_file()` returns the suffixed name, rename the git branch via
`subprocess.run(["git", "branch", "-m", suffixed_name])`. Non-fatal on failure.

### Files

- `src/sase/sase_utils.py`
- `src/sase/git_submit.py`
- `src/sase/vcs_provider/_base.py`
- `src/sase/vcs_provider/_git.py`
- `src/sase/ace/handlers/show_diff.py`
- `src/sase/workspace_changespec.py`

---

## Phase 2: Core operations and handlers

**Goal**: Fix the main operational code paths that use `changespec.name` as a git ref.

### 2a. `src/sase/ace/operations.py`

- `update_to_changespec()` (line 146): Use `resolve_revision()` for the checkout target
- `save_diff_to_file()` (line 244): Use `resolve_revision()` + `show_revision()`

### 2b. `src/sase/ace/archive.py`

- Line 112: `provider.checkout(changespec.name, ...)` → use `resolve_revision()`
- Line 137: `provider.archive(changespec.name, ...)` → use resolved revision

### 2c. `src/sase/ace/revert.py`

- Line 149: `provider.prune(changespec.name, ...)` → use resolved revision

### 2d. `src/sase/ace/mail_ops.py`

- Line 305: `_get_cl_description(changespec.name, ...)` → resolve first
- Lines 393, 408, 413, 428: checkout calls → resolve first
- Line 492: `provider.mail(changespec.name, ...)` → resolve first

### 2e. `src/sase/ace/handlers/reword.py`

- Line 92: `provider.get_description(changespec_name, ...)` → resolve first
- Lines 228, 342: `provider.checkout(changespec.name, ...)` → resolve first

### Files

- `src/sase/ace/operations.py`
- `src/sase/ace/archive.py`
- `src/sase/ace/revert.py`
- `src/sase/ace/mail_ops.py`
- `src/sase/ace/handlers/reword.py`

---

## Phase 3: TUI actions, schedulers, and internals

**Goal**: Fix remaining call sites in TUI, schedulers, and status machine.

### 3a. `src/sase/ace/tui/actions/base.py`

- Line 483: `provider.checkout(changespec.name, ...)` (tmux action) → resolve
- Line 546: `provider.checkout(changespec.name, ...)` (checkout action) → resolve

### 3b. `src/sase/ace/tui/actions/axe.py`

- Line 269: `provider.checkout(cl_name, ...)` → resolve

### 3c. `src/sase/ace/tui/actions/rename.py`

- Line 142: `provider.checkout(old_name, ...)` → resolve
- Line 151: `provider.rename_branch(new_name, ...)` — may need special handling

### 3d. `src/sase/ace/scheduler/hooks_runner.py`

- Lines 345-346: `provider.checkout(changespec.name, ...)` → resolve
- Line 577: `provider.checkout(changespec.name, ...)` → resolve

### 3e. `src/sase/ace/scheduler/workflows_runner/starter.py`

- Line 212: `provider.checkout(changespec.name, ...)` → resolve

### 3f. `src/sase/status_state_machine/transitions.py`

- Lines 165, 170, 216, 221: checkout and rename_branch calls during status transitions → resolve

### 3g. `src/sase/commit_workflow/workflow.py`

- Line 195: `provider.commit(full_name, ...)` — verify this still works correctly
- Line 256: `provider.rename_branch(suffixed_name, ...)` — verify

### Files

- `src/sase/ace/tui/actions/base.py`
- `src/sase/ace/tui/actions/axe.py`
- `src/sase/ace/tui/actions/rename.py`
- `src/sase/ace/scheduler/hooks_runner.py`
- `src/sase/ace/scheduler/workflows_runner/starter.py`
- `src/sase/status_state_machine/transitions.py`
- `src/sase/commit_workflow/workflow.py`

---

## Verification (each phase)

1. `just check` — formatting, linting, tests pass
2. Phase 1 specifically: `sase ace` → CLs tab → select xprompt-created ChangeSpec → "d" → diff displays
