# VCS Provider Reference

The **VCS provider layer** is an abstraction that lets sase commands work with both **Git** and **Mercurial**
repositories. Commands and workflows that touch version control, including `sase commit`, `sase ace`, `sase axe`,
`sase revert`, and `sase restore`, delegate to a provider interface rather than calling VCS commands directly.

Git and Mercurial share the same SASE concepts: ChangeSpecs, workspace checkout, diff capture, commit/proposal dispatch,
review submission, revert, and restore. Provider-specific capabilities and prerequisites still matter. For example,
GitHub pull-request operations require the optional `sase-github` plugin and the GitHub CLI, while Mercurial support
requires a maintained provider plugin that supplies `sase_hg_*` helper commands.

## Plugin Architecture

VCS providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins. The core `sase` package only bundles
the **BareGitPlugin** (for plain git repositories). Additional VCS backends are installed as separate packages:

| Package       | Plugin          | Description                               |
| ------------- | --------------- | ----------------------------------------- |
| `sase` (core) | `BareGitPlugin` | Standard git operations (bundled)         |
| `sase-github` | `GitHubPlugin`  | Git + GitHub CLI (`gh`) for PR operations |

Install optional providers into the same managed SASE environment:

```bash
sase plugin install github   # GitHub PR support
```

Plugins register themselves via the `sase_vcs` entry point group. The plugin manager loads all registered plugins and
dispatches VCS operations through pluggy's `firstresult=True` hook system — the first plugin that returns a non-`None`
result wins.

### Hook Specification

All VCS operations are defined in `VCSHookSpec` (`src/sase/vcs_provider/_hookspec.py`). Each method is prefixed with
`vcs_` and returns `tuple[bool, str | None]` (success flag and optional output). Plugins implement only the hooks they
support; unsupported operations return `None` and are skipped.

The hooks are organized into several groups:

- **Core operations** — `vcs_checkout`, `vcs_diff`, `vcs_diff_revision`, `vcs_apply_patch`, `vcs_apply_patches`,
  `vcs_add_remove`, `vcs_clean_workspace`, `vcs_commit`, `vcs_amend`, `vcs_rename_branch`, `vcs_rebase`, `vcs_archive`,
  `vcs_prune`, `vcs_stash_and_clean`
- **Optional core** — `vcs_resolve_revision`, `vcs_resolve_current_changespec_head_ref`, `vcs_show_revision`,
  `vcs_diff_with_untracked`, `vcs_committed_diff`, `vcs_get_default_parent_revision`, `vcs_diff_name_status`,
  `vcs_diff_line_stats`, `vcs_log`, `vcs_repo_stats`, `vcs_file_at_revision`
- **Sync operations** — `vcs_sync_workspace`, `vcs_is_sync_in_progress`, `vcs_get_conflicted_files`,
  `vcs_continue_sync`, `vcs_abort_sync`
