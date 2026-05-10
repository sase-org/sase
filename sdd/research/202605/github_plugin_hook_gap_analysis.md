# GitHub Plugin Hook Gap Analysis

Date: 2026-05-08 (revised 2026-05-08)

## Question

The retired Mercurial plugin plugin appears to support more of SASE's hook surface than the
sase-github plugin. What functionality is currently missing from the GitHub
plugin?

## Repositories inspected

- Core SASE repo: `sase_100`
- GitHub plugin repo: `../sase-github`
- Google/Mercurial plugin repo: `../retired Mercurial plugin`

Relevant source files:

- Core hookspecs and shared mixins
  - `src/sase/vcs_provider/_hookspec.py`
  - `src/sase/workspace_provider/_hookspec.py`
  - `src/sase/vcs_provider/plugins/_git_common.py`
  - `src/sase/vcs_provider/plugins/_git_core_ops.py`
  - `src/sase/vcs_provider/plugins/_git_query_ops.py`
  - `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`
  - `src/sase/workspace_provider/plugins/bare_git_workspace.py`
- Core config consumers (gap-relevant)
  - `src/sase/vcs_provider/config.py` — `get_pr_tags`, `get_use_project_pr_prefix`
  - `src/sase/ace/hooks/defaults.py` — reads `vcs_provider.default_hooks`
  - `src/sase/workflows/commit/pr_operations.py` — applies `_pr_title_prefix` and `pr_tags`
  - `src/sase/config/metahook.py` — dispatches `metahooks` from config
- GitHub plugin
  - `../sase-github/src/sase_github/plugin.py`
  - `../sase-github/src/sase_github/workspace_plugin.py`
  - `../sase-github/src/sase_github/config.py`
  - `../sase-github/src/sase_github/default_config.yml`
  - `../sase-github/src/sase_github/scripts/{gh_setup,new_pr_desc_get_context}.py`
  - `../sase-github/src/sase_github/xprompts/*.yml`
  - `../sase-github/pyproject.toml` (entry points)
