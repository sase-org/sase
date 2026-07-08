# GitHub Companion SDD Repository Research

Date: 2026-07-08

## Question

SASE currently stores prompt snapshots, tales, epics, legends, research notes, and beads under `sdd/` in the main project
repository when `sdd.version_controlled: true`. That keeps the SDD corpus portable, but it also pushes a large amount of
non-code churn into the main git history.

The target behavior is:

- GitHub-backed projects should use a separate GitHub repository for SDD content when one exists in the same
  organization.
- Candidate companion repositories are `<owner>/sdd` and `<owner>/<project>-sdd`, where `<project>` is the main repo
  name. For this repo, candidates are `sase-org/sase-sdd` and `sase-org/sdd`.
- VCS providers should opt in independently.
- The built-in `bare_git` provider should keep the current project-local `sdd/` behavior.

## Current Implementation

The existing implementation has two physical SDD modes:

- Local mode: `{primary_workspace}/.sase/sdd/`, a standalone git repo.
- Version-controlled mode: `{workspace}/sdd/`, tracked by the project repo.

The current SASE repo has `sdd.version_controlled: true` in `sase.yml`, so accepted plans and beads write directly into
the code checkout today.

Important code paths:

- `src/sase/sdd/_paths.py`
  - `get_sdd_dir(workspace_dir, workspace_num, version_controlled)` returns either `{workspace}/sdd` or
    `{primary}/.sase/sdd`.
  - This boolean contract is now too weak: an external GitHub companion repo is version-controlled, but not in the code
    checkout.
- `src/sase/sdd/_write.py`
  - `write_sdd_files()` writes prompt and plan files below an already-resolved `sdd_dir`.
  - `sdd_link_path()` already emits `sdd/...` links whenever the physical root is named `sdd`, so a companion repo that
    contains a top-level `sdd/` directory can preserve existing frontmatter links.
- `src/sase/sdd/_commit.py`
  - `commit_sdd_files()` only commits when `sdd_dir/.git` exists. This works for local `.sase/sdd`, but not for a
    companion repo laid out as `<repo>/sdd`, where `.git` is at `<repo>/.git`.
  - Bare-git initialization helpers intentionally special-case local bare remotes and should remain unchanged for
    `bare_git`.
- `src/sase/axe/run_agent_exec_plan_accept.py`
  - Accepted plans write SDD files, maybe commit them, set `SASE_PLAN`, and build follow-up prompts.
  - Epic and legend approvals need the plan committed before launching follow-up agents because VCS pre-steps can clean
    uncommitted files.
- `src/sase/plan_approval_actions.py` and `src/sase/ace/tui/actions/agents/_notification_modals.py`
  - CLI/TUI approval archives the pending plan before the runner consumes the response. This means SDD storage
    resolution must work in host/UI code, not just inside the agent runner.
- `src/sase/plan_search/facade.py` and `src/sase/sdd/links.py`
  - Plan search and validation resolve `sdd/` from the current checkout. They need to follow the effective SDD store.
- `src/sase/bead/workspace.py`, `src/sase/bead/cli_common.py`, and `src/sase/main/bead_fast_path.py`
  - Bead reads and writes assume effective version-controlled SDD means `sdd/beads` in the current or primary code
    checkout.
  - The Rust-backed bead fast path receives explicit read/write bead directories from Python, so Python can redirect it
    without Rust API changes.
- `src/sase/workflows/commit/precommit_hooks.py` and
  `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`
  - Code commits currently close/sync beads and stage `sdd/beads/` plus `_plan_path` from the code checkout.
  - With external SDD, SDD mutations should be committed to the companion repo, not staged into the code commit.

## GitHub Plugin Capabilities

The linked `sase-github` plugin already has the right primitives:

- `src/sase_github/plugin.py`
  - `GitHubPlugin.vcs_classify_repo()` claims git repos whose `origin` host matches configured GitHub hosts.
- `src/sase_github/workspace_plugin.py`
  - `GitHubWorkspacePlugin.ws_resolve_ref()` resolves `#gh` refs.
  - `resolve_gh_ref("owner/repo")` clones the repo if needed, creates or reuses a SASE project record, and returns a
    `ResolvedRef`.
  - `_github_workspace_dir(user, project, host=...)` and `_clone_gh_repo(..., host=...)` already support host-aware
    workspace paths.
  - `_list_github_repo_candidates()` uses `gh repo list` for repo completion.
