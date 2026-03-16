---
bead_id: sase-cvb
---

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

### Backward Compatibility

Existing ChangeSpecs have random branch names (e.g., `dull-basin`). After removing branch _creation_ code:

- Existing ChangeSpecs can still be viewed/submitted via `resolve_revision()` and `changespec_name_to_branch()` (both
  retained — see Phase 1c)
- Existing branches are not automatically deleted — they can be manually cleaned up or left to expire
- The `#pr` workflow (Phase 3) creates ChangeSpecs with explicit names, so no naming collision with old random branches

---

## Phase 1: Replace Worktrees with Clones + Remove Branch Names

**Goal**: Replace worktree infrastructure with clone infrastructure. Delete branch name _generation_ code (but keep
`changespec_name_to_branch()` and `resolve_revision()` since they're still needed for `#pr` ChangeSpecs in Phase 3).

### 1a. Replace `ensure_git_worktree` with `ensure_git_clone`

**`src/sase/gh_workspace.py`**:

- Rename `_get_git_worktree_dir()` → `_get_git_clone_dir()` (body unchanged, same `primary__N/` path pattern)
- Replace `ensure_git_worktree()` with `ensure_git_clone()`:
  - Workspace 1: verify primary dir exists (unchanged)
  - Workspace 2+: `git clone primary_dir clone_dir` (local clone, hard-linked objects)
  - After cloning: re-point `origin` to the real remote (not the primary workspace) using
    `git remote set-url origin <real_origin_url>`
  - To get the real remote URL: run `git remote get-url origin` in the primary workspace directory
  - If the clone dir already exists but is stale/corrupt (e.g., `git status` fails), delete and re-clone
  - After cloning, run `git fetch --quiet` to ensure refs are up-to-date with remote
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
| `src/sase/git_submit.py` (`_submit_via_local_merge()`, line ~97)                  | See note below about simplification now possible with clones                                            |

**`git_submit.py` note**: Commit c224376 fixed `_submit_via_local_merge()` to use `primary_ws_dir` because worktrees
can't check out master (it's already checked out in the primary). With clones, this workaround is unnecessary — each
clone is independent and can check out any branch. Simplify `_submit_via_local_merge()` to operate in the clone's own
`ws_dir` directly (remove the `primary_ws_dir` parameter). This simplification is safe because clones don't share branch
lock constraints with the primary workspace.

### 1c. Delete branch name generation (but keep `changespec_name_to_branch` and `resolve_revision`)

**Important**: `changespec_name_to_branch()` and `resolve_revision()` must be **retained**. They're still needed for
`#pr` ChangeSpecs (Phase 3), where ChangeSpec names use underscore/prefix conventions (e.g., `sase_my_feature__1`) while
branch names use hyphens (e.g., `my-feature`). The sase-g61 commits added `resolve_revision()` calls to ~15 call sites —
all would break for `#pr` ChangeSpecs if these functions were removed.

| Action                                           | File                                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **DELETE**                                       | `src/sase/branch_names.py` (entire module — this is the _generation_ code)                              |
| **DELETE**                                       | `tests/test_branch_names.py` (entire test file)                                                         |
| **KEEP** `changespec_name_to_branch()`           | `src/sase/sase_utils.py` (lines 90-100) — still needed for `#pr` ChangeSpecs                            |
| **KEEP** `resolve_revision()` as-is              | `src/sase/vcs_provider/_git.py` (lines 217-232) — still calls `changespec_name_to_branch()` as fallback |
| **Remove** branch rename logic                   | `src/sase/workspace_changespec.py` (lines 149-159, the `git branch -m` block)                           |
| **Remove** `generate_branch_name` import + usage | `xprompts/gh.yml` (line 21, lines 49-53)                                                                |
| **Remove** `generate_branch_name` import + usage | `xprompts/git.yml` (line 22, lines 56-60)                                                               |

### 1d. Update tests

- **DELETE** `tests/test_branch_names.py`
- **UPDATE** `tests/test_gh_workspace.py`: rename `TestGetGitWorktreeDir` → `TestGetGitCloneDir`, rename
  `TestEnsureGitWorktree` → `TestEnsureGitClone`, update imports and mock targets

### Verification

```bash
just check                          # All lint + tests pass
grep -rn 'ensure_git_worktree' src/ xprompts/   # No hits
grep -rn 'branch_names' src/ xprompts/          # No hits (module deleted)
grep -rn 'generate_branch_name' src/ xprompts/  # No hits
# These should still exist:
grep -rn 'changespec_name_to_branch' src/       # Should hit sase_utils.py and _git.py
grep -rn 'resolve_revision' src/                # Should hit _git.py and ~15 call sites
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
- Pass `None` for `cl_name` in `claim_workspace()` call (currently passes `resolved.branch_name`)

**`_ResolvedGhRef` field usage**: The `branch_name` field on `_ResolvedGhRef` (line 291 of `gh_workspace.py`) is no
longer relevant for the default (master) flow. For Mode 1 (repo path) and Mode 2 (project shorthand), `branch_name` is
already `None`. For Mode 3 (ChangeSpec name), it's set but unused in the new model. The `checkout_target` field
similarly becomes just the default branch name. Leave the struct fields in place for now (Phase 4 will clean up).

**`n` and `release` inputs**: These carry forward unchanged. `n` controls workspace number selection, `release` controls
whether the workspace is pinned (`pinned=not should_release`). Both are independent of branching.

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

Same changes as `gh.yml` above (parallel structure). Same notes about `_ResolvedGhRef` fields (the git.yml equivalent
uses similar structs from `git_workspace.py`), `claim_workspace()` `cl_name=None`, and `n`/`release` carrying forward.

### 2c. Simplify `_git.py` `commit()` method

**`src/sase/vcs_provider/_git.py`** (lines 147-156):

- Remove branch creation logic (`git checkout -b`). Just commit on the current branch:

```python
def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
    out = self._run(["git", "commit", "-F", logfile], cwd)
    return self._to_result(out, "git commit")
