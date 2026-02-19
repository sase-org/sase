# Git Change Specs v3: Clones Replace Worktrees, Direct Master Commits

## Context

The current `#gh` / `#git` workflow uses **git worktrees** for secondary workspaces and **random branch names**
(adjective-noun pairs like "dull-basin") for each agent run. This creates unnecessary complexity: worktrees prevent
having the same branch checked out in multiple directories, branch names add naming indirection, and the commit/submit
pipeline has many steps (create branch, commit to branch, create ChangeSpec, submit = merge branch to master).

**v3 replaces this with a simpler model**: each workspace is an independent `git clone` (all on `master`), agents commit
directly to master, and changes are auto-pushed. ChangeSpecs are only created when a PR is explicitly requested via
`#pr:<name>`.

Note: v2 Phases 1 (STATUS renaming) and 2 (workflow renaming) are **already implemented** and carry forward as-is.

---

## Phase 1: Replace Worktrees with Clones + Remove Branch Names

**Goal**: Replace worktree infrastructure with clone infrastructure. Delete all branch name generation code.

### 1a. Replace `ensure_git_worktree` with `ensure_git_clone`

**`src/sase/gh_workspace.py`**:

- Rename `_get_git_worktree_dir()` → `_get_git_clone_dir()` (body unchanged, same `primary__N/` path pattern)
- Replace `ensure_git_worktree()` with `ensure_git_clone()`:
  - Workspace 1: verify primary dir exists (unchanged)
  - Workspace 2+: `git clone primary_dir clone_dir` (local clone, hard-linked objects)
  - After cloning: re-point `origin` to the real remote (not the primary workspace) using
    `git remote set-url origin <real_origin_url>`
  - Add race-condition guard: if `git clone` fails, check if dir already exists (another process may have created it)
- Update module docstring ("worktrees" → "clone workspaces")

### 1b. Update all callers of `ensure_git_worktree`

| File                                                                              | Change                                                                                                  |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `src/sase/running_field.py` (`get_workspace_directory()`, line 553)               | Import and call `ensure_git_clone` instead of `ensure_git_worktree`                                     |
| `src/sase/ace/tui/actions/_agent_workflow_launch.py` (lines 41, 55-57, 77, 92-94) | Import and call `ensure_git_clone` in both `_resolve_gh_from_prompt()` and `_resolve_git_from_prompt()` |
| `src/sase/ace/scheduler/workflows_runner/starter.py` (lines 135-138, 161)         | Import and call `ensure_git_clone` in `_start_crs_workflow()`                                           |
| `xprompts/gh.yml` (lines 16, 38, 41)                                              | Import and call `ensure_git_clone`                                                                      |
| `xprompts/git.yml` (lines 17, 39, 42)                                             | Import and call `ensure_git_clone`                                                                      |

### 1c. Delete branch name generation

| Action                                           | File                                                                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| **DELETE**                                       | `src/sase/branch_names.py` (entire module)                                                                  |
| **DELETE**                                       | `tests/test_branch_names.py` (entire test file)                                                             |
| **Remove** `changespec_name_to_branch()`         | `src/sase/sase_utils.py` (lines 90-100)                                                                     |
| **Remove** import of `changespec_name_to_branch` | `src/sase/vcs_provider/_git.py` `resolve_revision()` (line 230) — simplify to just `return changespec_name` |
| **Remove** branch rename logic                   | `src/sase/workspace_changespec.py` (lines 149-159, the `git branch -m` block)                               |
| **Remove** `generate_branch_name` import + usage | `xprompts/gh.yml` (line 21, lines 49-53)                                                                    |
| **Remove** `generate_branch_name` import + usage | `xprompts/git.yml` (line 22, lines 56-60)                                                                   |

### 1d. Update tests

- **DELETE** `tests/test_branch_names.py`
- **UPDATE** `tests/test_gh_workspace.py`: rename `TestGetGitWorktreeDir` → `TestGetGitCloneDir`, rename
  `TestEnsureGitWorktree` → `TestEnsureGitClone`, update imports and mock targets

### Verification

```bash
just check                          # All lint + tests pass
grep -rn 'ensure_git_worktree' src/ xprompts/   # No hits
grep -rn 'branch_names' src/ xprompts/          # No hits
grep -rn 'changespec_name_to_branch' src/       # No hits
grep -rn 'generate_branch_name' src/ xprompts/  # No hits
```

---

## Phase 2: Direct Master Commits + Auto-Push

**Goal**: Simplify xprompts to stay on master (no branch creation). Update the commit workflow to commit directly to
master and auto-push. Remove ChangeSpec creation from default git workflow.

### 2a. Simplify `xprompts/gh.yml`

**Setup step** — remove branch logic:

- Remove `from sase.branch_names import generate_branch_name` (already gone from Phase 1)
- Remove `should_create_branch`, `branch_name` variables and output
- Remove `meta_changespec` output (no ChangeSpec by default)
- Remove `checkout_target` output
- Pass `None` for cl_name in `claim_workspace()` call

**Prepare step** — replace branch checkout with master sync:

