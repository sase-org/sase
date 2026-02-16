---
bead_id: sase-rhv
---

# Plan: Create `#gh` GitHub Embedded Workflow

## Context

SASE has an existing `#hg` embedded workflow (at `~/xprompts/hg.yml` via chezmoi) that manages workspace lifecycle for
Mercurial projects: claim workspace, clean, checkout CL, release. The `#mentor`, `#crs`, and `#fix_hook` xprompts use
`#hg:{{ cl_name }}` for workspace management.

We need an analogous `#gh` workflow for GitHub repositories that uses Git Worktrees for workspace copies. This enables
the same mentor/CRS/fix-hook agent workflows to operate on GitHub repos.

**Key design decisions** (confirmed with user):

- Store primary workspace directory in ProjectSpec `.gp` files as a `WORKSPACE_DIR` field
- `#gh` input: `user/project` (e.g., `bbugyi200/sase`) or shorthand `project_name` or `branch_name` (ChangeSpec)
- Xprompts get a `vcs_type` parameter (default `"hg"`) → `#{{ vcs_type }}:{{ cl_name }}`
- Git operations inline in YAML (no external scripts)
- Worktree paths: `~/projects/github/<user>/<project>__<N>/`

---

## Phase 1: Infrastructure — WORKSPACE_DIR Field + Git Workspace Module

### New file: `src/sase/gh_workspace.py`

Core Python module that `gh.yml` workflow steps will import.

**Functions:**

```python
@dataclass
class ResolvedGhRef:
    project_file: str      # Path to .gp file
    project_name: str      # Project basename
    primary_workspace_dir: str  # e.g., ~/projects/github/bbugyi200/sase/
    branch_name: str | None    # Branch to checkout (None for repo/project shorthand)
    checkout_target: str       # What to pass to git checkout --detach

def resolve_gh_ref(gh_ref: str) -> ResolvedGhRef
```

Resolution logic:

1. If `gh_ref` contains `/` → repo path format (`user/project`):
   - Derive `primary_workspace_dir = ~/projects/github/<user>/<project>/`
   - Project name = `<project>` portion
   - Project file = `~/.sase/projects/<project>/<project>.gp`
   - Validate: if `.gp` exists with a different WORKSPACE_DIR → error (duplicate project name)
   - Write WORKSPACE_DIR to `.gp` file (create file/dir if needed)
   - `branch_name = None`, `checkout_target = <default branch>`
2. If no `/`, check if project `<gh_ref>` exists with WORKSPACE_DIR set → project shorthand:
   - Read WORKSPACE_DIR from `~/.sase/projects/<gh_ref>/<gh_ref>.gp`
   - `branch_name = None`, `checkout_target = <default branch>`
3. If no `/` and not a project name, search ChangeSpecs via `find_all_changespecs()`:
   - Find ChangeSpec with `name == gh_ref`
   - Read WORKSPACE_DIR from its project file
   - If no WORKSPACE_DIR → error (not a GitHub project)
   - `branch_name = gh_ref`, `checkout_target = origin/<gh_ref>`
4. Otherwise → error

```python
def parse_workspace_dir(project_file: str) -> str | None
```

Read `WORKSPACE_DIR: <path>` field from `.gp` file (before first `NAME:` field). Expand `~`.

```python
def set_workspace_dir(project_file: str, workspace_dir: str) -> bool
```

Write/update `WORKSPACE_DIR` field in `.gp` file. Uses `changespec_lock` + `write_changespec_atomic`. Inserts before
`RUNNING:` or first `NAME:` field. Creates `.gp` file/dir if needed.

```python
def get_git_worktree_dir(primary_workspace_dir: str, workspace_num: int) -> str
```

- `workspace_num == 1` → return `primary_workspace_dir`
- `workspace_num >= 2` → return `<primary_dir>__<N>/` (double underscore separator)

```python
def ensure_git_worktree(primary_workspace_dir: str, workspace_num: int) -> str
```

- If worktree path doesn't exist: run `git worktree prune` then `git worktree add --detach <path>` from primary dir
- Return worktree path. Raise RuntimeError on failure.

```python
def detect_vcs_type_for_project(project_file: str) -> str
```

