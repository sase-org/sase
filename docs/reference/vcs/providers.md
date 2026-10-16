---
title: VCS providers
description: Look up provider selection, repository operations, and troubleshooting.
---

# VCS providers

This page describes provider selection and the Git and Mercurial behavior SASE exposes.

The **VCS provider layer** is an abstraction that lets sase commands work with both
**Git** and **Mercurial** repositories. Commands and workflows that touch version
control, including `sase stitch create`, `sase tui`, `sase axe`, `sase revert`, and
`sase restore`, delegate to a provider interface rather than calling VCS commands
directly.

Git and Mercurial share the same SASE concepts: Patches, workspace checkout, diff
capture, commit/proposal dispatch, review submission, revert, and restore.
Provider-specific capabilities and prerequisites still matter. For example, GitHub
pull-request operations require the optional `sase-github` plugin and the GitHub CLI,
while Mercurial support requires a maintained provider plugin that supplies `sase_hg_*`
helper commands.

## Provider Selection

Sase uses a 3-tier resolution strategy to decide which VCS provider to use. The first
tier that returns a concrete provider wins.

### Tier 1: Environment Variable

The `SASE_VCS_PROVIDER` environment variable takes highest priority.

```bash
# Force the Git provider family; GitHub remotes are reclassified when the plugin is installed.
SASE_VCS_PROVIDER=git sase stitch create -m "Update parser"

# Force hg provider
SASE_VCS_PROVIDER=hg sase tui

# Defer to next tier
SASE_VCS_PROVIDER=auto sase stitch create -m "Update parser"
```

The `-v, --vcs-provider` CLI flag on `sase tui` and `sase axe` sets this variable
internally for that process:

```bash
# Equivalent to SASE_VCS_PROVIDER=git sase tui
sase tui --vcs-provider git

# Same for an in-process axe run
sase axe --vcs-provider hg job run <name>
```

On `sase axe`, the flag belongs to the `axe` command itself and must come before the
subcommand. It takes effect for `sase axe job run` and `sase axe routine run`, which
execute in the CLI process. The `start|stop|restart|status` verbs only ask the service
host to act on the `scheduler` service proc, so a `-v` passed with them never reaches
the host-run scheduler. Pin the provider for the host-run scheduler in its proc
environment instead: `service.procs.scheduler.env` (for example,
`SASE_VCS_PROVIDER: hg`).

Valid values: `git`, `hg`, `auto`.

### Tier 2: Configuration File

If the environment variable is not set (or is unset entirely — not `"auto"`), sase
checks `~/.config/sase/sase.yml`:

```yaml
vcs_provider:
  provider: git # or "hg" or "auto"
```

Setting `provider: auto` defers to auto-detection (Tier 3).

**Note:** If the environment variable is set to `"auto"`, the config file is skipped
entirely and auto-detection runs directly. Only an unset environment variable consults
the config.

### Tier 3: Auto-Detection

If neither the environment variable nor config file specifies a provider, sase walks up
the directory tree from the current working directory looking for `.hg/` or `.git/`
directories. The first one found determines the provider.

- `.hg/` found first → Mercurial provider (`"hg"`)
- `.git/` found first → Git provider. If a plugin claims the Git remote, such as
  `sase-github` claiming a configured GitHub host, that provider name wins.
- `.git/` found with a hosted remote (e.g., GitHub) but no VCS plugin claims the repo →
  falls back to `"bare_git"`. This preserves baseline commit capability even without
  provider-specific plugins like `sase-github`.
- `.git/` found without a readable `origin` URL and no plugin claim → **Error**:
  `VCSProviderNotFoundError`
- Neither found → **Error**: `VCSProviderNotFoundError`

With the bundled and documented optional providers, `detect_vcs()` commonly returns
`"github"`, `"bare_git"`, or `"hg"`. Additional plugins may return their own provider
names. `detect_vcs_family()` collapses `"github"` and `"bare_git"` into `"git"` for
contexts that only care about the VCS family.

## Per-Command VCS Usage

### `sase stitch list`

Shows a day-grouped commit timeline across the primary repository and ordinary
configured linked repositories. Sidecar repositories are hidden by default. Pass the
compatibility option `--sdd` to include the complete sidecar set: modern
configured/default sidecars and any materialized legacy separate SDD repository. Pass
`--all` to build one timeline from every registered enabled or disabled project
(excluding the system-managed `home` project), regardless of the current directory.
Global discovery does not materialize missing workspaces. Sibling checkouts still appear
as linked repositories of their owning projects; `--all --sdd` also includes every
available sidecar from the registered projects. This CLI default is independent of the
sase's TUI Artifacts Stitches pane's configurable persistent query.