```bash
# Save diff backup if workspace is dirty
if ! git diff --quiet HEAD 2>/dev/null; then
  git diff HEAD > "/tmp/gh-workspace-backup-$(date +%s).patch"
fi
git checkout . && git clean -fd
git fetch --quiet
git pull --rebase origin master --quiet 2>&1 || true
echo "success=true"
```

**Remove** the `create_changespec` step entirely.

**Release step** — simplify: remove branch_name references from `release_workspace()` call.

### 2b. Simplify `xprompts/git.yml`

Same changes as `gh.yml` above (parallel structure).

### 2c. Simplify `_git.py` `commit()` method

**`src/sase/vcs_provider/_git.py`** (lines 147-156):

- Remove branch creation logic (`git checkout -b`). Just commit on the current branch:

```python
def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
    out = self._run(["git", "commit", "-F", logfile], cwd)
    return self._to_result(out, "git commit")
```

### 2d. Update `sase_commit_workflow` for git support

**`src/sase/scripts/sase_commit_workflow`**:

Add VCS detection at the top of `_amend_cl()`:

- Detect git vs hg using `detect_vcs()` from `sase.vcs_provider`
- **Git path** (new):
  - Skip `_get_cl_name_from_branch()` (no branch to derive from)
  - `git add -A && git commit -m "<summary>"`
  - Auto-push: `git push origin master` with rebase-retry (up to 3 attempts)
  - If push rejected (remote advanced): `git pull --rebase origin master`, retry push
  - No ChangeSpec interaction (no HISTORY entry)
  - Still save diff for audit trail
  - Return `cl_name=""` and `entry_id=<short_sha>`
- **Hg path** (existing): keep `bb_hg_amend` logic unchanged

### 2e. Update `xprompts/commit.yml`

Add a `detect_branch` hidden step after `check_changes` to determine if on master or a PR branch:

```python
import subprocess
result = subprocess.run(
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    capture_output=True, text=True, check=False
)
branch = result.stdout.strip() if result.returncode == 0 else "master"
is_pr_branch = branch not in ("master", "main", "HEAD")
```

Route the `amend` step conditionally:

- **On master**: call `sase_commit_workflow` with a `--master` flag (git add, commit, push)
- **On PR branch**: call `sase_commit_workflow` normally (amend path, for future PR workflow)
- The `update_pr` step only runs on PR branches

### Verification

```bash
just check
# Manual: Run `#gh:sase <prompt>` — agent should work on master, no branch created
# Manual: Stop hook fires, /commit commits to master and pushes
# Manual: Verify `git log` shows commit on master, `git branch` shows only master
```

---

## Phase 3: Redesign `#pr` Workflow

**Goal**: When `#pr:<name>` is embedded in a prompt alongside `#gh:<ref>`, create a feature branch, ChangeSpec, and PR.
Axe scheduler hooks/CRS only apply to these PR-backed ChangeSpecs.

### 3a. Redesign `xprompts/pr.yml` as non-wrapping embedded workflow

The current `pr.yml` creates PRs for existing branches. Redesign it as a **non-wrapping** embedded workflow (no
`wraps_all`). This lets it be used alongside `#gh` (which IS `wraps_all`).

Usage: `#gh:sase #pr:my-feature Fix the login bug`

Execution order (wraps_all first, then non-wraps_all):

1. `#gh` pre-steps: setup workspace, prepare (fetch + pull on master)
2. `#pr` pre-step: `git checkout -b my-feature` from master, push to set upstream
3. Agent works on the `my-feature` branch
4. Stop hook → `/commit` → detects PR branch → commits + pushes to branch
5. `#pr` post-steps: create ChangeSpec + create PR
6. `#gh` post-step: release workspace

**New `pr.yml` structure**:

```yaml
input:
  - name: name
    type: word

steps:
  - name: create_branch
    bash: |
      git checkout -b "{{ name }}" --quiet
      git push -u origin "{{ name }}" --quiet 2>/dev/null || true
      echo "branch_name={{ name }}"
      echo "meta_changespec={{ name }}"
      echo "success=true"
    output: { branch_name: word, success: bool }

  - name: inject
    prompt_part: ""

  - name: create_changespec
    hidden: true
    python: |
      # Detect project from workspace (get_workspace_name)
      # Create ChangeSpec with NAME=<project>_<name>
      # Uses workspace_changespec.create_changespec_for_workflow()
    output: { changespec_name: word }

  - name: create_pr
    hidden: true
    if: "{{ create_changespec.changespec_name }}"
    bash: |
      # gh pr create --base master --head {{ name }}
    output: { pr_url: line, success: bool }
```

### 3b. Update `workspace_changespec.py`

- Remove the `git branch -m` rename at lines 149-159 (already done in Phase 1c)
- The `cl_name` parameter is now provided explicitly by `#pr` (e.g., `sase_my_feature`)
- `_get_commits_ahead()` compares `origin/master..branch_name` (works as-is)

### 3c. Simplify `git_submit.py`

