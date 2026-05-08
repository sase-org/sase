---
create_time: 2026-05-08 19:04:51
status: done
prompt: sdd/prompts/202605/git_xprompt_auto_init.md
---
# Plan: Auto-Initialize Bare Git Projects From `#git:<project>`

## Goal

Make the built-in `git` VCS xprompt workflow work when launched with a project-style ref that has no existing SASE
project yet, for example:

```text
#git:new_project Build the first feature
```

Instead of failing with `Cannot resolve git_ref 'new_project'`, SASE should initialize a new bare-repo-backed git
project using the same semantics as `sase init-git new_project`, then continue the normal workspace claim, clone, and
checkout flow.

## Current Behavior

The `#git` workflow runs `src/sase/scripts/git_setup.py`, which calls `resolve_git_ref()` from
`src/sase/workspace_provider/plugins/bare_git_ref.py`.

`resolve_git_ref()` currently supports:

1. Existing project shorthand: `#git:sase` resolves `~/.sase/projects/sase/sase.gp` when it contains `BARE_REPO_DIR` and
   `WORKSPACE_DIR`.
2. Existing ChangeSpec name: `#git:feature_branch` searches all ChangeSpecs and resolves the project that owns that
   ChangeSpec.
3. Bare repo path: `#git:/path/to/repo.git` derives a project name and writes project metadata.

For a plain project name that is neither an existing project nor a ChangeSpec, the function raises `ValueError`.

There is already a reusable initializer in `src/sase/workspace_provider/plugins/bare_git_init.py`:
`init_bare_git_project(project_name, bare_dir=None, clone_dir=None, existing_bare=None)`. It creates
`~/.sase/repos/<name>.git`, clones it to `~/projects/git/<name>/`, creates an initial empty commit, pushes it, and
writes `BARE_REPO_DIR` plus `WORKSPACE_DIR` into `~/.sase/projects/<name>/<name>.gp`.

## Proposed Behavior

For `#git:<ref>` where `<ref>` has no slash:

1. Prefer an existing project when `~/.sase/projects/<ref>/<ref>.gp` exists and has `BARE_REPO_DIR`.
2. Prefer an existing ChangeSpec if no project shorthand matched.
3. If neither exists, treat `<ref>` as a new bare git project name and initialize it automatically.
4. Resolve the newly-created project using the same returned shape as an existing project: `project_file`,
   `project_name`, `primary_workspace_dir`, `bare_repo_dir`, and `checkout_target`.

This keeps ChangeSpec names from being accidentally shadowed by auto-created projects while enabling the intended
new-project workflow.

## Implementation

Update `src/sase/workspace_provider/plugins/bare_git_ref.py`.

Add a small helper, likely `_init_missing_project_ref(project_name: str) -> ResolvedGitRef`, that:

1. Imports `init_bare_git_project` lazily inside the helper to avoid a top-level circular import, because
   `bare_git_init.py` already imports `set_bare_repo_dir` from `bare_git_ref.py`.
2. Calls `init_bare_git_project(project_name)`.
3. Reads `BARE_REPO_DIR` and `WORKSPACE_DIR` back from the returned project file.
4. Raises a clear `ValueError` or `RuntimeError` if initialization appears to succeed but metadata is missing.
5. Computes `checkout_target` with `get_default_branch(workspace_dir)`.
6. Returns `ResolvedGitRef(...)`.

Then change the final no-slash failure branch from:

```python
raise ValueError(f"Cannot resolve git_ref '{git_ref}'")
```

to call that helper after the ChangeSpec search has failed.

I would also consider a narrow validation helper for project names before auto-init. The current `init-git` CLI accepts
any string argparse passes as `project_name`, but xprompt refs are restricted by the `#git` workflow regex to
`[a-zA-Z0-9_./-]+`. For no-slash refs, that effectively allows letters, digits, underscores, dots, and hyphens. I will
not broaden this surface. I will only reject empty strings and path-like names are already excluded by the no-slash
branch.

## Edge Cases

- Existing project dir exists but lacks `BARE_REPO_DIR`: preserve current behavior unless the project is truly missing.
  This avoids silently converting a non-bare-git project into a bare-git project.
- Existing ChangeSpec with the same name: preserve ChangeSpec resolution and do not auto-create a project.
- Initialization command failure: let the underlying `subprocess.CalledProcessError` or `RuntimeError` surface rather
  than hiding git failures.
- Race between two launches of the same new project: `init_bare_git_project()` currently uses
  `os.makedirs(..., exist_ok=True)` but `git clone` can still race if both create the same clone. I will not design a
  broad locking system in this change unless tests reveal a current helper is unsafe; the minimum acceptable behavior is
  no regression from manual `sase init-git`.
- Bare repo path refs containing `/`: leave unchanged in this pass because the user asked about project-name refs.

## Tests

Update `tests/test_bare_git_workspace.py`.

Add unit coverage for `resolve_git_ref()`:

1. `test_missing_project_name_auto_initializes`:
   - Patch `Path.home` to a temp home.
   - Patch `find_all_changespecs` to return `[]`.
   - Patch `init_bare_git_project` through its lazy import target or use real temp-backed initialization with mocked git
     subprocess calls.
   - Ensure `resolve_git_ref("newproj")` returns `project_name == "newproj"` and the expected project
     file/workspace/bare metadata.

2. `test_missing_project_does_not_shadow_changespec`:
   - Existing ChangeSpec named `newproj` resolves as before.
   - Assert the initializer is not called.

3. If practical, add one focused end-to-end-ish test using mocked `subprocess.run` for `init_bare_git_project()` to
   verify the expected default paths are used when auto-init is triggered.

Existing tests to keep green:

```bash
pytest tests/test_bare_git_workspace.py
```

## Verification

After implementation, run:

```bash
just install
pytest tests/test_bare_git_workspace.py
just check
```

The repo memory says `just install` must precede repo checks in ephemeral workspaces, and `just check` should be run
before finishing after code changes.