A bare `sase stitch` prints
`No subcommand provided for 'sase stitch'; delegating to 'sase stitch list'.` and then
the timeline. The legacy `sase vcs` spelling is still accepted as a deprecated alias and
uses the same default.

Global discovery canonicalizes checkout paths, so a repository registered independently
and linked from one or more projects is read and fetched only once. Registered project
display names take precedence; colliding linked-repo and sidecar labels are qualified
with their owning project. `--repo` narrows the eligible set after sidecar opt-in, so
use `--sdd --repo plans` to show only the current project's plans-sidecar history or
`--sdd --repo sdd` for a legacy SDD repo. A sidecar selected with `--repo` remains
unavailable without `--sdd`. Failures in one project or provider are warnings and do not
hide healthy repositories.

By default the command shows up to 40 commits and trailing SASE commit tags, refreshes a
supported remote ref when that checkout/ref has not been fetched successfully in the
last 60 seconds, and marks each commit as synced, unpushed, remote-only, or unknown when
no remote comparison is available. Providers without remote-log comparison still
contribute local history through the provider-neutral `log()` hook; a provider without
that hook produces an isolated warning.

When a cache miss or `--fetch` triggers remote I/O, stderr shows
`Fetching remote · <repo> ← <ref>` as a transient spinner in an interactive terminal or
a durable status line when redirected. Commit data remains isolated on stdout, so JSON
and oneline output stay safe to pipe.

The short author option moved from `-a` to `-A` because `-a` now selects all-project
scope. Existing scripts can migrate to `-A PATTERN`; the long `--author PATTERN`
spelling is unchanged.

Common forms:

```bash
sase stitch list
sase stitch list --all
sase stitch list --sdd
sase stitch list --sdd --repo sdd
sase stitch list --all --sdd
sase stitch list --all --repo sase-core --repo chezmoi
sase stitch list --branch main --no-fetch
sase stitch list --merges show
sase stitch list --origin stitch --origin manual
sase stitch list --merges only --format full
sase stitch list --fetch --limit 3
sase stitch list --since 2w --author bryan
sase stitch list --limit 0 --since 2026-07-01 --format full
sase stitch list --reverse --format json --no-tags
```

Options:

See the generated [stitch CLI reference](../cli/stitch.md) for the full option list.

`--all` and `--current-only` are mutually exclusive. `--current-only` reads only the
current/primary repo even when `--sdd` is supplied. `--repo` remains repeatable in
global scope and is applied after sidecar scope selection, canonical-path deduplication,
and unique label assignment. The `--limit` cap applies to the final merged timeline, not
to each project's inventory: each unique candidate repository is queried deeply enough
to compute the global top N. Use `--limit 0` for an unlimited merged timeline. JSON
output records the selected global scope as `query.all`.

Merge visibility is deliberately named after the SASE view, not after Git traversal
flags. `--merges hide` maps to Git's `--no-merges`: merge commits are omitted while
history is still traversed through those merges, so commits contained in a merged pull
request remain visible. `--merges show` applies no Git merge filter and marks visible
merge commits in the output. `--merges only` maps to Git's `--merges` and shows merge
commits alone, without adding `--first-parent`; for the same repo, revision, and other
filters, `hide` plus `only` partitions the same commit set shown by `show`.

When merge commits are visible (`show` or `only`), `pretty`/`timeline`/`oneline` output
prefixes each merge commit's subject with a `◆` glyph, and a `◆ merge` legend entry is
added to the output whenever any shown commit is a merge. A recognized GitHub PR merge
condenses its subject to `#<PR-number>  <headline>` instead of the raw merge-commit
subject, so the PR's actual change summary is what you see rather than the generic
"Merge pull request #N from ..." text. `--format full` additionally prints a
`parents  <id1>  <id2>` line under each merge commit, listing both parent revisions.

`DATE` accepts relative offsets (`Nh`, `Nd`, `Nw`), `today`, `yesterday`, `YYYY-MM-DD`,
or `YYYY-MM-DDTHH:MM`. Dates are resolved in the configured SASE timezone and pushed
into the provider query before the limit is applied, so filtered top-N results do not
silently miss matching commits.

