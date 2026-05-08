# GitHub Plugin Hook Gap Analysis

Date: 2026-05-08

## Question

The sase-google plugin appears to support more of SASE's hook surface than the
sase-github plugin. What functionality is currently missing from the GitHub
plugin?

## Repositories inspected

- Core SASE repo: `sase_103`
- GitHub plugin repo: `../sase-github`
- Google/Mercurial plugin repo: `../sase-google`

Relevant source files:

- `src/sase/vcs_provider/_hookspec.py`
- `src/sase/workspace_provider/_hookspec.py`
- `src/sase/vcs_provider/plugins/_git_common.py`
- `src/sase/vcs_provider/plugins/_git_core_ops.py`
- `src/sase/vcs_provider/plugins/_git_query_ops.py`
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`
- `../sase-github/src/sase_github/plugin.py`
- `../sase-github/src/sase_github/workspace_plugin.py`
- `../sase-github/src/sase_github/default_config.yml`
- `../sase-google/src/sase_google/plugin.py`
- `../sase-google/src/sase_google/workspace_plugin.py`
- `../sase-google/src/sase_google/default_config.yml`

## High-level finding

The raw method count in `sase_github/plugin.py` is misleading because
`GitHubPlugin` inherits most VCS hook implementations from SASE core's
`GitCommon` mixins. With inherited hooks counted, GitHub supports most of the
VCS hook contract.

The meaningful GitHub gaps are not basic git operations. They are Google/Hg
workflow affordances that have no GitHub equivalent yet:

- reviewer discovery and reviewer-comment polling;
- provider-level rewind from stored diffs;
- default ChangeSpec hooks, metahooks, precommit, and PR tag defaults;
- richer mail/description preparation for review workflows;
- provider-specific BUG normalization.

## VCS provider hook comparison

Core VCS hookspec count: 55.

GitHub support, counting inherited `GitCommon` methods: 50 hooks.

Google support: 49 hooks.

Google-only VCS hook implementations that GitHub does not provide directly:

| Hook | Google behavior | GitHub status | Impact |
|---|---|---|---|
| `vcs_find_reviewers` | Runs `p4 findreviewers -c <cl>` | Missing | GitHub has no equivalent SASE path for suggested reviewers during mail prep. |
| `vcs_rewind` | Runs `sase_google_rewind` over reverse-ordered diff files | Missing | The Rewind workflow calls `provider.rewind(...)`; GitHub currently cannot run that provider operation. |
| `vcs_normalize_bug_value` | Normalizes `b/123`, `http://b/123`, etc. to `http://b/123` | Falls back to identity | BUG tag sync on GitHub stores exactly what the user typed. |
| `vcs_prepare_description_for_reword` | Escapes strings for the Hg reword command | Falls back to identity | This is probably not a functional gap for GitHub because git amend receives argv directly. |
| `vcs_detect_repo_type` | Detects `.hg` directories as `hg` | Missing, but not needed | GitHub repos are detected through `.git` plus `vcs_classify_repo`. |

GitHub-only VCS support not present in the Google plugin:

- `vcs_classify_repo`, used to claim GitHub remotes.
- `vcs_can_rename_branch`, returns `False` because pushed GitHub PR branches are treated as immutable.
- `vcs_resolve_revision` and `vcs_resolve_current_changespec_head_ref`, inherited from git query mixins.
- `vcs_show_revision`, inherited from git query mixins.
- `vcs_finalize_commit`, inherited from git commit dispatch and used by commit resume.

This means GitHub is not generally behind on the VCS hookspec. It is missing a
small set of Google-specific operations, while also having some git/GitHub-only
operations that Google does not need.

## Workspace provider hook comparison

Core workspace hookspec count: 14.

GitHub plugin implements 11 workspace hooks. Google plugin implements 11
workspace hooks.

Google-only workspace hook implementation:

| Hook | Google behavior | GitHub status | Impact |
|---|---|---|---|
| `ws_generate_reviewer_comments_script` | Returns `critique_comments <changespec> 2>&1` | Missing | GitHub cannot start SASE reviewer-comment checks. |

Related behavior:

- Google `ws_supports_reviewer_comments` returns `True` for `http://cl/...`.
- GitHub `ws_supports_reviewer_comments` explicitly returns `False` for GitHub URLs.
- Core `start_reviewer_comments_check` skips the reviewer-comments check when a plugin says comments are unsupported.

GitHub-only workspace hook implementation:

| Hook | GitHub behavior | Google status | Impact |
|---|---|---|---|
| `ws_submit` | Merges PRs with `gh pr merge --merge --delete-branch`, then finalizes the ChangeSpec | Missing | Google appears to rely on other/legacy submission behavior rather than this workspace hook. |

Workspace hooks missing from both plugins:

- `ws_setup_workflow`
- `ws_get_workspace_name`

Those are not GitHub-specific gaps.

## Default ChangeSpec hooks and metahooks

This is the largest practical difference if "hooks" means SASE ChangeSpec hooks
rather than pluggy hook methods.

`sase-google/default_config.yml` contributes:

