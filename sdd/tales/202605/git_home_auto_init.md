---
create_time: 2026-05-12 14:29:52
status: done
prompt: sdd/prompts/202605/git_home_auto_init.md
---
# Plan: Auto-Initialize `#git:home` Bare Git Metadata

## Goal

Make the built-in `#git` VCS xprompt workflow initialize a missing bare-git project when the ref is `home`, matching the
existing auto-init behavior for other missing project refs.

The failure in the snapshot is:

```text
#git:home ...
ValueError: Default bare-git project 'home' is not ready: BARE_REPO_DIR is not set
```

That means SASE found `~/.sase/projects/home/home.sase`, but the project metadata does not include `BARE_REPO_DIR`.
Today that path is a deliberate special case that blocks auto-initialization for `home`.

## Current Behavior

The `#git` xprompt runs `src/sase/scripts/git_setup.py`, which calls
`sase.workspace_provider.plugins.bare_git_ref.resolve_git_ref()`.

`resolve_git_ref()` already has a helper, `_init_missing_project_ref()`, that initializes a new bare-git project through
`init_bare_git_project(project_name)`. It is used for ordinary missing project names after ChangeSpec lookup fails.

`home` is treated differently:

- If `~/.sase/projects/home/home.sase` exists without `BARE_REPO_DIR`, `resolve_git_ref("home")` raises a setup error.
- If the `home` project file does not exist, it also raises a setup error.
- Docs currently state that `#git:home` is not auto-created and should be configured explicitly with
  `sase init-git home --existing ...`.
- `tests/test_cd_spawn_env.py::test_default_git_home_reports_incomplete_home_project` asserts this error.

That policy no longer matches the desired xprompt workflow behavior.

## Proposed Behavior

For no-slash `#git:<ref>` resolution:

1. If an existing project file has both `BARE_REPO_DIR` and `WORKSPACE_DIR`, resolve it as before.
2. If an existing project file has `BARE_REPO_DIR` but no `WORKSPACE_DIR`, keep treating it as incomplete and fail. That
   is a partially configured bare-git project and auto-creating a new repo would not repair the intended clone.
3. If no existing project resolution succeeds, search ChangeSpecs as before so branch/ChangeSpec refs are not shadowed.
4. If no ChangeSpec matches, initialize the project with `_init_missing_project_ref(ref)`.
5. Apply that same final auto-init path to `home`, including the case where the project file exists but lacks
   `BARE_REPO_DIR`.

This fixes the snapshot because an incomplete `home.sase` without `BARE_REPO_DIR` becomes a bootstrap case rather than a
terminal setup error. The initializer will create:

- `~/.sase/repos/home.git`
- `~/projects/git/home/`
- `~/.sase/projects/home/home.sase` with `BARE_REPO_DIR` and `WORKSPACE_DIR`

## Scope

Make a narrow resolver-level change. Do not change the `#git` workflow YAML, workspace claim code, checkout logic, or
the `sase init-git` CLI.

The workflow already calls the resolver before claiming workspaces, so once `resolve_git_ref("home")` returns a complete
`ResolvedGitRef`, the existing setup, clone, checkout, release, and diff steps should work unchanged.

## Implementation Steps

1. Update `src/sase/workspace_provider/plugins/bare_git_ref.py`.
   - Remove or bypass the special `home` setup error for missing `BARE_REPO_DIR` and missing project file.
   - Keep a clear error for existing projects that have `BARE_REPO_DIR` but lack `WORKSPACE_DIR`.
   - Let the final no-slash unresolved branch call `_init_missing_project_ref(git_ref)` for `home` as well as ordinary
     refs.

2. Revisit `_home_project_setup_error`.
   - If it is still useful for the `BARE_REPO_DIR`-present but `WORKSPACE_DIR`-missing case, simplify the message so it
     no longer says SASE cannot auto-create `home` in general.
   - If no longer needed, remove it and use the generic incomplete-project error.

3. Update tests.
   - Replace `test_default_git_home_reports_incomplete_home_project` with coverage that `resolve_git_ref("home")`
     auto-initializes when `home.sase` exists without `BARE_REPO_DIR`.
   - Add or adjust coverage in `tests/test_bare_git_workspace.py` for `home` specifically, using the same mocked
     initializer pattern as `test_missing_project_name_auto_initializes`.
   - Keep coverage for the intentionally incomplete case where `BARE_REPO_DIR` is present but `WORKSPACE_DIR` is absent.

4. Update docs.
   - `docs/workspace.md` and `docs/xprompt.md` currently say `#git:home` is not auto-created. Change that to describe
     the new default bootstrap behavior.
   - Keep guidance that users who want `#git:home` to point at an existing dotfiles/home bare repo should still run
     `sase init-git home --existing <bare-repo> --clone-dir <checkout-dir>` before relying on the default.
   - Keep `#cd:~` documented as the explicit no-VCS/direct-home opt-out.

## Risks

- If a user had a placeholder `home.sase` and expected SASE to force manual configuration, SASE will now create an empty
  managed bare repo at the default `home` paths. This is the behavior requested for the xprompt bootstrap path, but docs
  should make the existing-repo setup path explicit.
- If a project has `BARE_REPO_DIR` but no `WORKSPACE_DIR`, auto-initializing a separate default repo would likely hide a
  broken config. Keep this as an error.
- Two concurrent first launches of `#git:home` can race in the underlying initializer. That race already exists for
  other auto-created project names; solving it requires a broader init lock and should stay out of this focused fix
  unless tests reveal a regression.

## Verification

Run targeted tests first:

```bash
pytest tests/test_bare_git_workspace.py tests/test_cd_spawn_env.py
```

Then follow repo instructions for changed code:

```bash
just install
just check
```