Origin filtering is applied after commit collection and before the final visible cap,
because commit origin is classified from the parsed SASE footer instead of pushed down
to the VCS provider. `stitch` means the commit was created through `sase stitch create`,
`auto` means another SASE command created it, and `manual` means the commit has no SASE
provenance footer. Pretty output shows the fixed origin glyph column (`✦`, `↻`, or `✎`)
and an adaptive legend; `--format full` includes the marker in each commit header,
`--format oneline` includes a compact origin token, and `--format json` includes an
`"origin"` string on every commit.

### `sase stitch create`

Dispatches to one of three VCS methods (`create_commit`, `create_proposal`,
`create_pull_request`) via the `CommitWorkflow` orchestrator. See
[Commit workflows](commit-workflows.md) for the full workflow reference.

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
sase stitch create -m "Update parser"                         # create_commit
sase stitch create -t propose -m "Try parser cleanup"         # create_proposal
sase stitch create -t pr -n parser_cleanup -m "Update parser" # create_pull_request
```

### `sase tui` Actions

sase's TUI provides interactive actions that use VCS operations:

#### Sync (`Y` key)

Syncs the workspace with the remote repository.

| Step     | Git                                                       | Mercurial               |
| -------- | --------------------------------------------------------- | ----------------------- |
| Checkout | `git checkout <name>`                                     | `sase_hg_update <name>` |
| Sync     | `git fetch origin` + `git rebase origin/<default_branch>` | `sase_hg_sync`          |

The git sync auto-detects the default branch via
`git symbolic-ref refs/remotes/origin/HEAD`, then probes `origin/master` and
`origin/main`, and finally falls back to `main`.

#### Mail (`M` key)

Pushes changes for review. The flow differs significantly between providers.

**Git flow:**

1. Display branch name and commit description
2. Prompt user to confirm push
3. `git push -u origin <branch>`
4. With the GitHub provider, check or create a PR through `gh`
5. Update Patch with the PR URL when the provider can return one

**Mercurial flow:**

1. Prompt for reviewers (1 or 2, or `@` to run `p4 findreviewers -c <pr_number>`)
2. Modify PR description with reviewer tags and startblock configuration
3. Reword PR description via `sase_hg_reword`
4. Prompt user to confirm mail
5. `hg mail -r <revision>`

#### Show Diff (`d` key)

Displays the diff for a Patch. Uses `diff()` for uncommitted changes or
`diff_revision()` for committed revisions.

| Type        | Git                                              | Mercurial          |
| ----------- | ------------------------------------------------ | ------------------ |
| Uncommitted | `git diff HEAD`                                  | `hg diff`          |
| Revision    | `git diff origin/<default>...<rev>` (merge-base) | `hg diff -c <rev>` |

#### Revert (status change to "Reverted")

Reverts a Patch by saving its diff and pruning the revision. Choose "Reverted" from the
status change action (`s`); the revert runs as a background proc. (`X` only shows or
hides reverted Patches in the list.)

1. Refuse when another Patch uses this one as its parent
2. Choose the next free `__<N>` suffix for the restored Patch name
3. Save the diff to `~/.sase/reverted/<new_name>.diff` via `diff_revision()`
4. Close the remote change via `abandon_change()`, then prune the revision via `prune()`
   and drop any branch alias
5. Rename the Patch, update its status to "Reverted", and clear its PR field

Steps 3 and 4 run only when the Patch has a PR.

| Operation | Git                        | Mercurial                  |
| --------- | -------------------------- | -------------------------- |
| Prune     | `git branch -D <revision>` | `sase_hg_prune <revision>` |

#### Restore (status change from "Reverted" to "WIP", "Draft", or "Ready")

Attempts to restore a reverted Patch as a background proc.

1. Rename the Patch back to its base name (dropping the `__<N>` suffix)
2. Checkout parent or default branch via `checkout()`
3. Apply the stashed diff via `apply_patch()`
4. Attempt to run `sase stitch create` to re-create the commit

| Operation   | Git                     | Mercurial                      |
| ----------- | ----------------------- | ------------------------------ |
| Checkout    | `git checkout <target>` | `sase_hg_update <target>`      |
| Apply patch | `git apply <path>`      | `hg import --no-commit <path>` |

**Current limitation:** the final step invokes `sase stitch create <base-name> -B keep`,
but `sase stitch create` accepts no positional Patch name. It therefore exits with a
usage error after the Patch rename, hook-status reset, checkout, and diff application
have already happened. The operation does not roll those steps back. Inspect the
resulting workspace and applied changes, then finish manually with a valid command such
as `sase stitch create -m '<conventional commit message>' -B keep`; do not assume that a
reported restore failure left the workspace untouched.

#### Archive (status change to "Archived")

Archives a Patch by saving the diff, archiving the revision, and updating status.

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

The Mercurial provider applies ANSI-C escape quoting to the description (escaping
backslashes, single quotes, newlines, tabs, carriage returns) because `sase_hg_reword`
uses `$'...'` shell quoting internally.

### `sase axe`

Background daemon that periodically checks Patches and runs hooks. Uses VCS operations
for:

- **Hook running** — Workspace checkout and sync before running hooks
- **Mentor checks** — Checking for changes via `has_local_changes()`
- **Workspace sync** — Periodic sync via `sync_workspace()`

The `--vcs-provider` flag works identically to `sase tui`.

### `sase revert`

Standalone command to revert a Patch. Performs the same operations as the revert action
in sase's TUI:

1. Save diff via `diff_revision()` to `~/.sase/reverted/<new_name>.diff`
2. Close the remote change and prune the revision via `prune()`
3. Rename the Patch with its `__<N>` suffix and update status to "Reverted"

```bash
sase revert my_feature
```

### `sase restore`

Standalone command that attempts to restore a reverted Patch. `sase restore -l`
(`--list`) lists the reverted Patches you can name.

1. Rename the Patch back to its base name
2. Checkout parent (or default branch) via `checkout()`
3. Apply saved diff via `apply_patch()` from `~/.sase/reverted/` or `~/.sase/archived/`
4. Attempt to run `sase stitch create` to re-create the commit; the current invocation
   fails as described in the
   [restore limitation above](#restore-status-change-from-reverted-to-wip-draft-or-ready)

```bash
sase restore --list
sase restore my_feature__2
```

## Git Provider Details

Git support is split across providers. **BareGitPlugin** (bundled with core sase)
handles standard `git` commands and bare-repo-backed workflows. **GitHubPlugin** (from
the optional `sase-github` package) adds GitHub CLI (`gh`) support for PR operations and
GitHub workspace references.

### Branch Naming

Git branch names match Patch names exactly — no prefix stripping or underscore-to-hyphen
conversion. Two VCS hooks control branch name derivation:

- `vcs_derive_branch_name()` — returns the base branch name (Patch name without `__<N>`
  suffix)
- `vcs_derive_branch_name_with_suffix()` — returns the full branch name including suffix

**Immutable branch aliases:** When a provider cannot rename branches (e.g., GitHub with
open PRs), sase persists branch aliases in `~/.sase/projects/<project>/branch_map.json`.
This maps the current Patch name to the actual git branch name. The
`vcs_can_rename_branch()` hook tells the system whether renaming is possible — GitHub
returns `False` for branches with open PRs, so alias mappings are used instead of
`git branch -m`.

### Branch Management

- Creates feature branches with `git checkout -b <name>` during commit
- Renames branches with `git branch -m <new_name>` (when `vcs_can_rename_branch()`
  returns `True`)
- Falls back to branch alias mapping when renaming is not possible
- Current branch detected via `git rev-parse --abbrev-ref HEAD`

### PR Integration

GitHub PR operations use the `gh` CLI:

- **Create PR**: `gh pr create --fill` (auto-fills title/body from commit)
- **View PR**: `gh pr view --json url -q .url`
- **Get PR number**: `gh pr view --json number -q .number`

The bundled bare-git provider does not create PRs. Its mail action pushes the resolved
branch to `origin`.

### GitHub Plugin Scope

The GitHub plugin covers the core git/PR lifecycle by combining GitHub-specific hooks
with the shared git provider mixins. It can classify GitHub remotes, create and inspect
PRs, preserve immutable branch aliases for open PRs, resolve workspace references such
as `#gh:<ref>`, and submit merged PRs through `gh pr merge`.