- `sase-github` is registered as both a `sase_vcs` and `sase_workspace` plugin.

One gap: `resolve_gh_ref()` currently uses the configured default GitHub host for `owner/repo` refs. Companion SDD
lookup should use the host from the main repo's `origin`, not necessarily the default configured host.

## Design Constraints

The best design needs to preserve these properties:

- Existing SDD frontmatter links like `sdd/tales/202607/foo.md` should remain valid after moving the `sdd/` tree.
- Agents must still be able to read approved plan files from follow-up prompts.
- Bead state must have one canonical write store per project.
- `bare_git` must continue using project-local `sdd/`.
- Core SASE should not import `sase_github`; GitHub-specific behavior belongs behind plugin hooks.
- Missing companion repositories should not silently recreate code-repo SDD churn for GitHub projects.

## Options Considered

### 1. Git Submodule

Make `sdd/` a submodule pointing at `sase-org/sase-sdd` or `sase-org/sdd`.

This is not a good fit. Submodule pointer updates still dirty the main repo, agent workspaces must initialize and update
submodules correctly, and code commits can still accidentally include pointer churn. It also gives every VCS provider
submodule semantics whether or not it opted in.

### 2. Symlink `sdd/` to a Companion Checkout

Keep code paths almost unchanged by symlinking `sdd` to another clone.

This is too fragile. Git can stage the symlink, workspace cleanup can remove or rewrite it, and cross-platform behavior
is poor. It also hides the real storage model from SASE, making bead commits and plan search harder to reason about.

### 3. Put a Remote on `.sase/sdd`

Reuse local mode's standalone git repo and add the GitHub companion as its remote.

This keeps SDD out of the main repo, but it makes paths and links use `.sase/sdd/...` instead of `sdd/...`, and it does
not match the requested "separate GitHub repo for these files" model cleanly. It is also less discoverable for humans
than a normal companion checkout.

### 4. Add an Explicit SDD Storage Resolver

Introduce an `SddStore` abstraction in core and let VCS providers optionally return an external store. The GitHub plugin
would opt in by resolving or cloning the companion repo. Bare-git would not implement the hook and would keep the old
behavior.

This is the best fit. It makes external SDD a first-class storage mode instead of encoding it into the existing boolean.

## Proposed Core Shape

Add a small storage model, for example in `src/sase/sdd/storage.py`:

```python
@dataclass(frozen=True)
class SddStore:
    kind: Literal["local", "project", "external"]
    sdd_dir: Path          # directory containing prompts/, tales/, beads/, ...
    repo_root: Path        # git repo root for committing this store
    logical_prefix: str    # normally "sdd"
    provider: str | None = None
    remote_ref: str | None = None
```

Then add resolver helpers:

- `resolve_sdd_store(workspace_dir: str, workspace_num: int = 1) -> SddStore`
- `resolve_sdd_store_for_cwd(cwd: Path | None = None) -> SddStore | None`
- `resolve_sdd_file_ref("sdd/epics/...", cwd=...) -> Path | None`

Keep `get_sdd_dir()` as a compatibility wrapper over `resolve_sdd_store(...).sdd_dir`, but migrate call sites that need
commit behavior to the full store object.

External companion layout should be:

```text
<companion-repo>/
  sdd/
    prompts/
    tales/
    epics/
    legends/
    myths/
    research/
    beads/
```

This preserves existing `sdd/...` frontmatter and bead design paths while keeping the main repo clean.

## Proposed Provider Hook

Add an optional VCS hook such as:

```python
def vcs_resolve_sdd_store(self, cwd: str, workspace_num: int) -> dict | None: ...
```

The core resolver calls `get_vcs_provider(cwd)` and asks the provider for an SDD store. If the hook returns `None`, core
uses the current behavior:

- `bare_git` or `sdd.version_controlled: true` -> `{workspace}/sdd`
- otherwise -> `{primary}/.sase/sdd`

The GitHub implementation should:

1. Parse `remote.origin.url` from the main repo to get `(host, owner, repo)`.
2. Probe candidates in this order:
   - `<owner>/<repo>-sdd`
   - `<owner>/sdd`