- Remove `_submit_via_local_merge()` — no more branch-to-master merges
- `submit_git_changespec()` only handles PR-based submission:
  - Check for existing PR → `gh pr merge --merge --delete-branch`
  - If no PR exists → error "No PR to submit"
- Keep `_finalize_submission()` (rename ChangeSpec, transition to Submitted)

### 3d. Axe scheduler scoping

No code changes needed — the axe scheduler already only runs on ChangeSpecs. Since ChangeSpecs are now only created when
`#pr` is used, hooks/CRS will only trigger for PR-backed changes. The scheduler code in `starter.py` continues to work
as-is.

### Verification

```bash
just check
# Manual: Run `#gh:sase #pr:my-feature <prompt>` — should create branch, work, create ChangeSpec + PR
# Manual: Verify ChangeSpec exists in .gp file with correct NAME
# Manual: Verify PR exists on GitHub
# Manual: Run `#gh:sase <prompt>` WITHOUT #pr — verify NO ChangeSpec is created
```

---

## Phase 4: Cleanup + Dead Code Removal

**Goal**: Remove remaining dead code, update tests, clean up documentation.

### 4a. Dead code removal

| File                                   | Action                                                                                                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/workspace_changespec.py`     | Remove pyvision pragmas for `xprompts/git.yml` and `xprompts/gh.yml` if `create_changespec_for_workflow` is no longer called from those (now only from `pr.yml`) |
| `src/sase/git_submit.py`               | Remove `_submit_via_local_merge()` function (if not done in Phase 3)                                                                                             |
| `src/sase/gh_workspace.py`             | Remove `_ResolvedGhRef.branch_name` field if it's no longer used, or rename to `changespec_name` for clarity                                                     |
| `xprompts/gh.yml` / `xprompts/git.yml` | Verify no stale references to removed variables                                                                                                                  |

### 4b. Update tests

- Update `tests/test_gh_workspace.py` for clone-based behavior (from Phase 1d)
- Remove or update any tests that reference branch names, worktrees, or ChangeSpec creation from `#gh`/`#git`
- Add tests for auto-push retry logic in `sase_commit_workflow`
- Add tests for the new `#pr` workflow

### 4c. Documentation

- Update `plans/git_change_specs_v2.md` header to note it's superseded by v3
- Update any docstrings that reference "worktree" or "branch name generation"

### Verification

```bash
just check
just pyvision    # No unused public symbols
grep -rn 'worktree' src/ xprompts/ --include='*.py' --include='*.yml'  # Only in comments/docs if any
grep -rn 'branch_names\|generate_branch_name\|changespec_name_to_branch' src/ xprompts/  # No hits
```

---

## Key Files Summary

| File                                                 | Phases | Role                                                            |
| ---------------------------------------------------- | ------ | --------------------------------------------------------------- |
| `src/sase/gh_workspace.py`                           | 1      | Core: `ensure_git_clone()` replaces `ensure_git_worktree()`     |
| `src/sase/branch_names.py`                           | 1      | DELETE entirely                                                 |
| `src/sase/sase_utils.py`                             | 1      | Remove `changespec_name_to_branch()`                            |
| `src/sase/running_field.py`                          | 1      | Update `get_workspace_directory()` caller                       |
| `src/sase/ace/tui/actions/_agent_workflow_launch.py` | 1      | Update `ensure_git_worktree` → `ensure_git_clone`               |
| `src/sase/ace/scheduler/workflows_runner/starter.py` | 1      | Update `ensure_git_worktree` → `ensure_git_clone`               |
| `src/sase/vcs_provider/_git.py`                      | 1, 2   | Simplify `resolve_revision()` and `commit()`                    |
| `xprompts/gh.yml`                                    | 1, 2   | Remove branch logic, simplify prepare, remove create_changespec |
| `xprompts/git.yml`                                   | 1, 2   | Same as gh.yml                                                  |
| `xprompts/commit.yml`                                | 2      | Add branch detection, route master vs PR                        |
| `src/sase/scripts/sase_commit_workflow`              | 2      | Add git support with auto-push                                  |
| `xprompts/pr.yml`                                    | 3      | Redesign as non-wrapping embedded workflow                      |
| `src/sase/workspace_changespec.py`                   | 1, 3   | Remove branch rename; used by #pr only                          |
| `src/sase/git_submit.py`                             | 3      | Simplify to PR-only submission                                  |
| `tests/test_branch_names.py`                         | 1      | DELETE entirely                                                 |
| `tests/test_gh_workspace.py`                         | 1, 4   | Rename/update for clone model                                   |

## Reusable Existing Code

- `_clone_gh_repo()` in `gh_workspace.py` (line 44) — existing clone function for GitHub repos, pattern to follow
- `get_default_branch()` in `gh_workspace.py` (line 20) — reuse for detecting master/main
- `detect_vcs()` in `vcs_provider/_registry.py` — detect git vs hg in commit workflow
- `get_workspace_name()` in `_git.py` (line 389) — detect project name from workspace (used by `#pr`)
- `get_project_file_path()` in `workflow_utils.py` — resolve project file from name
- `create_changespec_for_workflow()` in `workspace_changespec.py` — reused by `#pr` workflow