If WORKSPACE_DIR is set, check `.git` dir in that path → return `"git"`. Otherwise `"hg"`.

### New file: `tests/test_gh_workspace.py`

Unit tests for all functions (mock subprocess/filesystem for worktree operations).

### Key files to reference

- `src/sase/running_field.py` — RUNNING field parsing pattern (reuse `get_first_available_axe_workspace`,
  `claim_workspace`, `release_workspace`)
- `src/sase/ace/changespec/__init__.py` — `find_all_changespecs()`, `changespec_lock`, `write_changespec_atomic`
- `src/sase/ace/changespec/parser.py` — Field parsing pattern for `.gp` files

### Verification

```bash
just test tests/test_gh_workspace.py
just lint
```

---

## Phase 2: Create `gh.yml` Workflow

### New file: `xprompts/gh.yml` (in sase repo)

```yaml
input:
  - name: gh_ref
    type: word

steps:
  - name: setup
    python: |
      from sase.gh_workspace import resolve_gh_ref, ensure_git_worktree
      from sase.running_field import (
          get_first_available_axe_workspace,
          claim_workspace,
      )
      import os

      gh_ref = {{ gh_ref | tojson }}
      resolved = resolve_gh_ref(gh_ref)

      workspace_num = get_first_available_axe_workspace(resolved.project_file)
      worktree_dir = ensure_git_worktree(resolved.primary_workspace_dir, workspace_num)

      pid = os.getppid()
      workflow_name = f"gh-{gh_ref}"
      claim_workspace(resolved.project_file, workspace_num, workflow_name, pid,
                       resolved.branch_name)

      print(f"project_name={resolved.project_name}")
      print(f"project_file={resolved.project_file}")
      print(f"workspace_dir={worktree_dir}")
      print(f"workspace_num={workspace_num}")
      print(f"checkout_target={resolved.checkout_target}")
      print(f"_chdir={worktree_dir}")
    output:
      project_name: word
      project_file: path
      workspace_dir: path
      workspace_num: int
      checkout_target: text

  - name: prepare
    bash: |
      # Save existing diff for safety
      diff_file="$HOME/tmp/sase_gh_clean/{{ gh_ref }}-$(date +%Y%m%d_%H%M%S).diff"
      mkdir -p "$(dirname "$diff_file")"
      git diff HEAD > "$diff_file" 2>/dev/null || true

      # Clean workspace
      git reset --hard HEAD 2>/dev/null || true
      git clean -fd

      # Fetch and checkout target in detached HEAD mode
      # (detached HEAD avoids git worktree branch conflicts)
      git fetch origin
      git checkout --detach "{{ setup.checkout_target }}" 2>/dev/null \
        || git checkout --detach "origin/{{ setup.checkout_target }}" 2>/dev/null \
        || true

      echo "success=true"
    output: { success: bool }

  - name: inject
    prompt_part: ""

  - name: release
    python: |
      from sase.running_field import release_workspace
      release_workspace(
          {{ setup.project_file | tojson }},
          {{ setup.workspace_num }},
          f"gh-{{ gh_ref }}",
      )
      print("released=true")
    output: { released: bool }
```

**Design notes:**

- **Detached HEAD**: Avoids git worktree's constraint against having the same branch checked out in multiple worktrees
- **Diff backup**: Saved to `~/tmp/sase_gh_clean/` (mirrors hg pattern at `~/tmp/sase_hg_clean/`)
- **checkout_target**: Computed by `resolve_gh_ref()` in setup step, passed to prepare step via output variable

### Verification

```bash
# Manual test: set up a GitHub project
sase run "#gh:bbugyi200/sase Hello"

# Verify workspace claiming works
bd ready  # or check RUNNING field in .gp file
```

---

## Phase 3: Update Xprompts + Python Runners for VCS Abstraction

### 3.1 Update xprompts — add `vcs_type` parameter

**`xprompts/mentor.md`**, **`xprompts/crs.md`**, **`xprompts/fix_hook.md`** — all get the same change:

```yaml
input:
  ...existing inputs...
  - name: vcs_type
    type: word
    default: "hg"
```