3. Use the main repo's GitHub host, not only `get_default_github_host()`.
4. Prefer `gh repo view <owner>/<candidate> --json nameWithOwner` with `GH_HOST=<host>` for exact existence checks,
   falling back to `git ls-remote` or direct clone attempts if `gh` is unavailable.
5. Clone or update the companion checkout using the same host-aware path rules as normal GitHub workspaces.
6. Return `kind="external"`, `repo_root=<companion checkout>`, `sdd_dir=<companion checkout>/sdd`,
   `remote_ref=<owner>/<candidate>`.

If no companion repo exists, write paths should fail loudly with an actionable message such as:

```text
GitHub SDD companion repo not found. Create one of:
  - sase-org/sase-sdd
  - sase-org/sdd
```

Read-only paths can still optionally fall back to legacy in-repo `sdd/` during migration, but writes should not silently
fall back once the GitHub provider claims the project.

## Commit and Sync Behavior

Add commit helpers that work from `SddStore`, not just `sdd_dir`:

- `ensure_sdd_store_initialized(store, commit=True, push=True)`
- `commit_sdd_store_paths(store, message, paths=..., push=True)`
- `sync_sdd_store(store)` for fetch/rebase before writes where appropriate.

For `kind="external"`, these helpers should run git in `store.repo_root` and stage paths relative to that repo. They
should push after committing, with the same timeout/retry posture already used for SDD git operations and git commit
dispatch. Bead conflicts can still use the existing resolver because the companion repo layout keeps bead files under
`sdd/beads/`.

For `kind="project"`, preserve current behavior:

- Bare-git keeps committing SDD files through the project repo path.
- Existing `sase commit` integration can continue to stage project-local `sdd/` files.

For `kind="local"`, preserve current `.sase/sdd` standalone git behavior.

## Main Call-Site Changes

The first implementation should update these paths together:

- Plan approval archive:
  - `src/sase/plan_approval_actions.py`
  - `src/sase/ace/tui/actions/agents/_notification_modals.py`
- Accepted plan handling:
  - `src/sase/axe/run_agent_exec_plan_accept.py`
  - `src/sase/axe/run_agent_exec_plan_sdd.py`
- SDD CLI/search/doctor:
  - `src/sase/sdd/links.py`
  - `src/sase/plan_search/facade.py`
  - `src/sase/doctor/checks_config_sdd.py`
- Beads:
  - `src/sase/bead/workspace.py`
  - `src/sase/bead/cli_common.py`
  - `src/sase/main/bead_fast_path.py`
- Commit workflow:
  - `src/sase/workflows/commit/precommit_hooks.py`
  - `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`

Follow-up prompts can initially use absolute physical paths for `@...` plan references so agents can read companion
files immediately. Stored metadata should still canonicalize those paths back to logical `sdd/...` references when the
path is under `store.sdd_dir`. A later polish pass can teach `file_references.py` to resolve `@sdd/...` through the
active SDD store so prompts stay pretty without losing correctness.

## Migration Notes

For this repo, create either `sase-org/sase-sdd` or `sase-org/sdd`, then copy or history-filter the existing `sdd/`
tree into the companion repo. Keeping the top-level `sdd/` directory inside the companion repo avoids frontmatter
rewrites.

After the companion repo is active:

- New SDD writes go to the companion repo.
- Plan search should prefer the companion repo.
- Legacy in-repo `sdd/` can remain readable until it is removed or archived.
- The main repo can eventually delete the tracked `sdd/` tree and ignore accidental local `sdd/` recreation.

## Recommended Approach

Implement a first-class `SddStore` resolver in core, backed by a new optional VCS provider hook. Have `sase-github`
implement that hook by deriving the main repo's GitHub host/owner/repo, probing `<project>-sdd` before `sdd`, and
returning a companion checkout whose layout is `<companion>/sdd/...`. Do not use submodules or symlinks.

Update plan approval, plan search, SDD validation, bead location, bead fast path, and commit hooks to consume the
resolved store instead of assuming `version_controlled == workspace/sdd`. For GitHub external stores, commit and push
SDD changes in the companion repo independently; keep code commits focused on code changes and logical `PLAN=sdd/...`
references. Leave `bare_git` without the new hook so it continues using the current project-local `sdd/` behavior.