It does not currently provide the richer Mercurial-specific automation surface. In
particular, GitHub PRs do not get plugin-supplied default Patch hooks, metahooks, mentor
profiles, PR tags, or a provider-specific `commit_hooks.before` fix command unless users
configure those in `sase.yml`. Reviewer-comment polling and comment-response automation
are not enabled for GitHub PR URLs, reviewer discovery during mail preparation is not
implemented, `vcs_rewind` has no GitHub backend, BUG values are left as provided, and
Mercurial-only refresh/split workflows do not have GitHub equivalents.

These are plugin capability gaps, not core VCS limitations: ordinary git operations,
diffing, branch management, commit/proposal/PR dispatch, conflict resume, and workspace
setup are still provided by the shared git implementation.

### GitHub Enterprise

The `sase-github` plugin supports GitHub Enterprise Server and other self-hosted GitHub
hosts. Authenticate the GitHub CLI with `gh auth login --hostname <host>`, configure the
host through `github_hosts`, and then use the normal `#gh(owner/repo)` workflow. The
plugin's
[GitHub Enterprise setup walkthrough](https://github.com/sase-org/sase-github/blob/master/docs/configuration.md#github-enterprise-setup)
is the source of truth for the ordered setup, including SSH clone configuration and
workspace layout.

### GitHub CLI Calls

Core SASE code that shells out to `gh` goes through one shared, non-interactive runner.
Each attempt runs with `GH_PROMPT_DISABLED=1`, Git terminal and askpass prompts
disabled, and stdin closed, so a missing login fails instead of waiting for input. Every
attempt is also appended as a `gh_operation` record to `~/.sase/logs/tui_git_ops.jsonl`
(or `$SASE_TUI_GIT_OPS_PATH`).

A failed call is retried only when the Rust core classifies its exit status and output
as transient, such as a rate-limit response; a timeout counts as transient. Permanent
errors such as `Not Found (HTTP 404)` or `Bad credentials (HTTP 401)` fail on the first
attempt. A retrying caller makes at most three attempts, waiting 1 second and then 2
seconds between them. When the classifier, or a `Retry-After` or `X-RateLimit-Reset`
value in the `gh` output, supplies a delay, SASE waits that long instead, capped by
`SASE_GH_MAX_RETRY_SLEEP` (default: 60 seconds). `SASE_GH_TIMEOUT` (default: 20 seconds)
sets the per-attempt timeout only for callers that do not pass their own.

When retries run out, the error names the `gh` command, the attempt count, and the exit
status or timeout, followed by the first line of `gh` output. If the `gh` binary cannot
be started, the call fails at once without retrying.

The TUI's incoming-commit previews for SASE and plugin updates use the full retry
budget. The plugin catalog fetch behind `sase plugin` and the GitHub auth probe in
`sase doctor -C plugins.github` make a single attempt. PR operations come from the
`sase-github` plugin, whose documentation owns their retry behavior.

### Sync

```
git fetch origin
git rebase origin/<default_branch>
```

The default branch is auto-detected from `git symbolic-ref refs/remotes/origin/HEAD`,
then `origin/master`, then `origin/main`, and finally `main`.

### Archive

Preserves commits via a tag before deleting the branch:

```
git tag archive/<name> <name>
git branch -D <name>
```

### Diff

- **Uncommitted changes**: `git diff HEAD` (falls back to `git diff` for empty repos)
- **Specific revision**: `git diff origin/<default>...<rev>` (three-dot merge-base
  syntax, showing the full PR diff). Falls back to `git diff <rev>~1 <rev>` for edge
  cases (detached HEAD, orphan branches), then to `git show` for root commits.

### Workspace Info

- **Repository name**: Extracted from `git config --get remote.origin.url` (strips
  `.git` suffix), falls back to `git rev-parse --show-toplevel` basename
- **Local changes**: `git status --porcelain`
- **Commit description**: `git log --format=%B -n1 <revision>` (full) or
  `git log --format=%s -n1 <revision>` (short)

### Tag Operations

Adding tags to commit descriptions:

```
git log --format=%B -n1 HEAD    # Read current message
git commit --amend -m "<msg>\n<tag>=<value>"    # Append tag
```

## Mercurial Provider Details

Mercurial support is provided by external provider plugins. A Mercurial provider uses a
combination of standard `hg` commands and `sase_hg_*` wrapper commands.

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

PR URLs follow the pattern `http://cl/<number>`, where the number comes from
`branch_number`.

### Description Escaping

The `prepare_description_for_reword()` method escapes descriptions for
`sase_hg_reword`'s `$'...'` shell quoting:

- `\` → `\\` (backslashes first)
- `'` → `\'`
- newline → `\n`
- tab → `\t`
- carriage return → `\r`

## Diff Management

Sase maintains diff files in `~/.sase/` for tracking changes across operations.

### Diff Storage Locations

| Directory                                         | Purpose                         | When Used                             |
| ------------------------------------------------- | ------------------------------- | ------------------------------------- |
| `~/.sase/diffs/YYYYMM/<cl_name>-<timestamp>.diff` | Pre-commit/amend diff snapshots | Every commit and amend                |
| `~/.sase/reverted/<name>.diff`                    | Stashed diff for reverted PRs   | `sase revert` / TUI status → Reverted |
| `~/.sase/archived/<name>.diff`                    | Stashed diff for archived PRs   | TUI status → Archived                 |

### Patch Application

| Provider  | Apply Command                  |
| --------- | ------------------------------ |
| Git       | `git apply <path>`             |
| Mercurial | `hg import --no-commit <path>` |

Multiple patches can be applied at once — both providers accept multiple paths in a
single command.

### Stash and Clean

The `stash_and_clean()` operation preserves local work before switching or cleaning a
workspace:

| Provider  | Steps                                                                |
| --------- | -------------------------------------------------------------------- |
| Git       | `git status --porcelain` → `git stash push --include-untracked -m …` |
| Mercurial | `sase_hg_clean <diff_name>`                                          |

## Configuration Reference

<a id="full-saseyml-example"></a> <a id="schema"></a>

The generated [configuration reference](../config/repositories.md#vcs_provider) lists
the `vcs_provider` keys and defaults.

<a id="environment-variable"></a>

The [environment-variable reference](../environment-variables.md#vcs-provider) covers
`SASE_VCS_PROVIDER`.

<a id="cli-flags"></a>

Generated [TUI](../cli/tui.md) and [axe](../cli/axe.md) references list the provider
flag and its options.

For example, set the environment variable to choose a provider for one command:

```bash
SASE_VCS_PROVIDER=git sase stitch create -m "Update parser"
```

## Troubleshooting

### Git `index.lock` Contention

SASE routes Git mutations used by commits, workspace setup, operational workspace leases
(lease preparation and reset/replay recovery of leased checkouts), SDD writes, linked
repositories, agent reverts, CLI updates, and TUI editable updates through one bounded
lock-recovery policy owned by `sase-core`. The TUI reporter's dev-update runner uses
that same policy; a running editable TUI must be restarted to load a landed fix, because
advancing its checkout does not replace already-imported Python code.

On an `index.lock` failure SASE retries with a short six-step backoff
(`0.1, 0.2, 0.4, 0.8, 1.6, 3.2` seconds, overridable by `SASE_GIT_LOCK_RETRY_DELAYS` /
`SASE_SDD_GIT_LOCK_RETRY_DELAYS`). Removal requires an unchanged regular lock file at
least 15 seconds old, exhausted retries, and affirmative evidence that no relevant owner
is active. A younger owner-free lock may wait until that age inside a 30-second recovery
budget (or a shorter command deadline). A live owner, an unknown/incomplete owner probe,
a symlink or directory leaf, a changed path or file identity, unsupported
`GIT_DIR`/`GIT_INDEX_FILE` context, or a mismatched error path preserves the lock. Other
`.lock` types may retry; they are never deleted. Read-only Git commands do not need this
policy.

This is conservative recovery, not a proof of exclusive ownership: an external Git
writer can still race the unlink. SASE rechecks identity and owner immediately before
unlinking and removes a lock at most once.

If a mutation still reports `index.lock`, first check for another Git process operating
on that repository and let it finish. Avoid deleting `.git/index.lock` blindly:
worktrees can store the real Git directory elsewhere, and a changing or owned lock
belongs to active work. After confirming no Git process is live, rerun the SASE
operation; its recovery logic will resolve the canonical lock path and remove only an
unchanged stale owner-free file.

### Numbered Workspace Reports a Broken Git Object Dependency

Numbered managed Git checkouts borrow the primary checkout's object database through Git
alternates by default (`workspace.share_git_objects: true`). If the primary checkout is
moved or deleted, Git commands in a borrower can fail with missing-object errors, and
workspace preparation refuses to reuse that checkout with
`existing managed checkout has a broken SASE Git object dependency`. The checkout and
any uncommitted work are left in place.

**Fix:** Preview the repair with `sase workspace repair -n`, then run
`sase workspace repair` to repoint SASE-owned alternates at the current primary. Add
`-p <project>` when the project cannot be inferred from the current directory. See the
[`sase workspace` CLI](../agents/workspaces.md#sase-workspace-cli) for object sharing,
compaction, and the opt-out.

### Slow or Flaky Sidecar Git Transport

Network Git commands for SDD sidecar repositories (clone, fetch, and push during bead
sync, SDD integration, repository health checks, and agent publishing) retry failures
that the Rust core classifies as transient; see
[Network Git Operations](../../contribute/sdd-storage.md#network-git-operations) for
attempts, timeouts, and the environment variables that tune them. Those operations are
logged to `~/.sase/logs/tui_git_ops.jsonl`, and
`sase doctor -C vcs.git_transport_margin` reads the most recent samples and warns when
they keep running close to their time limit. Run it with `-v` to see which sidecar
stores were slow.

### "No VCS provider found" Error

**Cause:** Auto-detection could not find `.hg/` or `.git/` in the current directory or
any parent, no explicit provider was configured, or a Git repo could not be classified
because no plugin claimed it and `origin` was missing or unreadable.

**Fix:** Either run sase from within a VCS-managed directory, or set the provider
explicitly:

```bash
SASE_VCS_PROVIDER=git sase stitch create -m "Update parser"
```

### GitHub: `gh` CLI Not Installed

GitHub PR operations (`get_change_url`, `mail`, `get_pr_number`) require the
[GitHub CLI](https://cli.github.com/). Without it, these operations will fail with a
"command not found" error.

**Symptoms:**

- `sase stitch create` completes but reports "Failed to retrieve change URL"
- `sase tui` mail action fails with "gh pr create failed"
- No PR URL shown after commit

**Fix:** Install the GitHub CLI and authenticate, then run
`sase doctor -C plugins.github` to confirm that `gh` is on `PATH` and `gh auth status`
passes:

```bash
# macOS
brew install gh

# Then authenticate
gh auth login

# GitHub Enterprise / self-hosted GitHub
gh auth login --hostname github.mycompany.com
```

### GitHub: Transient `gh` Failures

**Symptoms:** A `gh`-backed step, such as an incoming-commit preview on the Updates
surfaces, reports `` `gh api -X GET ...` failed after 3 attempts (exit 1): ... `` or
`` `gh ...` timed out after 3 attempts ``.

**Cause:** Every attempt hit a failure the classifier treats as transient, such as a
rate limit, or every attempt timed out. Permanent failures stop after one attempt. See
[GitHub CLI Calls](#github-cli-calls).

**Fix:** Inspect the `gh_operation` records in `~/.sase/logs/tui_git_ops.jsonl`; each
record includes the attempt number, classifier verdict, and output previews. Confirm
that `gh auth status` passes, then retry once the GitHub outage or rate-limit window has
passed. Raise `SASE_GH_MAX_RETRY_SLEEP` only if longer waits between attempts are
acceptable.

### Mercurial: Plugin Not Installed

Mercurial support requires an installed provider plugin. Without one, hg repositories
will not be detected.

**Symptoms:**

- Auto-detection does not recognize `.hg/` directories
- "No VCS provider found" error in hg repositories

**Fix:** Install the maintained Mercurial provider plugin for your environment.

<a id="mercurial-sasehg-commands-not-found"></a>

### Mercurial: `sase_hg_*` Commands Not Found

The Mercurial provider depends on `sase_hg_*` wrapper commands. If these are not in your
PATH, operations will fail.

**Symptoms:**

- "sase_hg_amend command not found"
- "sase_hg_sync command not found"
- Any core hg operation failing with "command not found"

**Fix:** Ensure your PATH includes the directory containing the `sase_hg_*` scripts.

### Auto-Detection Picks Wrong Provider in Nested Repos

If you have nested repositories (e.g., a git repo inside an hg workspace),
auto-detection walks up from the current directory and picks the **first** VCS directory
it finds.

**Example:** If you're in `/workspace/git-repo/subdir/` and both `/workspace/.hg/` and
`/workspace/git-repo/.git/` exist, auto-detection will find `.git/` first and use the
Git provider.

**Fix:** Override the provider explicitly:

```bash
# Force Mercurial for this session
export SASE_VCS_PROVIDER=hg

# Or use config file
# ~/.config/sase/sase.yml
vcs_provider:
  provider: hg
```

## Related

- [Version control](index.md) — the section hub.
