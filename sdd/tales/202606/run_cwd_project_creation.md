---
create_time: 2026-06-15 09:53:29
status: done
prompt: sdd/prompts/202606/run_cwd_project_creation.md
---
# Fix `sase run` CWD Project Creation

## Diagnosis

`sase run` can create `~/.sase/projects/<cwd-derived-project>/` because both launch paths call
`ensure_project_file_and_get_workspace_num()` before prompt-level workspace context has fully taken over.

That helper currently:

1. Calls `workspace_provider.get_workspace_name(os.getcwd())`.
2. Accepts names inferred from the current git repo, including the built-in bare-git fallback from remote URL or git
   root basename.
3. Constructs `~/.sase/projects/<project>/<project>.sase`.
4. Creates the project file if it does not already exist.

For background agent launches, `launch_agents_from_cwd()` does this before it resolves explicit/default prompt refs like
`#git:home`, `#gh:sase`, or `#cd:/path`. For foreground runs, `run_query()` has the same eager call after defaulting
bare prompts to `#git:home`. This means a plain `sase run` from any git checkout whose basename is a valid SASE project
name can silently register that checkout as a SASE project, even when the actual launch should use `home` or an explicit
prompt ref.

There is a second visible symptom: once a wrong project name is carried into the launch context, artifact creation can
also materialize `~/.sase/projects/<project>/artifacts/...`, even if a ProjectSpec file was not needed.

## Goal

Make `sase run` launch context resolution non-creating by default. Existing, known SASE projects should still work, and
explicit project/workspace refs should still activate or resolve their real project. Bare prompts should fall back to
the existing `home` behavior instead of registering the CWD.

## Plan

1. Split project-context lookup from project creation.
   - Keep the existing `ensure_project_file_and_get_workspace_num()` behavior for callers that truly want to bootstrap a
     missing project file.
   - Add a read-only resolver, or add a keyword such as `create_missing: bool = True`, so launch paths can ask for the
     CWD project only when the corresponding ProjectSpec already exists.
   - Preserve invalid-name protection so names like `.sase` still resolve to `(None, None, None)`.

2. Update `sase run` launch paths to use read-only project context.
   - In `launch_agents_from_cwd()`, avoid creating a ProjectSpec from CWD at function entry.
   - Let explicit prompt refs (`#gh`, `#git`, `#cd`, known-project refs) override the base context as they already do.
   - When no existing project context or explicit workspace ref exists, keep the current home-mode fallback.
   - In foreground `run_query()`, avoid creating a CWD ProjectSpec for the claim/artifact context. If the prompt
     resolves to `home` or another known ref, use that; otherwise skip workspace claiming rather than bootstrapping CWD
     state.

3. Add regression coverage.
   - Add tests around `ensure_project_file_and_get_workspace_num(create_missing=False)` or the new read-only helper:
     valid inferred project with no existing ProjectSpec returns no project and creates nothing.
   - Add daemon launch regression: from an inferred git project with no existing ProjectSpec, a bare prompt falls back
     to `home` and does not create `~/.sase/projects/<cwd-project>/`.
   - Add explicit-ref regression: from the same CWD, `#gh:sase` or known-project refs still launch under the referenced
     project and do not create the inferred CWD project.
   - Add foreground regression for `run_query("hello")` so artifact/project creation targets `home` or skips claim
     without creating the CWD project.

4. Verify with focused tests first, then the repo check.
   - Run the targeted launch/project tests added or touched.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Risk and Compatibility

The main risk is changing legacy behavior for users who relied on `sase run` to implicitly create a ProjectSpec for the
current git checkout. That implicit side effect is the bug here, so project creation should remain available through
explicit project initialization paths and explicit VCS refs, not a plain launch. Keeping the original helper behavior as
the default limits blast radius for other call sites while making `sase run` opt into read-only resolution.