```

### 2d. Update `sase_commit_workflow` for git support

**Current state**: `sase_commit_workflow` (at `src/sase/scripts/sase_commit_workflow`) is the **amend** helper, renamed
from `sase_amend_workflow` in v2 (sase-py2.2). Its `_amend_cl()` function (lines 38-154):

1. Calls `_get_cl_name_from_branch()` (line 44) which uses `provider.get_branch_name()` to find the current branch name
2. Looks up the ChangeSpec matching that branch name
3. Saves a diff for audit trail (line 85)
4. Calls `bb_hg_amend` (lines 121-129) — **Mercurial only**, no git support
5. Adds a HISTORY entry to the project file (lines 132-139)

**Problem on master**: `_get_cl_name_from_branch()` returns "master" when on master — no ChangeSpec matches, so the
amend flow fails. The plan must handle this.

**Also note**: `sase_cl_workflow` (renamed from `sase_commit_workflow` in v2) is the **CL creation** helper. It creates
new ChangeSpecs from uncommitted changes. In the new model, CL creation only happens via `#pr`, so `sase_cl_workflow` is
not called from the default `#gh`/`#git` flow. It may still be used by `#pr` in Phase 3 or can be deprecated in favor of
`create_changespec_for_workflow()` which `#pr` calls directly.

**Changes to `_amend_cl()`**:

Add VCS detection at the top:

- Detect git vs hg using `detect_vcs()` from `sase.vcs_provider`
- **Git path on master** (new — the common case):
  - Do NOT call `_get_cl_name_from_branch()` (there's no ChangeSpec on master)
  - `git add -A && git commit -m "<summary>"`
  - Auto-push: `git push origin master` with rebase-retry (up to 3 attempts):
    - If push rejected (remote advanced): `git pull --rebase origin master`, retry push
  - No ChangeSpec interaction (no HISTORY entry)
  - Still save diff for audit trail
  - Return `cl_name=""` and `entry_id=<short_sha>`
- **Git path on PR branch** (used when `#pr` is active):
  - `git add -A && git commit -m "<summary>"`
  - `git push origin <branch>` with rebase-retry
  - Amend the ChangeSpec HISTORY entry (look up ChangeSpec by branch name)
  - Return `cl_name=<changespec_name>` and `entry_id=<next_commit_number>`
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

Route the `amend` step based on branch:

- **On master**: call `sase_commit_workflow` which will take the git-on-master path (git add, commit, push with
  rebase-retry). No ChangeSpec interaction, no HISTORY entry.
- **On PR branch**: call `sase_commit_workflow` which will take the git-on-PR-branch path (git add, commit, push to
  branch, amend ChangeSpec HISTORY entry).
- The `update_pr` step only runs on PR branches (when `is_pr_branch` is true)

Note: no `--master` flag is needed on `sase_commit_workflow` — it can detect the branch itself via
`_get_cl_name_from_branch()`. On master, `_get_cl_name_from_branch()` returns "master" which doesn't match any
ChangeSpec, so the script knows to use the direct-commit path. On a PR branch, it finds the matching ChangeSpec and uses
the amend path.

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

1. `#gh` pre-steps: setup workspace (claim workspace on master, no branch), prepare (fetch + pull on master)
2. `#pr` pre-step: `create_branch` runs **in the workspace that `#gh` set up** — `git checkout -b my-feature` from
   master, push to set upstream
3. Agent works on the `my-feature` branch
4. Stop hook → `/commit` → detects PR branch → commits + pushes to branch, amends ChangeSpec HISTORY
5. `#pr` post-steps: create ChangeSpec + create PR
6. `#gh` post-step: release workspace

**`#gh` → `#pr` handoff**: `#pr`'s `create_branch` step runs in the working directory that `#gh`'s setup step
established (via `_chdir`). `#pr` does not need to know which workspace was claimed — it just operates on the current
directory. The outputs `#pr` produces (`branch_name`, `changespec_name`) are consumed by its own post-steps.

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
      from sase.vcs_provider._git import GitVCSProvider
      provider = GitVCSProvider()
      project_name = provider.get_workspace_name(os.getcwd())
      # ChangeSpec NAME = <project>_<name> (e.g., sase_my_feature)
      # Uses workspace_changespec.create_changespec_for_workflow()
      # workflow_name = f"pr-{name}"
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

### 3c. Update `git_submit.py`

**Important**: Do NOT remove `_submit_via_local_merge()` entirely. Bare git repos (via `#git`) don't have GitHub PRs. If
a `#git` + `#pr` ChangeSpec exists for a bare repo, it still needs local merge submission.

Changes:

- `submit_git_changespec()` first checks for an existing PR → `gh pr merge --merge --delete-branch`
- If no PR exists AND it's a GitHub repo → error "No PR to submit"
- If no PR exists AND it's a bare git repo → fall back to `_submit_via_local_merge()`
- Keep `_finalize_submission()` (rename ChangeSpec, transition to Submitted)
- Simplify `_submit_via_local_merge()` per Phase 1b note (remove `primary_ws_dir` parameter since clones can check out
  any branch directly)

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

| File                                   | Action                                                                                                                                                                                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/workspace_changespec.py`     | Remove pyvision pragmas for `xprompts/git.yml` and `xprompts/gh.yml` if `create_changespec_for_workflow` is no longer called from those (now only from `pr.yml`)                                                                             |
| `src/sase/gh_workspace.py`             | Remove or rename `_ResolvedGhRef.branch_name` field — unused in default flow, only relevant for Mode 3 (ChangeSpec resolution). Consider renaming to `changespec_name` for clarity since it's only set when resolving a ChangeSpec reference |
| `xprompts/gh.yml` / `xprompts/git.yml` | Verify no stale references to removed variables                                                                                                                                                                                              |

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
grep -rn 'branch_names\|generate_branch_name' src/ xprompts/  # No hits
# These should still exist (needed for #pr ChangeSpecs):
grep -rn 'changespec_name_to_branch' src/       # Should hit sase_utils.py and _git.py
grep -rn 'resolve_revision' src/                # Should hit _git.py and call sites
```

---

## Key Files Summary

| File                                                 | Phases | Role                                                                                                                     |
| ---------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------ |
| `src/sase/gh_workspace.py`                           | 1, 4   | Core: `ensure_git_clone()` replaces `ensure_git_worktree()`; clean up `_ResolvedGhRef`                                   |
| `src/sase/branch_names.py`                           | 1      | DELETE entirely (generation code only)                                                                                   |
| `src/sase/sase_utils.py`                             | —      | KEEP `changespec_name_to_branch()` (needed for `#pr` ChangeSpecs)                                                        |
| `src/sase/running_field.py`                          | 1      | Update `get_workspace_directory()` caller                                                                                |
| `src/sase/ace/tui/actions/_agent_workflow_launch.py` | 1      | Update `ensure_git_worktree` → `ensure_git_clone`                                                                        |
| `src/sase/ace/scheduler/workflows_runner/starter.py` | 1      | Update `ensure_git_worktree` → `ensure_git_clone`                                                                        |
| `src/sase/vcs_provider/_git.py`                      | 2      | Simplify `commit()` (keep `resolve_revision()` as-is)                                                                    |
| `xprompts/gh.yml`                                    | 1, 2   | Remove branch logic, simplify prepare, remove create_changespec                                                          |
| `xprompts/git.yml`                                   | 1, 2   | Same as gh.yml                                                                                                           |
| `xprompts/commit.yml`                                | 2      | Add branch detection, route master vs PR                                                                                 |
| `src/sase/scripts/sase_commit_workflow`              | 2      | Add git support: master path (direct commit+push) and PR branch path (amend)                                             |
| `src/sase/scripts/sase_cl_workflow`                  | 2      | Note: not called from default flow; may be deprecated in favor of `#pr`'s direct `create_changespec_for_workflow()` call |
| `xprompts/pr.yml`                                    | 3      | Redesign as non-wrapping embedded workflow                                                                               |
| `src/sase/workspace_changespec.py`                   | 1, 3   | Remove branch rename; used by #pr only                                                                                   |
| `src/sase/git_submit.py`                             | 1, 3   | Simplify `_submit_via_local_merge()` (remove `primary_ws_dir`); keep for bare git repos                                  |
| `tests/test_branch_names.py`                         | 1      | DELETE entirely                                                                                                          |
| `tests/test_gh_workspace.py`                         | 1, 4   | Rename/update for clone model                                                                                            |

## Reusable Existing Code

- `_clone_gh_repo()` in `gh_workspace.py` (line 44) — existing clone function for GitHub repos, pattern to follow
- `get_default_branch()` in `gh_workspace.py` (line 20) — reuse for detecting master/main
- `detect_vcs()` in `vcs_provider/_registry.py` — detect git vs hg in commit workflow
- `get_workspace_name()` in `_git.py` (line 389) — detect project name from workspace (used by `#pr`)
- `get_project_file_path()` in `workflow_utils.py` — resolve project file from name
- `create_changespec_for_workflow()` in `workspace_changespec.py` — reused by `#pr` workflow
- `changespec_name_to_branch()` in `sase_utils.py` (line 90) — retained for `#pr` ChangeSpec name→branch mapping
