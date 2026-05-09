---
create_time: 2026-05-09 13:30:24
status: done
prompt: sdd/prompts/202605/default_git_home_vcs.md
---
# Plan: Default Bare Prompts To `#git:home`

## Goal

Change SASE's implicit workspace workflow for prompts that do not specify a VCS/workspace xprompt from `#cd:~` to
`#git:home`, so ordinary bare prompts run inside a managed bare-git workspace by default and get version-control
behavior without user-visible prompt ceremony.

Explicit workspace refs must keep their current behavior:

- `#cd:~`, `#cd:/path`, and `#cd(...)` still run directly in that directory with no VCS workspace management.
- `#git:<ref>`, `#gh:<ref>`, `#hg:<ref>`, known-project fallback refs, and underscore shorthand continue to bypass
  default injection.
- Multi-agent xprompts are still detected before default injection so a sole `#multi_agent_prompt` reference can fan
  out.

## Current Shape

The default is currently hardcoded in `src/sase/xprompt/_parsing.py`:

- `normalize_default_vcs_workflow_segment(..., default_vcs_prefix="#cd:~")`
- `normalize_default_vcs_workflow()` delegates per segment to that function.

The normalized prompt is used by several dispatch paths:

- Foreground `sase run` in `src/sase/main/query_handler/_query.py`.
- Background CWD launches in `src/sase/agent/launch_cwd.py`.
- TUI launch body in `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`.
- Multi-prompt defaulting in `src/sase/agent/multi_prompt_launcher.py`.

The existing `#git` workflow is already a VCS workspace workflow (`src/sase/xprompts/git.yml`) backed by the built-in
bare-git workspace plugin. `#git:home` resolution relies on `~/.sase/projects/home/home.gp` containing `BARE_REPO_DIR`
and `WORKSPACE_DIR`, or else the current bare-git resolver may auto-initialize a new `home` project at the default bare
git locations.

## Design

Introduce a single canonical default workspace prefix, `#git:home`, instead of leaving the literal default embedded in a
function signature. The default should be used by all existing normalization callers, including per-segment
normalization.

Keep `#cd` as an explicit opt-out path for direct home/directory execution. This is important because `#git:home`
changes launch semantics from "home mode, workspace 0, no VCS" to "project mode, numbered workspace, VCS
setup/release/diff".

Handle `home` project readiness deliberately. The code path must not rely on a missing `#git:home` project accidentally
creating an unrelated empty home repo if the user's intent is to version-control an existing home/dotfiles project.
Implementation should either:

- document and verify the required `sase init-git home --existing ... --clone-dir ...` setup, or
- add a narrow readiness check/error for the default `#git:home` case that points the user at the setup step when the
  `home` project exists but lacks bare-git metadata.

Do not remove `#cd`; this is a default policy change, not deletion of directory-mode workflows.

## Implementation Steps

1. Add a small default constant/helper near the xprompt parsing normalization code, for example
   `DEFAULT_VCS_WORKFLOW_PREFIX = "#git:home"`.

2. Change `normalize_default_vcs_workflow_segment()` so its default argument comes from the new canonical default rather
   than `"#cd:~"`. Keep the explicit `default_vcs_prefix` parameter for tests and future overrides.

3. Audit all callers of `normalize_default_vcs_workflow()` and `normalize_default_vcs_workflow_segment()` to ensure no
   call site still assumes `#cd:~` in comments, home-mode branches, history sorting, MRU recording, or multi-prompt
   fallback behavior.

4. Preserve launch semantics for explicit direct-directory prompts:
   - `#cd:~ do work` should still resolve to home mode, workspace `0`, no numbered workspace claim.
   - Bare `do work` should now normalize to `#git:home do work`, resolve via the bare-git provider, allocate/preallocate
     a numbered workspace, and pass `SASE_GIT_*` preallocation into the child.

5. Add or update focused tests:
   - xprompt parsing normalization: bare prompt, directives, frontmatter, and multi-prompt segments now inject
     `#git:home`.
   - existing explicit `#cd` and explicit `#git` refs are preserved.
   - background `launch_agent_from_cwd("do work")` resolves through `#git:home` and is no longer home mode.
   - multi-prompt defaulting uses `#git:home` for bare segments.
   - TUI non-blocking launch expectations that currently assert `#cd:~ do work` are updated to the new default.

6. Update docs that explicitly describe the default:
   - `docs/xprompt.md`
   - `docs/workspace.md`
   - `docs/ace.md`

7. Add a short migration note in docs or release-facing text:
   - default bare prompts now use `#git:home`;
   - use `#cd:~` for direct home-directory/no-VCS runs;
   - ensure the `home` bare-git project exists and points at the intended repo before relying on the new default.

8. Verify with targeted tests first, then full repo checks:
   - `pytest tests/test_cd_vcs_parsing.py tests/test_cd_launch_resolution.py tests/ace/tui/test_agent_launch_non_blocking.py`
   - any additional tests touched by the audit
   - `just install`
   - `just check`

## Risks And Mitigations

- **Accidental empty `home` project creation**: `resolve_git_ref("home")` can auto-initialize if no project exists. The
  plan calls this out explicitly; implementation should ensure the user's intended `home` repo is configured or provide
  a clear error/migration path.
- **Behavioral shift from home mode to project mode**: bare prompts will now claim numbered workspaces and run VCS
  setup. Tests should assert the new launch metadata, not just the normalized text.
- **Multi-agent xprompt regression**: default injection must remain after multi-agent detection. Existing comments and
  tests around this should be retained and updated only for the default prefix.
- **History/MRU churn**: prompt history will store `#git:home` for bare prompts. That is expected, but docs and tests
  need to reflect it.