Body change: `#hg:{{ cl_name }}` → `#{{ vcs_type }}:{{ cl_name }}`

Default `"hg"` ensures backward compatibility for all existing callers.

### 3.2 Update Python runners — detect VCS type

**`src/sase/mentor_workflow.py`** (line 35-47):

```python
def _build_mentor_prompt(mentor: MentorConfig, cl_name: str, vcs_type: str = "hg") -> str:
    expanded = process_xprompt_references(mentor.prompt)
    return f"#{vcs_type}:{cl_name}\n\n{expanded}"
```

In `MentorWorkflow.run()`, after finding the project file (line 140):

```python
from sase.gh_workspace import detect_vcs_type_for_project
vcs_type = detect_vcs_type_for_project(project_file)
```

Pass `vcs_type` to `_build_mentor_prompt()`.

**`src/sase/crs_workflow.py`** (`_build_crs_prompt`, line 65-82):

Add `vcs_type` parameter, pass to xprompt reference:

```python
f'#crs(critique_comments_path="...", cl_name="...", vcs_type="{vcs_type}")'
```

Add `vcs_type` to `CrsWorkflow.__init__` and detect in `run()`.

**`src/sase/axe_fix_hook_runner.py`** (line 124-128):

Add `vcs_type` to the xprompt reference:

```python
f'#fix_hook(hook_command="...", output_file="...", cl_name="...", vcs_type="{vcs_type}")'
```

### 3.3 Update axe scheduler — VCS-aware workspace management

**`src/sase/ace/scheduler/workflows_runner/starter.py`**:

`_start_crs_workflow` (lines 116-256) currently does workspace management directly using hg-specific functions:

- `get_workspace_directory_for_num()` → calls `sase_get_workspace` (hg-specific)
- `run_sase_hg_clean()` → calls `sase_hg_clean` script (hg-specific)

For git projects, replace with VCS-aware alternatives:

- Workspace directory: For git projects, use `get_git_worktree_dir()` + `ensure_git_worktree()` from `gh_workspace.py`
- Clean: Use `provider.stash_and_clean()` from `vcs_provider` (already works for both git and hg)

Detection: `detect_vcs_type_for_project(changespec.file_path)` determines which path to take.

`start_fix_hook_workflow` (lines 259-362) does NOT do workspace management (the `#hg`/`#gh` embedded workflow handles
it), so it needs no workspace changes. But `axe_fix_hook_runner.py` needs the `vcs_type` CLI arg passed from the
starter.

### 3.4 Files modified summary

| File                                                 | Change                                                                      |
| ---------------------------------------------------- | --------------------------------------------------------------------------- |
| `xprompts/mentor.md`                                 | Add `vcs_type` input (default `"hg"`), use `#{{ vcs_type }}`                |
| `xprompts/crs.md`                                    | Same pattern                                                                |
| `xprompts/fix_hook.md`                               | Same pattern                                                                |
| `src/sase/mentor_workflow.py`                        | Detect VCS, pass `vcs_type` to prompt builder                               |
| `src/sase/crs_workflow.py`                           | Accept `vcs_type`, pass to xprompt reference                                |
| `src/sase/axe_fix_hook_runner.py`                    | Accept `vcs_type` CLI arg, pass to xprompt                                  |
| `src/sase/ace/scheduler/workflows_runner/starter.py` | VCS-aware workspace mgmt in CRS starter; pass `vcs_type` to fix-hook runner |

### Verification

```bash
just check  # Full check suite (fmt + lint + test)
```

Manual: Run `sase ace` on an hg project (should still use `#hg`), then on a git project (should use `#gh`).

---

## Edge Cases

- **Worktree creation race**: `ensure_git_worktree` should handle "already exists" from `git worktree add` gracefully
- **Branch conflicts**: Solved by always using `git checkout --detach` in worktrees
- **Missing primary workspace**: Error if `~/projects/github/<user>/<project>/` doesn't exist (user must clone first)
- **Duplicate project names**: Error if `#gh:alice/sase` is used when `~/.sase/projects/sase/sase.gp` already has a
  different WORKSPACE_DIR
- **Stale worktrees**: Run `git worktree prune` before creating new worktrees