- `precommit_command: "sase_hg_fix"`
- `vcs_provider.default_hooks`
  - `!$sase_google_presubmit`
  - `$sase_google_lint`
- `vcs_provider.pr_tags`
  - `AUTOSUBMIT_BEHAVIOR`
  - `MARKDOWN`
  - `R`
  - `STARTBLOCK_AUTOSUBMIT`
  - `WANT_LGTM`
- `metahooks`
  - `hg_presubmit_tap`
  - `scuba`
- many Google-specific mentor profiles and xprompts.

`sase-github/default_config.yml` currently contains only:

```yaml
xprompts: {}
```

Core reads `vcs_provider.default_hooks` through
`get_required_changespec_hooks()`, so new ChangeSpecs get Google default hooks
when the Google plugin contributes that config. There is no equivalent GitHub
default hook set today.

Core metahook behavior is also config-driven: failing hook output is matched
against configured `metahooks`, and matching metahooks dispatch
`sase_metahook_<name>`. Since the GitHub plugin contributes no metahooks and no
metahook scripts, GitHub does not have Google-style specialized hook failure
handling.

## Practical unsupported functionality in GitHub

1. Reviewer-comment polling and comment-response automation.

   Google supports background reviewer comment checks through
   `ws_generate_reviewer_comments_script` and `critique_comments`. GitHub
   explicitly reports reviewer comments unsupported, so core skips that check.

2. Reviewer discovery during mail preparation.

   Google mail prep accepts `@` to run reviewer discovery through
   `vcs_find_reviewers`. GitHub mail prep only shows branch/description and asks
   whether to push/create or update the PR.

3. Rewind workflow provider operation.

   The core rewind workflow calls `provider.rewind(diff_files_reversed, cwd)`.
   Google implements this via `sase_google_rewind`; GitHub has no implementation.

4. Default ChangeSpec hooks for PRs.

   Google installs default hooks for presubmit and lint through plugin config.
   GitHub has no default `vcs_provider.default_hooks`, so it does not attach
   provider-supplied PR checks to new ChangeSpecs.

5. Metahook handling for known failure formats.

   Google config maps known hook output patterns to metahooks. GitHub has no
   plugin-provided metahook config or scripts.

6. Provider-specific precommit/fix behavior.

   Google sets `precommit_command: "sase_hg_fix"` and implements `vcs_fix` via
   `hg fix`. GitHub inherits no-op `vcs_fix` and `vcs_upload` behavior from the
   git query mixin, so there is no provider-specific auto-fix/upload step.

7. Rich PR/CL tag defaults and formatting.

   Google contributes default PR tags and its workspace description formatter
   writes BUG/FIXED and review/autosubmit metadata. GitHub's formatter only
   prepends `[project]`. Core can append configured PR tags for any provider,
   but the GitHub plugin supplies no defaults.

8. Provider-specific BUG normalization.

   Google normalizes bug references to `http://b/<id>`. GitHub uses the core
   identity fallback, so BUG values are not canonicalized into issue URLs or any
   other GitHub-specific format.

## Things that look unsupported but are not real GitHub gaps

- Basic VCS operations are mostly inherited from `GitCommon`, including
  checkout, diff, apply patch, add/remove, clean, commit, amend, rebase,
  archive, prune, stash, branch resolution, file-at-revision, sync, conflict
  handling, reword, create commit/proposal/PR, and finalize commit.
- `vcs_detect_repo_type` is absent from GitHub because core detects `.git`
  repositories and then calls GitHub's `vcs_classify_repo` to claim
  `github.com` remotes.
- `vcs_prepare_description_for_reword` falls back to identity for GitHub. That
  is acceptable for the current git implementation because it calls
  `git commit --amend -m <description>` using argv rather than shell quoting.
- `ws_submit` is actually supported by GitHub and missing from Google.

## Possible next implementation targets

If the goal is feature parity where GitHub can support the same SASE workflows
as Google, the most valuable GitHub plugin additions are:

1. Add GitHub reviewer-comment support:
   - implement `ws_generate_reviewer_comments_script`;
   - change `ws_supports_reviewer_comments` to return `True` for GitHub PR URLs
     once a GitHub comments command exists;
   - decide whether output should emulate `critique_comments` or use a new
     parser.

2. Add GitHub reviewer discovery:
   - implement `vcs_find_reviewers` using GitHub CODEOWNERS, PR reviewers, or
     `gh api`/GraphQL;
   - extend GitHub mail prep with a reviewer prompt if that UX is desired.

3. Add GitHub rewind support:
   - implement `vcs_rewind` using `git apply -R`, branch reset, or replayed
     stored diffs;
   - review the core rewind workflow's Hg-specific messages and assumptions.

4. Add GitHub default config:
   - decide provider default hooks for PR workflows;
   - add default `pr_tags` only if they make sense outside Google;
   - add metahooks for common GitHub CI/test failure formats if useful.

5. Add GitHub BUG normalization:
   - normalize `#123`, `issues/123`, and full issue URLs to a canonical GitHub
     issue URL when the repository origin is known.