- **Commit dispatch** — `vcs_create_commit`, `vcs_create_proposal`, `vcs_create_pull_request` (the three commit workflow
  methods dispatched by `CommitWorkflow`), plus `vcs_finalize_commit` (replays idempotent post-commit work — bead amend,
  push-with-retry — when `sase commit --resume` finishes a workflow whose dispatch was interrupted by a merge conflict;
  plugins that cannot safely replay finalization can leave this unimplemented, and the workflow will only replay its
  tracking steps). See [commit_workflows.md](commit_workflows.md#resume-after-conflict).
- **VCS-agnostic operations** — `vcs_abandon_change`, `vcs_prepare_description_for_reword`, `vcs_normalize_bug_value`,
  `vcs_get_change_url`, `vcs_get_change_body`
- **Info and review hooks** — `vcs_reword`, `vcs_reword_add_tag`, `vcs_get_description`, `vcs_get_branch_name`,
  `vcs_get_pr_number`, `vcs_get_workspace_name`, `vcs_has_local_changes`, `vcs_get_bug_number`, `vcs_mail`, `vcs_fix`,
  `vcs_upload`, `vcs_find_reviewers`, `vcs_rewind`
- **Branch naming hooks** — `vcs_derive_branch_name`, `vcs_derive_branch_name_with_suffix` (compute branch names from
  ChangeSpec names), `vcs_can_rename_branch` (check if branch renaming is supported)
- **Classification hooks** — `vcs_detect_repo_type` (detect VCS markers like `.hg/` or `.git/`) and `vcs_classify_repo`
  (classify git repos by remote URL, e.g. GitHub vs bare)

### Disabling Plugins

The VCS provider registry loads provider entry points directly. It does not currently consult the resource-plugin
disable switches described in [docs/configuration.md](configuration.md#plugin-system). Use `SASE_VCS_PROVIDER` or
`vcs_provider.provider` to force a provider selection.

## Provider Selection

Sase uses a 3-tier resolution strategy to decide which VCS provider to use. The first tier that returns a concrete
provider wins.

### Tier 1: Environment Variable

The `SASE_VCS_PROVIDER` environment variable takes highest priority.

```bash
# Force the Git provider family; GitHub remotes are reclassified when the plugin is installed.
SASE_VCS_PROVIDER=git sase commit my_feature

# Force hg provider
SASE_VCS_PROVIDER=hg sase ace

# Defer to next tier
SASE_VCS_PROVIDER=auto sase commit my_feature
```

The `--vcs-provider` CLI flag on `sase ace` and `sase axe` sets this variable internally:

```bash
# Equivalent to SASE_VCS_PROVIDER=git sase ace
sase ace --vcs-provider git

# Same for axe
sase axe --vcs-provider hg start
```

Valid values: `git`, `hg`, `auto`.

### Tier 2: Configuration File

If the environment variable is not set (or is unset entirely — not `"auto"`), sase checks `~/.config/sase/sase.yml`:

```yaml
vcs_provider:
  provider: git # or "hg" or "auto"
```

Setting `provider: auto` defers to auto-detection (Tier 3).

**Note:** If the environment variable is set to `"auto"`, the config file is skipped entirely and auto-detection runs
directly. Only an unset environment variable consults the config.

### Tier 3: Auto-Detection

If neither the environment variable nor config file specifies a provider, sase walks up the directory tree from the
current working directory looking for `.hg/` or `.git/` directories. The first one found determines the provider.

- `.hg/` found first → Mercurial provider (`"hg"`)
- `.git/` found first → Git provider. If a plugin claims the Git remote, such as `sase-github` claiming a configured
  GitHub host, that provider name wins.
- `.git/` found with a hosted remote (e.g., GitHub) but no VCS plugin claims the repo → falls back to `"bare_git"`. This
  preserves baseline commit capability even without provider-specific plugins like `sase-github`.
- `.git/` found without a readable `origin` URL and no plugin claim → **Error**: `VCSProviderNotFoundError`
- Neither found → **Error**: `VCSProviderNotFoundError`

With the bundled and documented optional providers, `detect_vcs()` commonly returns `"github"`, `"bare_git"`, or `"hg"`.
Additional plugins may return their own provider names. `detect_vcs_family()` collapses `"github"` and `"bare_git"` into
`"git"` for contexts that only care about the VCS family.

## Per-Command VCS Usage

### `sase vcs list`

Lists the available repository constellation: the primary repository, configured linked repositories, and the
materialized separate SDD store when present. A bare `sase vcs` delegates to `sase vcs list`. The log command excludes
the separate SDD history by default; use `sase vcs log --sdd` to include it.

Common forms:

```bash
sase vcs
sase vcs list
sase vcs list --sort recent
sase vcs list --repo sase-core --format json
```

Options:

| Option                                     | Purpose                                                                |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| `-c`, `--color auto/always/never`          | Control colorized pretty output.                                       |
| `-f`, `--format pretty/oneline/json`       | Choose rich pretty output, pipe-friendly rows, or JSON.                |
| `-N`, `--no-fetch`                         | Skip provider-backed description lookups.                              |
| `-o`, `--current-only`                     | Read only the current/primary repo.                                    |
| `-r`, `--repo NAME`                        | Restrict to a resolved repo name. Repeatable.                          |
| `-s`, `--sort default/name/commits/recent` | Keep resolved order or sort by name, commit count, or recent activity. |

The pretty output shows a summary line, then one block per repo with its kind, branch, dirty state, configured
description when available, commit count, contributor count, last activity, and latest commit. A failed stats read for
one repo is shown as a warning and does not hide the other repos.

### `sase vcs log`

Shows a day-grouped commit timeline across the primary repository and configured linked repositories. Pass `--sdd` to
also include the current project's materialized separate SDD repository. Pass `--all` to build one timeline from every
registered active or inactive project (excluding the system-managed `home` project), regardless of the current
directory. Global discovery includes each usable primary and configured linked repo without materializing missing
workspaces. Sibling checkouts still appear as linked repositories of their owning projects; `--all --sdd` also includes
materialized separate SDD repositories from the registered projects.

Global discovery canonicalizes checkout paths, so a repository registered independently and linked from one or more
projects is read and fetched only once. Registered project display names take precedence; colliding linked-repo and SDD
labels are qualified with their owning project. `--repo` narrows the eligible set after SDD opt-in, so use
`--sdd --repo sdd` to show only the current project's SDD history. `--repo sdd` without `--sdd` does not expand scope
and reports no match. Failures in one project or provider are warnings and do not hide healthy repositories.

By default the command shows up to 40 commits and trailing SASE commit tags, refreshes a supported remote ref when that
checkout/ref has not been fetched successfully in the last 60 seconds, and marks each commit as synced, unpushed,
remote-only, or unknown when no remote comparison is available. Providers without remote-log comparison still contribute
local history through the provider-neutral `log()` hook; a provider without that hook produces an isolated warning.

When a cache miss or `--fetch` triggers remote I/O, stderr shows `Fetching remote · <repo> ← <ref>` as a transient
spinner in an interactive terminal or a durable status line when redirected. Commit data remains isolated on stdout, so
JSON and oneline output stay safe to pipe.

The short author option moved from `-a` to `-A` because `-a` now selects all-project scope. Existing scripts can migrate
to `-A PATTERN`; the long `--author PATTERN` spelling is unchanged.

Common forms:

```bash
sase vcs log
sase vcs log --all
sase vcs log --sdd
sase vcs log --sdd --repo sdd
sase vcs log --all --sdd
sase vcs log --all --repo sase-core --repo chezmoi
sase vcs log --branch main --no-fetch
sase vcs log --fetch --limit 3
sase vcs log --since 2w --author bryan
sase vcs log --limit 0 --since 2026-07-01 --format full
sase vcs log --reverse --format json --no-tags
```

Options:

| Option                                    | Purpose                                                                                 |
| ----------------------------------------- | --------------------------------------------------------------------------------------- |
| `-a`, `--all`                             | Read repositories from every registered active or inactive project.                     |
| `-A`, `--author PATTERN`                  | Filter by author name/email substring. Repeatable values are ORed case-insensitively.   |
| `-b`, `--branch REF`, `--ref REF`         | Compare against `origin/REF` instead of the resolved remote ref.                        |
| `-c`, `--color auto/always/never`         | Control colorized pretty/full output.                                                   |
| `-o`, `--current-only`                    | Read only the current/primary repo.                                                     |
| `-F`, `--fetch`                           | Fetch remote refs now, bypassing the 60-second freshness cache.                         |
| `-f`, `--format pretty/full/oneline/json` | Choose compact pretty output, full commit-message blocks, pipe-friendly lines, or JSON. |
| `-n`, `--limit N`                         | Max commits in the merged timeline (default: 40); `0` means unlimited.                  |
| `-N`, `--no-fetch`                        | Skip the remote fetch and compare against existing remote-tracking refs.                |
| `-T`, `--no-tags`                         | Hide trailing SASE commit tags in pretty/full/oneline output and omit them from JSON.   |
| `-r`, `--repo NAME`                       | Restrict to a resolved repo name. Repeatable.                                           |
| `-R`, `--reverse`                         | Display the selected commits oldest-first.                                              |
| `-S`, `--sdd`                             | Include commits from materialized separate SDD repositories.                            |
| `-s`, `--since DATE`, `--after DATE`      | Include commits at or after `DATE`.                                                     |
| `-u`, `--until DATE`, `--before DATE`     | Include commits at or before `DATE`.                                                    |

`--all` and `--current-only` are mutually exclusive. `--current-only` reads only the current/primary repo even when
`--sdd` is supplied. `--repo` remains repeatable in global scope and is applied after SDD scope selection,
canonical-path deduplication, and unique label assignment. The `--limit` cap applies to the final merged timeline, not
to each project's inventory: each unique candidate repository is queried deeply enough to compute the global top N. Use
`--limit 0` for an unlimited merged timeline. JSON output records the selected global scope as `query.all`.

`DATE` accepts relative offsets (`Nh`, `Nd`, `Nw`), `today`, `yesterday`, `YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM`. Dates are
resolved in the configured SASE timezone and pushed into the provider query before the limit is applied, so filtered
top-N results do not silently miss matching commits.

### `sase commit`

Dispatches to one of three VCS methods (`create_commit`, `create_proposal`, `create_pull_request`) via the
`CommitWorkflow` orchestrator. See [`docs/commit_workflows.md`](commit_workflows.md) for the full workflow reference.

**Key VCS operations used:**

| Operation       | Git                                                       | Mercurial                                         |
| --------------- | --------------------------------------------------------- | ------------------------------------------------- |
| Bug number      | Returns empty string (not applicable)                     | `sase_hg_branch_bug` command                      |
| Workspace name  | `git config --get remote.origin.url` (extracts repo name) | `workspace_name` command                          |
| Create commit   | `git add` + `git commit` + `git push`                     | `hg commit --name "<name>" --logfile "<logfile>"` |
| Create proposal | Save diff + provider workspace clean                      | `sase_hg_clean <diff_name>`                       |
| Create PR       | Branch + commit + push; GitHub plugin creates the PR      | Not supported natively                            |
| Change URL      | GitHub plugin reads `gh pr view --json url -q .url`       | `http://cl/<branch_number>`                       |

Common CLI forms:

```bash
sase commit -m "Update parser"                         # create_commit
sase commit -t propose -m "Try parser cleanup"         # create_proposal
sase commit -t pr -n parser_cleanup -m "Update parser" # create_pull_request
```

### `sase ace` TUI Actions

The ace TUI provides interactive actions that use VCS operations:

#### Sync (`S` key)

Syncs the workspace with the remote repository.

| Step     | Git                                                       | Mercurial               |
| -------- | --------------------------------------------------------- | ----------------------- |
| Checkout | `git checkout <name>`                                     | `sase_hg_update <name>` |
| Sync     | `git fetch origin` + `git rebase origin/<default_branch>` | `sase_hg_sync`          |

The git sync auto-detects the default branch via `git symbolic-ref refs/remotes/origin/HEAD`, then probes
`origin/master` and `origin/main`, and finally falls back to `main`.

#### Mail (`m` key)

Pushes changes for review. The flow differs significantly between providers.

**Git flow:**

1. Display branch name and commit description
2. Prompt user to confirm push
3. `git push -u origin <branch>`
4. With the GitHub provider, check or create a PR through `gh`
5. Update ChangeSpec with the PR URL when the provider can return one

**Mercurial flow:**

1. Prompt for reviewers (1 or 2, or `@` to run `p4 findreviewers -c <pr_number>`)
2. Modify PR description with reviewer tags and startblock configuration
3. Reword PR description via `sase_hg_reword`
4. Prompt user to confirm mail
5. `hg mail -r <revision>`

#### Show Diff (`d` key)

Displays the diff for a ChangeSpec. Uses `diff()` for uncommitted changes or `diff_revision()` for committed revisions.

| Type        | Git                                              | Mercurial          |
| ----------- | ------------------------------------------------ | ------------------ |
| Uncommitted | `git diff HEAD`                                  | `hg diff`          |
| Revision    | `git diff origin/<default>...<rev>` (merge-base) | `hg diff -c <rev>` |

#### Revert (`X` key / status change to "Reverted")

Reverts a ChangeSpec by saving its diff and pruning the revision.

1. Save diff to `~/.sase/reverted/<name>.diff` via `diff_revision()`
2. Prune revision via `prune()`
3. Update status to "Reverted"

| Operation | Git                        | Mercurial                  |
| --------- | -------------------------- | -------------------------- |
| Prune     | `git branch -D <revision>` | `sase_hg_prune <revision>` |

#### Restore (status change from "Reverted" to "WIP"/"Drafted")

Restores a previously reverted ChangeSpec.

1. Checkout parent or default branch via `checkout()`
2. Apply stashed diff via `apply_patch()`
3. Run `sase commit` to re-create the commit

| Operation   | Git                     | Mercurial                      |
| ----------- | ----------------------- | ------------------------------ |
| Checkout    | `git checkout <target>` | `sase_hg_update <target>`      |
| Apply patch | `git apply <path>`      | `hg import --no-commit <path>` |

#### Archive (status change to "Archived")

Archives a ChangeSpec by saving the diff, archiving the revision, and updating status.

1. Checkout the PR via `checkout()`
2. Save diff to `~/.sase/archived/<name>.diff`
3. Archive revision via `archive()`

| Operation | Git                                                      | Mercurial                |
| --------- | -------------------------------------------------------- | ------------------------ |
| Archive   | `git tag archive/<name> <name>` + `git branch -D <name>` | `sase_hg_archive <name>` |

#### Reword (`w` key)

Amends the commit message without changing code.

| Operation | Git                                   | Mercurial                      |
| --------- | ------------------------------------- | ------------------------------ |
| Reword    | `git commit --amend -m <description>` | `sase_hg_reword <description>` |

The Mercurial provider applies ANSI-C escape quoting to the description (escaping backslashes, single quotes, newlines,
tabs, carriage returns) because `sase_hg_reword` uses `$'...'` shell quoting internally.

### `sase axe`

Background daemon that periodically checks ChangeSpecs and runs hooks. Uses VCS operations for:

- **Hook running** — Workspace checkout and sync before running hooks
- **Mentor checks** — Checking for changes via `has_local_changes()`
- **Workspace sync** — Periodic sync via `sync_workspace()`

The `--vcs-provider` flag works identically to `sase ace`.

### `sase revert`

Standalone command to revert a ChangeSpec. Performs the same operations as the ace TUI revert action:

1. Save diff via `diff_revision()` to `~/.sase/reverted/<name>.diff`
2. Prune revision via `prune()`
3. Update status to "Reverted"

### `sase restore`

Standalone command to restore a reverted ChangeSpec:

1. Checkout parent (or default branch) via `checkout()`
2. Apply saved diff via `apply_patch()` from `~/.sase/reverted/` or `~/.sase/archived/`
3. Run `sase commit` to re-create the commit

## Git Provider Details

Git support is split across providers. **BareGitPlugin** (bundled with core sase) handles standard `git` commands and
bare-repo-backed workflows. **GitHubPlugin** (from the optional `sase-github` package) adds GitHub CLI (`gh`) support
for PR operations and GitHub workspace references.

### Branch Naming

Git branch names match ChangeSpec names exactly — no prefix stripping or underscore-to-hyphen conversion. Two VCS hooks
control branch name derivation:

- `vcs_derive_branch_name()` — returns the base branch name (ChangeSpec name without `__<N>` suffix)
- `vcs_derive_branch_name_with_suffix()` — returns the full branch name including suffix

**Immutable branch aliases:** When a provider cannot rename branches (e.g., GitHub with open PRs), sase persists branch
aliases in `~/.sase/projects/<project>/branch_map.json`. This maps the current ChangeSpec name to the actual git branch
name. The `vcs_can_rename_branch()` hook tells the system whether renaming is possible — GitHub returns `False` for
branches with open PRs, so alias mappings are used instead of `git branch -m`.

### Branch Management

- Creates feature branches with `git checkout -b <name>` during commit
- Renames branches with `git branch -m <new_name>` (when `vcs_can_rename_branch()` returns `True`)
- Falls back to branch alias mapping when renaming is not possible
- Current branch detected via `git rev-parse --abbrev-ref HEAD`

### PR Integration

GitHub PR operations use the `gh` CLI:

- **Create PR**: `gh pr create --fill` (auto-fills title/body from commit)
- **View PR**: `gh pr view --json url -q .url`
- **Get PR number**: `gh pr view --json number -q .number`

The bundled bare-git provider does not create PRs. Its mail action pushes the resolved branch to `origin`.

### GitHub Plugin Scope

The GitHub plugin covers the core git/PR lifecycle by combining GitHub-specific hooks with the shared git provider
mixins. It can classify GitHub remotes, create and inspect PRs, preserve immutable branch aliases for open PRs, resolve
workspace references such as `#gh:<ref>`, and submit merged PRs through `gh pr merge`.

It does not currently provide the richer Mercurial-specific automation surface. In particular, GitHub PRs do not get
plugin-supplied default ChangeSpec hooks, metahooks, mentor profiles, PR tags, or a provider-specific
`commit_hooks.before` fix command unless users configure those in `sase.yml`. Reviewer-comment polling and
comment-response automation are not enabled for GitHub PR URLs, reviewer discovery during mail preparation is not
implemented, `vcs_rewind` has no GitHub backend, BUG values are left as provided, and Mercurial-only refresh/split
workflows do not have GitHub equivalents.

These are plugin capability gaps, not core VCS limitations: ordinary git operations, diffing, branch management,
commit/proposal/PR dispatch, conflict resume, and workspace setup are still provided by the shared git implementation.

### GitHub Enterprise

The `sase-github` plugin supports GitHub Enterprise Server and other self-hosted GitHub hosts. Authenticate the GitHub
CLI with `gh auth login --hostname <host>`, configure the host through `github_hosts`, and then use the normal
`#gh(owner/repo)` workflow. The plugin's
[GitHub Enterprise setup walkthrough](https://github.com/sase-org/sase-github/blob/master/docs/configuration.md#github-enterprise-setup)
is the source of truth for the ordered setup, including SSH clone configuration and workspace layout.

### Sync

```
git fetch origin
git rebase origin/<default_branch>
```

The default branch is auto-detected from `git symbolic-ref refs/remotes/origin/HEAD`, then `origin/master`, then
`origin/main`, and finally `main`.

### Archive

Preserves commits via a tag before deleting the branch:

```
git tag archive/<name> <name>
git branch -D <name>
```

### Diff

- **Uncommitted changes**: `git diff HEAD` (falls back to `git diff` for empty repos)
- **Specific revision**: `git diff origin/<default>...<rev>` (three-dot merge-base syntax, showing the full PR diff).
  Falls back to `git diff <rev>~1 <rev>` for edge cases (detached HEAD, orphan branches), then to `git show` for root
  commits.

### Workspace Info

- **Repository name**: Extracted from `git config --get remote.origin.url` (strips `.git` suffix), falls back to
  `git rev-parse --show-toplevel` basename
- **Local changes**: `git status --porcelain`
- **Commit description**: `git log --format=%B -n1 <revision>` (full) or `git log --format=%s -n1 <revision>` (short)

### Tag Operations

Adding tags to commit descriptions:

```
git log --format=%B -n1 HEAD    # Read current message
git commit --amend -m "<msg>\n<tag>=<value>"    # Append tag
```

## Mercurial Provider Details

Mercurial support is provided by external provider plugins. A Mercurial provider uses a combination of standard `hg`
commands and `sase_hg_*` wrapper commands.

### Core Commands

| Operation | Command                                             |
| --------- | --------------------------------------------------- |
| Commit    | `hg commit --name <name> --logfile <logfile>`       |
| Amend     | `sase_hg_amend [--no-upload] <note>`                |
| Checkout  | `sase_hg_update <revision>`                         |
| Sync      | `sase_hg_sync`                                      |
| Archive   | `sase_hg_archive <revision>`                        |
| Prune     | `sase_hg_prune <revision>`                          |
| Rename    | `sase_hg_rename <new_name>`                         |
| Rebase    | `sase_hg_rebase <branch> <new_parent>`              |
| Reword    | `sase_hg_reword <description>`                      |
| Add tag   | `sase_hg_reword --add-tag <name> <value>`           |
| Clean     | `sase_hg_clean <diff_name>` (saves diff and cleans) |

### Branch and Workspace Info

| Info           | Command                |
| -------------- | ---------------------- |
| Branch name    | `branch_name`          |
| PR number      | `branch_number`        |
| Bug number     | `sase_hg_branch_bug`   |
| Workspace name | `workspace_name`       |
| Local changes  | `branch_local_changes` |

### Description Management

| Operation         | Command                 |
| ----------------- | ----------------------- |
| Full description  | `cl_desc -r <revision>` |
| Short description | `cl_desc -s`            |

### Review Operations

| Operation       | Command                           |
| --------------- | --------------------------------- |
| Mail for review | `hg mail -r <revision>`           |
| Find reviewers  | `p4 findreviewers -c <pr_number>` |
| Upload          | `hg upload tree`                  |
| Fix             | `hg fix`                          |

### Diff and Patch

| Operation        | Command                        |
| ---------------- | ------------------------------ |
| Uncommitted diff | `hg diff`                      |
| Revision diff    | `hg diff -c <revision>`        |
| Apply patch      | `hg import --no-commit <path>` |
| Rewind           | `sase_hg_rewind <diff_paths>`  |

### Change URL

PR URLs follow the pattern `http://cl/<number>`, where the number comes from `branch_number`.

### Description Escaping

The `prepare_description_for_reword()` method escapes descriptions for `sase_hg_reword`'s `$'...'` shell quoting:

- `\` → `\\` (backslashes first)
- `'` → `\'`
- newline → `\n`
- tab → `\t`
- carriage return → `\r`

## Diff Management

Sase maintains diff files in `~/.sase/` for tracking changes across operations.

### Diff Storage Locations

| Directory                                         | Purpose                         | When Used                         |
| ------------------------------------------------- | ------------------------------- | --------------------------------- |
| `~/.sase/diffs/YYYYMM/<cl_name>-<timestamp>.diff` | Pre-commit/amend diff snapshots | Every commit and amend            |
| `~/.sase/reverted/<name>.diff`                    | Stashed diff for reverted PRs   | `sase revert` / ace revert action |
| `~/.sase/archived/<name>.diff`                    | Stashed diff for archived PRs   | ace archive action                |

### Patch Application

| Provider  | Apply Command                  |
| --------- | ------------------------------ |
| Git       | `git apply <path>`             |
| Mercurial | `hg import --no-commit <path>` |

Multiple patches can be applied at once — both providers accept multiple paths in a single command.

### Stash and Clean

The `stash_and_clean()` operation preserves local work before switching or cleaning a workspace:

| Provider  | Steps                                                                |
| --------- | -------------------------------------------------------------------- |
| Git       | `git status --porcelain` → `git stash push --include-untracked -m …` |
| Mercurial | `sase_hg_clean <diff_name>`                                          |

## Configuration Reference

### Full `sase.yml` Example

```yaml
# ~/.config/sase/sase.yml

vcs_provider:
  provider: auto # "git", "hg", or "auto" (default: "auto")
  pr_tags: {} # optional key-value tags appended to PR commit messages (rendered SASE_-prefixed, e.g. SASE_BUG=value)
  use_project_pr_prefix: false # prepend [<project>] to PR titles / PR descriptions
```

### Environment Variable

```bash
# Override VCS provider for a single command
SASE_VCS_PROVIDER=git sase commit my_feature

# Set for the entire shell session
export SASE_VCS_PROVIDER=hg
```

### CLI Flags

Available on `sase ace` and `sase axe` only:

```bash
sase ace --vcs-provider git
sase ace --vcs-provider hg
sase ace --vcs-provider auto

sase axe start --vcs-provider git
```

Valid values for all three methods: `git`, `hg`, `auto`.

### Schema

The `vcs_provider` section in `sase.yml` is validated against the installed config schema returned by
`sase path config-schema`:

```json
{
  "vcs_provider": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "provider": {
        "type": "string",
        "enum": ["git", "hg", "auto"],
        "default": "auto"
      },
      "workspace_root": {
        "type": "string"
      },
      "default_hooks": {
        "type": "array",
        "items": { "type": "string" }
      },
      "pr_tags": {
        "type": "object",
        "additionalProperties": { "type": "string" },
        "default": {}
      },
      "use_project_pr_prefix": {
        "type": "boolean",
        "default": false
      }
    }
  }
}
```

## Classification Hooks

VCS provider detection is pluggable via two classification hooks:

### `vcs_detect_repo_type`

Checks for VCS markers in a directory (e.g., `.hg/`, `.git/`). Each plugin checks for its own marker and returns the VCS
type name (e.g., `"hg"`) or `None`. Used during auto-detection when walking up the directory tree.

### `vcs_classify_repo`

For git repositories, further classifies by examining the remote URL. For example, the `sase-github` plugin claims repos
whose remote host is in the configured GitHub host set, returning `"github"` for `github.com` by default and for any
hosts listed in `github_hosts`. Unclaimed repos fall through to the `"bare_git"` provider. This allows hosting-specific
plugins to provide enhanced functionality (e.g., PR operations via `gh` CLI) without modifying the core.

## Troubleshooting

### "No VCS provider found" Error

**Cause:** Auto-detection could not find `.hg/` or `.git/` in the current directory or any parent, no explicit provider
was configured, or a Git repo could not be classified because no plugin claimed it and `origin` was missing or
unreadable.

**Fix:** Either run sase from within a VCS-managed directory, or set the provider explicitly:

```bash
SASE_VCS_PROVIDER=git sase commit my_feature
```

### GitHub: `gh` CLI Not Installed

GitHub PR operations (`get_change_url`, `mail`, `get_pr_number`) require the [GitHub CLI](https://cli.github.com/).
Without it, these operations will fail with a "command not found" error.

**Symptoms:**

- `sase commit` completes but reports "Failed to retrieve change URL"
- `sase ace` mail action fails with "gh pr create failed"
- No PR URL shown after commit

**Fix:** Install the GitHub CLI and authenticate:

```bash
# macOS
brew install gh

# Then authenticate
gh auth login

# GitHub Enterprise / self-hosted GitHub
gh auth login --hostname github.mycompany.com
```

### Mercurial: Plugin Not Installed

Mercurial support requires an installed provider plugin. Without one, hg repositories will not be detected.

**Symptoms:**

- Auto-detection does not recognize `.hg/` directories
- "No VCS provider found" error in hg repositories

**Fix:** Install the maintained Mercurial provider plugin for your environment.

### Mercurial: `sase_hg_*` Commands Not Found

The Mercurial provider depends on `sase_hg_*` wrapper commands. If these are not in your PATH, operations will fail.

**Symptoms:**

- "sase_hg_amend command not found"
- "sase_hg_sync command not found"
- Any core hg operation failing with "command not found"

**Fix:** Ensure your PATH includes the directory containing the `sase_hg_*` scripts.

### Auto-Detection Picks Wrong Provider in Nested Repos

If you have nested repositories (e.g., a git repo inside an hg workspace), auto-detection walks up from the current
directory and picks the **first** VCS directory it finds.

**Example:** If you're in `/workspace/git-repo/subdir/` and both `/workspace/.hg/` and `/workspace/git-repo/.git/`
exist, auto-detection will find `.git/` first and use the Git provider.

**Fix:** Override the provider explicitly:

```bash
# Force Mercurial for this session
export SASE_VCS_PROVIDER=hg

# Or use config file
# ~/.config/sase/sase.yml
vcs_provider:
  provider: hg
```
