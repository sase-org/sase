---
bead_id: sase-3ec
---

# Plan: Add `#git` Workflow for Bare Git Repositories

## Context

The project currently supports two VCS workflows: `#gh` (GitHub-hosted git repos) and `#hg` (Mercurial). The user wants
a `#git` workflow for bare git repositories — local git repos initialized on the machine that act as a "local remote"
for clones elsewhere on the filesystem. This enables a GitHub-like push/pull workflow without requiring a remote hosting
service.

**Directory conventions** (per user):

- Bare repos: `~/.sase/repos/<name>.git`
- Primary clones: `~/projects/git/<name>/`
- Project files: `~/.sase/projects/<name>/<name>.gp` (existing convention)

---

## Phase 1: Core Infrastructure

**Goal**: Create `git_workspace.py` module, add workflow-type detection, update `_GitProvider` for bare repos.

### 1a. New module: `src/sase/git_workspace.py`

Parallel to `gh_workspace.py`. Key contents:

- **`ResolvedGitRef`** dataclass: `project_file`, `project_name`, `primary_workspace_dir`, `bare_repo_dir`,
  `branch_name`, `checkout_target`

- **`resolve_git_ref(git_ref: str) -> ResolvedGitRef`**: Three dispatch modes:
  1. **Project shorthand**: `git_ref` matches a dir under `~/.sase/projects/<name>/` with a `.gp` file having
     `BARE_REPO_DIR` — resolve WORKSPACE_DIR and BARE_REPO_DIR
  2. **ChangeSpec name**: Search all changespecs for matching name, verify its project has `BARE_REPO_DIR`
  3. **Bare repo path** (contains `/`): Derive project name from the path, auto-create project file if needed

- **`parse_bare_repo_dir(project_file: str) -> str | None`**: Read `BARE_REPO_DIR` field from `.gp` file (follows
  `parse_workspace_dir()` pattern from `gh_workspace.py:44`)

- **`_set_bare_repo_dir(project_file: str, bare_repo_dir: str) -> bool`**: Write `BARE_REPO_DIR` to `.gp` file (follows
  `_set_workspace_dir()` pattern from `gh_workspace.py:73`)

- **`init_bare_git_project(project_name, bare_dir=None, clone_dir=None, existing_bare=None)`**:
  - If `existing_bare` is provided: validate it's a bare repo, clone it
  - Otherwise: `git init --bare <bare_dir>` (default `~/.sase/repos/<name>.git`), clone to `<clone_dir>` (default
    `~/projects/git/<name>/`), create initial commit + push
  - Create `.gp` project file with `BARE_REPO_DIR` and `WORKSPACE_DIR`

- Reuse `ensure_git_worktree()` from `gh_workspace.py:144` for multi-workspace support (worktrees work the same
  regardless of remote type)

### 1b. Add `detect_workflow_type_for_project()` to `src/sase/gh_workspace.py`

Keep existing `detect_vcs_type_for_project()` returning `"git"` / `"hg"` unchanged (for callers that only care about VCS
tool). Add a NEW function:

```python
def detect_workflow_type_for_project(project_file: str) -> str:
    """Return 'gh', 'git', or 'hg' based on project configuration."""
```

Logic:

1. If no `.git` dir in WORKSPACE_DIR → `"hg"`
2. If `.gp` file has `BARE_REPO_DIR` → `"git"`
3. Check `origin` remote URL: local path → `"git"`, otherwise → `"gh"`

### 1c. Update `_GitProvider` in `src/sase/vcs_provider/_git.py`

Add `_is_bare_remote(cwd)` helper: checks if `origin` URL is a local filesystem path.

Update these methods to skip `gh` CLI calls when remote is bare:

- `mail()` (line 259): push without PR creation
- `get_change_url()` (line 234): return `(True, None)`
- `get_cl_number()` (line 242): return `(True, None)`

### 1d. Tests

- New file: `tests/test_git_workspace.py` — test `resolve_git_ref()` (all 3 modes), `parse_bare_repo_dir()`,
  `_set_bare_repo_dir()`, `init_bare_git_project()`
- Update `tests/test_gh_workspace.py` — test `detect_workflow_type_for_project()`
- Update git provider tests — test `_is_bare_remote()`, bare-aware `mail()`

### Verification

- `just check` passes
- `detect_workflow_type_for_project()` correctly returns `"git"` for bare-repo projects, `"gh"` for GitHub projects,
  `"hg"` for mercurial

### Files

| File                                  | Action                                          |
| ------------------------------------- | ----------------------------------------------- |
| `src/sase/git_workspace.py`           | **Create**                                      |
| `src/sase/gh_workspace.py`            | Modify (add `detect_workflow_type_for_project`) |
| `src/sase/vcs_provider/_git.py`       | Modify (add bare-remote awareness)              |
| `tests/test_git_workspace.py`         | **Create**                                      |
| `tests/test_gh_workspace.py`          | Modify                                          |
| `tests/test_vcs_provider_git_core.py` | Modify                                          |

---

## Phase 2: Workflow YAML + TUI Integration

**Goal**: Create `git.yml` workflow and wire `#git` references into the TUI.

### 2a. Create `xprompts/git.yml`

Modeled on `gh.yml` (same structure: setup/prepare/inject/release), but:

- Input: `git_ref` (word type)
- Setup step: uses `git_workspace.resolve_git_ref()` instead of `gh_workspace.resolve_gh_ref()`
- Env vars: `SASE_GIT_PRE_ALLOCATED`, `SASE_GIT_WORKSPACE_NUM`, `SASE_GIT_WORKSPACE_DIR`
- Release step: uses `"git-{git_ref}"` workflow name
- Prepare step: identical to `gh.yml` (git checkout + clean + fetch)