- Google plugin
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/workspace_plugin.py`
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/scripts/*` (24 console scripts)
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/*.{yml,md}`
  - `../retired Mercurial plugin/src/retired_mercurial_plugin/llm_jetski/provider.py`
  - `../retired Mercurial plugin/pyproject.toml` (entry points)

## High-level finding

The raw method count in `sase_github/plugin.py` is misleading because
`GitHubPlugin` extends `GitCommon` (which itself composes `_git_core_ops`,
`_git_query_ops`, and `_git_commit_dispatch` mixins). With those inherited
hooks counted, GitHub already covers most of the VCS hookspec.

The genuine GitHub gaps fall into three categories:

1. **Hook implementations** that have no GitHub equivalent (reviewer
   discovery/comments, rewind, BUG normalization, provider-specific fix/upload).
2. **Plugin-contributed configuration** that is empty in
   `sase-github/default_config.yml` (default ChangeSpec hooks, metahooks,
   PR tags, project-PR-title prefix toggle, mentor profiles, precommit command).
3. **Auxiliary plugin surface area** that exists for Google and not for
   GitHub: a `sase_llm` provider entry point (Jetski) and 24 console scripts
   that the Google hooks delegate to.

The first category is where the SASE *hookspec* is unimplemented. The second
two categories are why the practical user-visible feature gap feels even
larger than the hookspec count suggests.

## VCS provider hook comparison

Total methods declared on `VCSHookSpec` (counting every `@hookspec` plus the
two classification hooks at the bottom of the file): **55**.

GitHub support, counting hooks inherited from `GitCommon` and its mixins: **50
hooks**. (Inherited from `_git_core_ops`, `_git_query_ops`, and
`_git_commit_dispatch`; only `vcs_classify_repo`, `vcs_can_rename_branch`,
`vcs_abandon_change`, `vcs_get_change_url`, `vcs_get_change_body`,
`vcs_get_cl_number`, `vcs_mail`, and `vcs_create_pull_request` are overridden
or added in `sase_github/plugin.py`.)

Google support: **49 hooks** (all defined directly in `retired_mercurial_plugin/plugin.py`
on `HgPlugin`, which does *not* extend `GitCommon`).

### Google-only VCS hook implementations that GitHub does not provide

| Hook | Google behavior | GitHub status | Impact |
|---|---|---|---|
| `vcs_find_reviewers` | Runs `p4 findreviewers -c <cl>` | Missing | GitHub mail prep has no reviewer-discovery affordance. |
| `vcs_rewind` | Runs `retired_mercurial_plugin_rewind` over reverse-ordered diff files | Missing | The core rewind workflow's `provider.rewind(...)` call has no GitHub backend. |
| `vcs_normalize_bug_value` | Normalizes `b/123`, `http://b/123`, etc. to `http://b/123` | Falls back to identity | BUG tag values stored on GitHub ChangeSpecs are kept verbatim. |
| `vcs_prepare_description_for_reword` | Escapes strings for `hg reword` | Falls back to identity | Not a functional gap for GitHub; `git commit --amend -m` takes argv directly. |
| `vcs_detect_repo_type` | Detects `.hg` directories as `hg` | Missing, but not needed | GitHub repos are identified via `.git` plus `vcs_classify_repo`. |
| `vcs_fix` | Runs `hg fix` | Inherits no-op from `_git_query_ops` | No provider-specific auto-fix on GitHub. |
| `vcs_upload` | Runs `hg upload tree` | Inherits no-op | No provider-specific upload step (push happens inside `vcs_mail`). |
| `vcs_reword` / `vcs_reword_add_tag` | Run `retired_mercurial_plugin_reword` | Inherited git stubs | Programmatic CL/PR description rewrite is Google-only today. |

### GitHub-only VCS support not present in Google

- `vcs_classify_repo` — used by the registry to claim GitHub remotes.
- `vcs_can_rename_branch` — returns `False` because GitHub PR branches are
  immutable once pushed.
- `vcs_resolve_revision`, `vcs_resolve_current_changespec_head_ref`,
  `vcs_show_revision`, `vcs_diff_*`, `vcs_finalize_commit`, etc. — inherited
  from the git mixins. Google does not extend `GitCommon`, so these are not
  available on `HgPlugin` (and Hg has no need for them).

The takeaway: GitHub is not generally behind on the VCS hookspec. It is
missing a small set of Google-specific operations, while also having some
git/GitHub-only operations that Google does not need.

## Workspace provider hook comparison

`WorkspaceHookSpec` declares **14** hook methods.

| Hook | GitHub | Google | Notes |
|---|---|---|---|
| `ws_get_workflow_metadata` | yes | yes | |
| `ws_detect_workflow_type` | yes | yes | |
| `ws_get_change_label` | yes (`PR`) | yes (`CL`) | |
| `ws_resolve_ref` | yes (`#gh`) | yes (`#hg`) | |
| `ws_submit` | **yes** | **no** | GitHub-only: `gh pr merge --merge --delete-branch`. |
| `ws_setup_workflow` | no, but provided by core `bare_git_workspace` | no | GitHub falls back to the core git workspace plugin. |
| `ws_extract_change_identifier` | yes (PR# from URL) | yes (CL# from URL) | |
| `ws_generate_submitted_check_script` | yes (`gh pr view ... state==MERGED`) | yes (`is_cl_submitted`) | |
| `ws_supports_reviewer_comments` | **`False` for github.com** | **`True` for `http://cl/`** | Core skips comment polling on GitHub URLs. |
| `ws_generate_reviewer_comments_script` | **no** | yes (`critique_comments <cs>`) | Core cannot start a reviewer-comments check for PRs. |
| `ws_get_workspace_directory` | yes (git clone) | yes (`retired_mercurial_plugin_get_workspace`) | |
| `ws_prepare_mail` | yes (display branch + confirm push) | yes (reviewer prompt + auto-startblock + reword) | Google's flow is significantly richer. |
| `ws_format_commit_description` | yes (prepends `[project]`) | yes (prepends `[project]` and writes `BUG`/`FIXED` and configured `pr_tags`) | |
| `ws_get_workspace_name` | no, but provided by core `bare_git_workspace` | no | |

Both plugins implement **11** workspace hooks directly. The asymmetry is in
*which* eleven, not the count.

## Default ChangeSpec hooks, metahooks, and provider config

This is the largest practical difference if "hooks" means SASE ChangeSpec
hooks rather than pluggy hook methods. The Google plugin contributes
significant default configuration via its `default_config.yml`; GitHub
contributes essentially none.

`retired Mercurial plugin/default_config.yml` contributes:

- `llm_provider.provider: gemini` (default LLM).
- `precommit_command: "sase_hg_fix"` — run before commits.
- `vcs_provider.use_project_pr_prefix: true` — wrap PR/CL titles with `[project]`.
- `vcs_provider.default_hooks: ["!$retired_mercurial_plugin_presubmit", "$retired_mercurial_plugin_lint"]`
  — attached to every new ChangeSpec via `get_required_changespec_hooks()`.
- `vcs_provider.pr_tags`: `AUTOSUBMIT_BEHAVIOR`, `MARKDOWN`, `R=startblock`,
  `STARTBLOCK_AUTOSUBMIT`, `WANT_LGTM` — applied by
  `apply_pr_tags_to_payload()` and written into commit descriptions by
  `HgWorkspacePlugin.ws_format_commit_description`.
- `metahooks` for `hg_presubmit_tap` and `scuba` — failing hook output is
  matched against these patterns by `src/sase/config/metahook.py` and
  dispatched as `sase_metahook_<name>` scripts.
- `mentor_profiles` (six profiles: `aaa`, `code`, `g3doc`, `pubfeat`, `sql`,
  `ui`) — picked up by mentor-driven review workflows.
- ~30 user-facing `xprompts` for Google-internal CL workflows
  (`b`, `bug`, `clr`, `clref`, `cldd`, `cl_diff`, `launch/*`,
  `my_cl_desc_advice`, `presubmit`, `sase_new_cl_desc`, etc.).

`sase-github/default_config.yml` currently contains only:

```yaml
xprompts: {}
```

So GitHub does not contribute any default ChangeSpec hooks, metahooks, PR
tags, project PR title prefix opt-in, mentor profiles, precommit fixer, LLM
provider default, or convenience xprompts beyond the four workflow files
under `sase_github/xprompts/`.

## Plugin entry points and auxiliary surface

`pyproject.toml` entry points show another asymmetry.

| Entry point group | sase-github | retired Mercurial plugin |
|---|---|---|
| `sase_vcs` | 1 (`GitHubPlugin`) | 1 (`HgPlugin`) |
| `sase_workspace` | 1 (`GitHubWorkspacePlugin`) | 1 (`HgWorkspacePlugin`) |
| `sase_xprompts` | 1 (package) | 1 (package) |
| `sase_config` | 1 (package) | 1 (package) |
| `sase_llm` | **0** | **1** (`jetski` provider in `llm_jetski/provider.py`) |
| `project.scripts` | **0** | **24** (every `retired_mercurial_plugin_*`, `sase_metahook_*`, `sase_hg_fix`, `sase_refresh_cl_desc`, `sase_split_*`) |

The Google plugin therefore also ships an LLM provider and a complete set of
console scripts that its hook implementations shell out to. The GitHub plugin
ships only the two Python helpers used by its xprompts (`gh_setup.py`,
`new_pr_desc_get_context.py`).

`sase-github/src/sase_github/config.py` does provide one config helper —
`get_github_orgs()` — which is required by `_clone_gh_repo()` and the
`ws_submit` flow. The Google plugin has no analogous helper because its
workspace allocation is entirely script-driven.

## XPrompts shipped by each plugin

Both plugins ship a similar number of user-facing xprompts, though they cover
different scopes.

- sase-github (4 files):
  - `gh.yml` — main `#gh` workflow (resolve, claim, checkout, prompt, release, capture diff).
  - `new_pr_desc.yml` — agent-generated PR title/body, applied via `gh pr edit`.
  - `pr_diff.yml` — `git diff origin/HEAD...HEAD` against the detected default branch.
  - `prdd.yml` — `append_to_commit_and_propose` prompt part injecting PR diff and description.
- retired Mercurial plugin (6 files): `hg.yml`, `crs.md` (Critique-comments response),
  `refresh_cl_desc.yml`, `split.yml`, `split_executor.md`,
  `split_spec_generator.md`. Plus the ~30 small xprompts in
  `default_config.yml`.

GitHub does not have:

- A Critique-style comments-response xprompt (`#crs`).
- A description-refresh workflow (`#refresh_cl_desc` / `sase_refresh_cl_desc`).
- A CL/PR split workflow (`#split` + `split_executor` + `split_spec_generator`).

## Practical unsupported functionality in GitHub

The list below merges the previous summary with the additional findings from
this round of research.

1. **Reviewer-comment polling and comment-response automation.** Google
   supports background reviewer-comment checks through
   `ws_generate_reviewer_comments_script` (returning `critique_comments
   <changespec>`) and ships the `#crs` xprompt for response. GitHub's
   `ws_supports_reviewer_comments` explicitly returns `False`, so core's
   `start_reviewer_comments_check` skips the check. There is no
   GitHub-comments-equivalent script.
2. **Reviewer discovery during mail preparation.** Google `_prepare_mail_hg`
   accepts `@` to run `provider.find_reviewers` (which calls `p4
   findreviewers`); GitHub `_prepare_mail_git` only displays branch and
   description and confirms push.
3. **Rewind workflow provider operation.** The core rewind workflow calls
   `provider.rewind(diff_files_reversed, cwd)`. Google delegates to
   `retired_mercurial_plugin_rewind`; GitHub has no implementation, so the core rewind
   workflow cannot complete on a GitHub workspace.
4. **Default ChangeSpec hooks for PRs.** Google attaches
   `!$retired_mercurial_plugin_presubmit` and `$retired_mercurial_plugin_lint` to every new ChangeSpec
   via `vcs_provider.default_hooks`. GitHub's plugin contributes no defaults,
   so PRs ship without provider-supplied checks unless the user adds them
   manually.
5. **Metahook handling for known failure formats.** Google config maps known
   hook output patterns to metahooks (`hg_presubmit_tap`, `scuba`) and ships
   `sase_metahook_*` scripts. GitHub has no plugin-provided metahook config
   or scripts, so common GitHub CI failure formats are not specially handled.
6. **Provider-specific precommit/fix behavior.** Google sets
   `precommit_command: "sase_hg_fix"` and implements `vcs_fix` via `hg fix`.
   GitHub inherits the no-op `vcs_fix` and `vcs_upload` from `_git_query_ops`
   and does not register a precommit command, so there is no
   provider-specific auto-fix or auto-format step for PRs.
7. **PR/CL tag defaults and rich description formatting.** Google contributes
   default `pr_tags` (e.g. `R=startblock`, `WANT_LGTM=all`) and writes
   `BUG`/`FIXED`/`pr_tags` blocks into commit descriptions. GitHub's
   `ws_format_commit_description` only prepends `[project]`. Core can append
   configured `pr_tags` for any provider, but GitHub supplies none and does
   not opt into `use_project_pr_prefix`, so PR titles are not prefixed by
   default either.
8. **Provider-specific BUG normalization.** Google normalizes bug references
   to `http://b/<id>`. GitHub uses the core identity fallback, so BUG values
   are not canonicalized into issue URLs or any GitHub-specific format.
9. **Programmatic description rewrite.** `vcs_reword` and
   `vcs_reword_add_tag` are Hg-specific (`retired_mercurial_plugin_reword`). GitHub
   inherits the git stubs, so the Google mail-prep flow's auto-startblock
   injection and tag editing have no direct GitHub equivalent.
10. **CL split workflow.** `#split`, `#split_executor`, and
    `#split_spec_generator` (plus `sase_split_setup` /
    `sase_split_prepare_execute` console scripts) drive an
    HITL-reviewed multi-CL split. GitHub has no equivalent multi-PR split
    workflow.
11. **Description refresh workflow.** Google's `#refresh_cl_desc` regenerates
    a CL description and applies it through `sase_refresh_cl_desc` (which
    uses `vcs_reword` under the hood). GitHub's `#new_pr_desc` is similar but
    only updates a *PR* (not the underlying commit message) via `gh pr edit`,
    and only when a PR already exists for the branch.
12. **Mentor profiles.** Google ships six profiles (`aaa`, `code`, `g3doc`,
    `pubfeat`, `sql`, `ui`) with file-glob-keyed mentor focus areas. GitHub
    ships none, so the mentor system is empty for GitHub-only users unless
    they author profiles in user config.
13. **LLM provider plugin.** Google contributes a `sase_llm` entry point
    (`jetski`) via `llm_jetski/provider.py`. The GitHub repo has no LLM
    provider entry point.

## Things that look unsupported but are not real GitHub gaps

- Basic VCS operations are mostly inherited from `GitCommon`, including
  checkout, diff, apply patch, add/remove, clean, commit, amend, rebase,
  archive, prune, stash, branch resolution, file-at-revision, sync, conflict
  handling, create commit/proposal/PR, and finalize commit.
- `vcs_detect_repo_type` is absent from GitHub because core detects `.git`
  repositories and then calls GitHub's `vcs_classify_repo` to claim
  `github.com` remotes.
- `vcs_prepare_description_for_reword` falling back to identity is fine for
  current git usage; `git commit --amend -m <description>` receives argv
  rather than a shell-quoted string.
- `ws_setup_workflow` and `ws_get_workspace_name` are absent from
  `GitHubWorkspacePlugin`, but `bare_git_workspace.py` in core implements
  both for any git repository, so GitHub still picks them up.
- `ws_submit` is supported by GitHub and absent from Google.

## Possible next implementation targets

If the goal is feature parity where GitHub can support the same SASE
workflows as Google, the most valuable additions are roughly:

1. **GitHub reviewer-comment support** — implement
   `ws_generate_reviewer_comments_script` (e.g. wrap `gh pr view --json
   reviewThreads` / `gh api`), flip `ws_supports_reviewer_comments` to
   `True`, and add a GitHub `#crs` analogue.
2. **GitHub reviewer discovery** — implement `vcs_find_reviewers` from
   CODEOWNERS / past PR reviewers / `gh api`, and extend `_prepare_mail_git`
   with a reviewer prompt parallel to the Hg flow.
3. **GitHub rewind support** — implement `vcs_rewind` using `git apply -R`,
   branch reset, or replayed stored diffs, and revisit any Hg-specific
   wording in the core rewind workflow.
4. **GitHub default config** — populate `default_config.yml` with sensible
   defaults: `vcs_provider.default_hooks` for PR checks, optional
   `use_project_pr_prefix`, GitHub-shaped `pr_tags`, and metahooks for
   common GH Actions / `gh pr checks` failure formats.
5. **GitHub BUG normalization** — normalize `#123`, `issues/123`, and full
   issue URLs to a canonical issue URL when the repo origin is known.
6. **GitHub description refresh / split** — port `#refresh_cl_desc` to update
   PR titles/bodies *and* the underlying commit message via `git commit
   --amend`, and add an analogue of `#split` for multi-PR stacks.
7. **GitHub precommit and fix** — pick a default formatter / linter (e.g.
   `pre-commit`) and wire it via `precommit_command` and `vcs_fix`.
8. **GitHub mentor profiles** — author at least a baseline set so
   GitHub-only users are not starting from an empty mentor system.
