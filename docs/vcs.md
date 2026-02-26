# VCS Provider Reference

The **VCS provider layer** is an abstraction that lets sase commands work transparently with both **Git** and
**Mercurial** repositories. Every command that touches version control — `commit`, `amend`, `ace`, `axe`, `revert`,
`restore` — delegates to a provider interface rather than calling VCS commands directly.

Both Git and Mercurial are first-class supported. The same sase workflows (creating commits, amending, syncing,
mailing/pushing for review, reverting, restoring) work identically regardless of which VCS backs the repository.

## Plugin Architecture

VCS providers are implemented as [pluggy](https://pluggy.readthedocs.io/) plugins. The core `sase` package only bundles
the **BareGitPlugin** (for plain git repositories). Additional VCS backends are installed as separate packages:

| Package       | Plugin          | Description                                |
| ------------- | --------------- | ------------------------------------------ |
| `sase` (core) | `BareGitPlugin` | Standard git operations (bundled)          |
| `sase-github` | `GitHubPlugin`  | Git + GitHub CLI (`gh`) for PR operations  |
| `sase-hg`     | `HgPlugin`      | Mercurial with `sase_hg_*` helper commands |

Install optional providers via pip:

```bash
pip install sase-github   # GitHub PR support
pip install sase-hg       # Mercurial support
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
- **Optional core** — `vcs_resolve_revision`, `vcs_show_revision`, `vcs_diff_with_untracked`, `vcs_committed_diff`,
  `vcs_get_default_parent_revision`
- **Sync operations** — `vcs_sync_workspace`, `vcs_is_sync_in_progress`, `vcs_get_conflicted_files`,
  `vcs_continue_sync`, `vcs_abort_sync`
- **Classification hooks** — `vcs_detect_repo_type` (detect VCS markers like `.hg/` or `.git/`) and `vcs_classify_repo`
  (classify git repos by remote URL, e.g. GitHub vs bare)
- **Info and review hooks** — `vcs_reword`, `vcs_get_description`, `vcs_get_branch_name`, `vcs_get_cl_number`,
  `vcs_get_workspace_name`, `vcs_has_local_changes`, `vcs_get_bug_number`, `vcs_mail`, `vcs_fix`, `vcs_upload`,
  `vcs_find_reviewers`, `vcs_rewind`, `vcs_get_change_url`

### Disabling Plugins

Set `SASE_DISABLE_PLUGINS` to disable all plugin groups, or `SASE_DISABLE_PLUGIN_VCS` to disable VCS plugins
specifically. See [docs/configuration.md](configuration.md#plugin-system) for details.

## Provider Selection

Sase uses a 3-tier resolution strategy to decide which VCS provider to use. The first tier that returns a concrete
provider wins.

### Tier 1: Environment Variable

The `SASE_VCS_PROVIDER` environment variable takes highest priority.

```bash
# Force git provider
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
- `.git/` found first → Git provider. If a GitHub remote is detected, uses `"github"` (requires `sase-github` plugin);
  otherwise uses `"bare_git"`.
- Neither found → **Error**: `VCSProviderNotFoundError`

The `detect_vcs()` function returns one of three values: `"github"`, `"bare_git"`, or `"hg"`. A convenience function
`detect_vcs_family()` collapses `"github"` and `"bare_git"` into `"git"` for contexts that only care about the VCS
family.

## Per-Command VCS Usage

### `sase commit`

Creates a new commit with formatted CL description and metadata tracking.

**VCS operations performed:**

1. **Get bug number** — `get_bug_number()` to populate the BUG= tag
2. **Get workspace name** — `get_workspace_name()` to determine the project prefix
3. **Save diff** — `diff()` + `add_remove()` to capture the pre-commit diff
4. **Checkout parent** — `checkout(parent_branch)` to handle rebasing onto the correct parent
5. **Create commit** — `commit(name, logfile)` to create the actual commit
6. **Run fixes** — `fix()` to run automatic code fixes
7. **Upload** — `upload()` to upload the change for review
8. **Get change URL** — `get_change_url()` to retrieve the CL/PR URL
9. **Rename branch** — `rename_branch(suffixed_name)` if a naming suffix was added

| Operation      | Git                                                       | Mercurial                                         |
| -------------- | --------------------------------------------------------- | ------------------------------------------------- |
| Bug number     | Returns empty string (not applicable)                     | `sase_hg_branch_bug` command                      |
| Workspace name | `git config --get remote.origin.url` (extracts repo name) | `workspace_name` command                          |
| Create commit  | `git checkout -b <name>` + `git commit -F <logfile>`      | `hg commit --name "<name>" --logfile "<logfile>"` |
| Fix            | No-op (returns success)                                   | `hg fix`                                          |
| Upload         | No-op (returns success)                                   | `hg upload tree`                                  |
| Change URL     | `gh pr view --json url -q .url`                           | `http://cl/<branch_number>`                       |
| Rename branch  | `git branch -m <new_name>`                                | `sase_hg_rename <new_name>`                       |

### `sase amend`

Amends the current commit with COMMITS tracking. Has a **propose mode** that saves changes without amending.

**VCS operations performed:**

1. **Get branch name** — `get_branch_name()` to determine the current CL
2. **Save diff** — captures uncommitted changes before amending
3. **Amend commit** — `amend(note)` to amend the current revision
4. In **propose mode**: `clean_workspace()` instead of amending

| Operation       | Git                                       | Mercurial                            |
| --------------- | ----------------------------------------- | ------------------------------------ |
| Amend           | `git commit --amend -m <note>`            | `sase_hg_amend [--no-upload] <note>` |
| Clean workspace | `git reset --hard HEAD` + `git clean -fd` | `hg update --clean .` + `hg clean`   |

### `sase ace` TUI Actions

The ace TUI provides interactive actions that use VCS operations:

#### Sync (`S` key)

Syncs the workspace with the remote repository.

| Step     | Git                                                       | Mercurial               |
| -------- | --------------------------------------------------------- | ----------------------- |
| Checkout | `git checkout <name>`                                     | `sase_hg_update <name>` |
| Sync     | `git fetch origin` + `git rebase origin/<default_branch>` | `sase_hg_sync`          |

The git sync auto-detects the default branch (main/master) via `git symbolic-ref refs/remotes/origin/HEAD`.

#### Mail (`m` key)

Pushes changes for review. The flow differs significantly between providers.

**Git flow:**

1. Display branch name and commit description
2. Prompt user to confirm push
3. `git push -u origin <branch>`
4. Check if PR exists via `gh pr view`
5. If no PR: `gh pr create --fill`
6. Update ChangeSpec with PR URL

**Mercurial flow:**

1. Prompt for reviewers (1 or 2, or `@` to run `p4 findreviewers -c <cl_number>`)
2. Modify CL description with reviewer tags and startblock configuration
3. Reword CL description via `sase_hg_reword`
4. Prompt user to confirm mail
5. `hg mail -r <revision>`

#### Show Diff (`d` key)

Displays the diff for a ChangeSpec. Uses `diff()` for uncommitted changes or `diff_revision()` for committed revisions.

| Type        | Git                      | Mercurial          |
| ----------- | ------------------------ | ------------------ |
| Uncommitted | `git diff HEAD`          | `hg diff`          |
| Revision    | `git diff <rev>~1 <rev>` | `hg diff -c <rev>` |

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

1. Checkout the CL via `checkout()`
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

The Git provider is split into two plugins: **BareGitPlugin** (bundled with core sase) handles standard `git` commands,
while **GitHubPlugin** (from the `sase-github` package) adds **GitHub CLI (`gh`)** support for PR operations.

### Branch Management

- Creates feature branches with `git checkout -b <name>` during commit
- Renames branches with `git branch -m <new_name>`
- Current branch detected via `git rev-parse --abbrev-ref HEAD`

### PR Integration

All PR operations use the `gh` CLI:

- **Create PR**: `gh pr create --fill` (auto-fills title/body from commit)
- **View PR**: `gh pr view --json url -q .url`
- **Get PR number**: `gh pr view --json number -q .number`

### Sync

```
git fetch origin
git rebase origin/<default_branch>
```

The default branch is auto-detected from `git symbolic-ref refs/remotes/origin/HEAD`, falling back to `main`.

### Archive

Preserves commits via a tag before deleting the branch:

```
git tag archive/<name> <name>
git branch -D <name>
```

### Diff

- **Uncommitted changes**: `git diff HEAD` (falls back to `git diff` for empty repos)
- **Specific revision**: `git diff <rev>~1 <rev>` (falls back to `git show` for root commits)

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

The Mercurial provider is available via the `sase-hg` package (`pip install sase-hg`). It uses a combination of standard
`hg` commands and `sase_hg_*` wrapper commands.

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
| CL number      | `branch_number`        |
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
| Find reviewers  | `p4 findreviewers -c <cl_number>` |
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

CL URLs follow the pattern `http://cl/<number>`, where the number comes from `branch_number`.

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

| Directory                                  | Purpose                         | When Used                         |
| ------------------------------------------ | ------------------------------- | --------------------------------- |
| `~/.sase/diffs/<cl_name>-<timestamp>.diff` | Pre-commit/amend diff snapshots | Every commit and amend            |
| `~/.sase/reverted/<name>.diff`             | Stashed diff for reverted CLs   | `sase revert` / ace revert action |
| `~/.sase/archived/<name>.diff`             | Stashed diff for archived CLs   | ace archive action                |

### Patch Application

| Provider  | Apply Command                  |
| --------- | ------------------------------ |
| Git       | `git apply <path>`             |
| Mercurial | `hg import --no-commit <path>` |

Multiple patches can be applied at once — both providers accept multiple paths in a single command.

### Stash and Clean

The `stash_and_clean()` operation saves the current diff to a file and resets the workspace:

| Provider  | Steps                                                                       |
| --------- | --------------------------------------------------------------------------- |
| Git       | `git diff HEAD` → write to file → `git reset --hard HEAD` → `git clean -fd` |
| Mercurial | `sase_hg_clean <diff_name>` (handles both steps internally)                 |

## Configuration Reference

### Full `sase.yml` Example

```yaml
# ~/.config/sase/sase.yml

vcs_provider:
  provider: auto # "git", "hg", or "auto" (default: "auto")
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

The `vcs_provider` section in `sase.yml` is validated against the schema at `~/.config/sase/sase.schema.json`:

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
with `github.com` URLs (returning `"github"`), while unclaimed repos fall through to the `"bare_git"` provider. This
allows hosting-specific plugins to provide enhanced functionality (e.g., PR operations via `gh` CLI) without modifying
the core.

## Troubleshooting

### "No VCS provider found" Error

**Cause:** Auto-detection could not find `.hg/` or `.git/` in the current directory or any parent, and no explicit
provider was configured.

**Fix:** Either run sase from within a VCS-managed directory, or set the provider explicitly:

```bash
SASE_VCS_PROVIDER=git sase commit my_feature
```

### Git: `gh` CLI Not Installed

PR operations (`get_change_url`, `mail`, `get_cl_number`) require the [GitHub CLI](https://cli.github.com/). Without it,
these operations will fail with a "command not found" error.

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
```

### Mercurial: Plugin Not Installed

The Mercurial provider requires the `sase-hg` package. Without it, hg repositories will not be detected.

**Symptoms:**

- Auto-detection does not recognize `.hg/` directories
- "No VCS provider found" error in hg repositories

**Fix:** Install the Mercurial plugin:

```bash
pip install sase-hg
```

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