### 2b. Update `_entry_points.py` — VCS prompt prefix

File: `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`

Change `_vcs_prompt_prefix()` (line 15) to use `detect_workflow_type_for_project()`:

```python
def _vcs_prompt_prefix(project_file: str, name: str) -> str:
    from sase.gh_workspace import detect_workflow_type_for_project
    workflow_type = detect_workflow_type_for_project(project_file)
    return f"#{workflow_type}:{name} "
```

### 2c. Update `_agent_workflow_launch.py` — reference detection

File: `src/sase/ace/tui/actions/_agent_workflow_launch.py`

- Add `_GIT_REF_PATTERN` regex (parallel to `_GH_REF_PATTERN` at line 16)
- Add `_resolve_git_from_prompt()` method (parallel to `_resolve_gh_from_prompt()` at line 32)
- Update `_finish_agent_launch()` (line 68) to check for `#git` in home mode (after `#gh` check)
- Update `_launch_background_agent()` (line 225) to pass `SASE_GIT_PRE_ALLOCATED` env vars (add `git_ref` parameter
  parallel to `gh_ref`)

### 2d. Update workflow runner callers

These files all do `vcs_type = "gh" if raw_vcs == "git" else "hg"` — update to use `detect_workflow_type_for_project()`:

- `src/sase/axe_crs_runner.py:70-73`
- `src/sase/axe_fix_hook_runner.py:111-114`
- `src/sase/mentor_workflow.py:152-155`
- `src/sase/ace/scheduler/workflows_runner/starter.py:136-151` (this one also branches on `raw_vcs == "git"` for
  worktree logic — bare git also uses worktrees, so change to `raw_vcs in ("git-gh", "git-bare")` or keep using
  `detect_vcs_type_for_project()` for that check)

### Verification

- `just check` passes
- In TUI, typing `#git:myproject <prompt>` in home mode resolves correctly
- `_vcs_prompt_prefix()` returns `#git:name` for bare-repo projects
- Existing `#gh` and `#hg` workflows unaffected

### Files

| File                                                       | Action     |
| ---------------------------------------------------------- | ---------- |
| `xprompts/git.yml`                                         | **Create** |
| `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` | Modify     |
| `src/sase/ace/tui/actions/_agent_workflow_launch.py`       | Modify     |
| `src/sase/axe_crs_runner.py`                               | Modify     |
| `src/sase/axe_fix_hook_runner.py`                          | Modify     |
| `src/sase/mentor_workflow.py`                              | Modify     |
| `src/sase/ace/scheduler/workflows_runner/starter.py`       | Modify     |

---

## Phase 3: CLI Init Command + End-to-End

**Goal**: Add `sase init-git` CLI command and validate the full workflow end-to-end.

### 3a. Add `sase init-git` subcommand

File: `src/sase/main/parser.py` — add subparser:

```
sase init-git <project_name> [--bare-dir DIR] [--clone-dir DIR] [--existing BARE_PATH]
```

- `project_name`: required positional arg
- `--bare-dir`: override bare repo location (default: `~/.sase/repos/<name>.git`)
- `--clone-dir`: override clone location (default: `~/projects/git/<name>/`)
- `--existing`: path to existing bare repo to register (instead of creating new)

File: `src/sase/main/entry.py` — add handler (insert alphabetically before `amend`):

```python
if args.command == "init-git":
    from sase.git_workspace import init_bare_git_project
    init_bare_git_project(
        project_name=args.project_name,
        bare_dir=args.bare_dir,
        clone_dir=args.clone_dir,
        existing_bare=args.existing,
    )
    sys.exit(0)
```

### 3b. End-to-end integration tests

New file: `tests/test_cli_init_git.py`

- Test `sase init-git myproject` creates correct directory structure
- Test `sase init-git myproject --existing /path/to/existing.git` registers correctly
- Test `sase init-git myproject` when project already exists raises error
- Test full cycle: init → create branch → make changes → push to bare repo

### Verification

- `just check` passes
- Manual test:
  ```bash
  sase init-git testproject
  # Verify: ~/.sase/repos/testproject.git exists (bare repo)
  # Verify: ~/projects/git/testproject/ exists (clone)
  # Verify: ~/.sase/projects/testproject/testproject.gp has BARE_REPO_DIR + WORKSPACE_DIR
  cd ~/projects/git/testproject/
  echo "test" > test.txt && git add . && git commit -m "test"
  git push origin main  # pushes to bare repo
  ```

### Files

| File                         | Action     |
| ---------------------------- | ---------- |
| `src/sase/main/parser.py`    | Modify     |
| `src/sase/main/entry.py`     | Modify     |
| `tests/test_cli_init_git.py` | **Create** |

---

## Key Reuse Points

| Existing Code                                   | Reused In                           | Why                                             |
| ----------------------------------------------- | ----------------------------------- | ----------------------------------------------- |
| `ensure_git_worktree()` (`gh_workspace.py:144`) | `git_workspace.py`, `git.yml`       | Worktrees work identically for bare-repo clones |
| `parse_workspace_dir()` (`gh_workspace.py:44`)  | Pattern for `parse_bare_repo_dir()` | Same .gp field parsing pattern                  |
| `_set_workspace_dir()` (`gh_workspace.py:73`)   | Pattern for `_set_bare_repo_dir()`  | Same .gp field writing pattern                  |
| `running_field` functions                       | `git.yml` workflow                  | Same workspace claiming/releasing               |
| `gh.yml` workflow structure                     | `git.yml`                           | Same 4-step pattern                             |
| `_GH_REF_PATTERN` / `_resolve_gh_from_prompt()` | Pattern for `#git` equivalents      | Same regex + resolution pattern                 |
