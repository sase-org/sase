---
create_time: 2026-07-08
status: research
---

# Separate GitHub SDD Repository Per Project

This consolidates the two prior research notes:

- `sdd/research/202607/github_companion_sdd_repo.md`
- `sdd/research/202607/separate_sdd_repository_per_project.md`

## Problem And Target Behavior

SASE currently stores prompt snapshots, plans, research notes, and bead state
under `sdd/` in the main code repository when `sdd.version_controlled: true`.
This repo has that setting enabled in `sase.yml`, so SDD housekeeping commits
land directly in the main repo history.

The requested behavior is:

- GitHub-backed projects should store SDD artifacts in a separate GitHub repo in
  the same organization.
- Candidate repo names are `<project>-sdd` and `sdd`; for this repo, that means
  `sase-org/sase-sdd` and `sase-org/sdd`.
- VCS providers must opt in independently.
- BareGit must keep the current in-tree `sdd/` behavior.

## Verified Current State

SASE already has two physical SDD storage modes:

| Mode | Config/effective decision | Physical root | Commit target |
| --- | --- | --- | --- |
| In-tree | `version_controlled == true` | `<workspace>/sdd` | main project repo |
| Local standalone | `version_controlled == false`, except BareGit | `<primary>/.sase/sdd` | local standalone git repo |

Important code facts:

- `get_sdd_dir()` in `src/sase/sdd/_paths.py` returns either
  `<workspace>/sdd` or `<primary>/.sase/sdd`.
- `get_effective_sdd_config()` in `src/sase/sdd/beads.py` is the current
  per-VCS seam. It returns `true` when config says so, otherwise it forces
  `detect_vcs(cwd) == "bare_git"` to use in-tree SDD.
- `init_beads()` in `src/sase/sdd/beads.py` already initializes
  `<primary>/.sase/sdd` as a git repo, writes `.gitignore`, creates beads, and
  calls `commit_sdd_files()`.
- `commit_sdd_files()` in `src/sase/sdd/_commit.py` commits inside the SDD root
  when that root has a `.git`. It does not push.
- Bead state already has push helpers in `src/sase/bead/sync.py`; they skip
  cleanly when no remote exists.
- Plan/prompt approval writes through `write_sdd_files()` and plan-reference
  helpers in `src/sase/axe/run_agent_exec_plan_accept.py` and
  `src/sase/axe/run_agent_exec_plan_sdd.py`.
- Bead location is resolved in `src/sase/bead/cli_common.py` and
  `src/sase/bead/workspace.py` by mapping the boolean SDD mode to either
  `sdd/beads` or `.sase/sdd/beads`.

The key implication: a separate SDD repo is not a brand-new storage class from
scratch. The local standalone `.sase/sdd` mode already provides most of the
filesystem, git-init, commit, and bead-layout behavior. What is missing is
remote discovery, clone/fetch, push, and a richer policy model than a boolean.

## GitHub Plugin Fit

The `sase-github` linked repo is registered as both a `sase_vcs` and
`sase_workspace` plugin. Verified relevant pieces:

- `GitHubPlugin.vcs_classify_repo()` claims repos whose `remote.origin.url`
  normalizes to a configured GitHub host.
- `GitHubWorkspacePlugin` already has org repo listing via
  `_list_github_repo_candidates()` and cloning via `_clone_gh_repo()`.
- The GitHub workspace plugin currently uses the configured default GitHub host
  for repo listing; SDD companion lookup should instead derive host, owner, and
  repo from the main repo's `origin` so GitHub Enterprise and non-default hosts
  work correctly.
- There is no existing `gh repo create` path in `sase-github`, so missing
  companion repos need either a clear error or a new explicit create/migrate
  command.

## Design Implications

The current `version_controlled: bool` is too weak. A GitHub companion repo is
version-controlled, but not version-controlled by the main code repo. The model
should become a policy enum plus a resolved store:

```python
SddStorage = Literal["in_tree", "local", "separate_repo"]

@dataclass(frozen=True)
class SddStore:
    storage: SddStorage
    sdd_dir: Path        # contains prompts/, tales/, research/, beads/, ...
    repo_root: Path      # git root to commit/push
    logical_prefix: str  # usually "sdd"
    provider: str | None = None
    remote_ref: str | None = None
```

For v1, the least disruptive external layout is to clone the companion repo
directly into `<primary>/.sase/sdd`, with repo contents like:

```text
prompts/
tales/
epics/
legends/
myths/
research/
beads/
```

That reuses the existing non-VC `.sase/sdd` machinery and bead layout. To keep
user-facing references stable, `SddStore.logical_prefix` should still allow
`sdd/...` references to resolve to the physical `.sase/sdd/...` store. This is
better than relying on symlinks or requiring every prompt to expose the physical
path.

If the fallback repo name is the org-level `sdd`, decide whether it is dedicated
to one project or shared by multiple projects. A shared `sdd` repo needs a
project namespace such as `sase/`; a dedicated `<project>-sdd` repo can use the
root layout above. Prefer `<project>-sdd` first to preserve the "per project"
property.

## Options Considered

Submodule: rejected. It keeps a pointer change in the main repo, adds workspace
initialization complexity, and does not make SDD storage a per-VCS opt-in.

Symlink `sdd` to another checkout: rejected. It is fragile across cleanup,
platforms, and git staging, and it hides the storage model from commit and bead
code.

Linked repo with a special `role: sdd`: not recommended for v1. Linked repos are
path-configured local checkouts, not auto-discovered GitHub repos, and their
commit flow is agent-driven. SDD writes are automatic host-side state changes,
so bending them through linked-repo finalization would be more invasive than
extending the existing standalone SDD repo mode.

Companion checkout containing a top-level `sdd/`: viable but more disruptive.
It preserves raw `sdd/...` paths naturally, but it means the SDD root is no
longer the git root and forces changes in `commit_sdd_files()`, bead paths, and
other non-VC helpers. A `SddStore` can support this later if needed.

Standalone `.sase/sdd` with a remote: recommended for v1. It matches existing
local mode and only requires remote materialization, push, policy, and reference
resolution work.

## Implementation Shape

1. Add config while preserving compatibility:
   - Introduce `sdd.storage: auto | in_tree | local | separate_repo`.
   - Keep `sdd.version_controlled` as a deprecated alias during migration
     (`true -> in_tree`, `false -> auto`).
   - Add optional `sdd.repo.name`, `sdd.repo.discover`,
     `sdd.repo.create_if_missing`, and `sdd.push_after_commit`.
   - Update `src/sase/default_config.yml` and
     `src/sase/config/sase.schema.json`.

2. Declare provider defaults through plugin metadata:
   - Extend `WorkflowMetadata` in `src/sase/workspace_provider/_hookspec.py`
     with an SDD storage default, or a general capability map.
   - Add a lookup next to `get_display_name_by_vcs()` in
     `src/sase/workspace_provider/_registry.py`.
   - BareGit declares `in_tree`; GitHub declares `separate_repo`; other
     providers default to existing behavior unless they opt in.

3. Add a central SDD store resolver:
   - Replace boolean-only `get_effective_sdd_config()` call sites with
     `resolve_sdd_store()` or `resolve_sdd_storage()`.
   - Keep `get_sdd_dir()` as a compatibility wrapper for callers that only need
     a directory.
   - Callers that commit, push, display, or validate links should consume the
     full `SddStore`.
   - Per the Rust core boundary, keep storage policy and logical path resolution
     in one backend-level place; Python can stay as a thin adapter if the Rust
     API is not ready for the first patch.

4. Add a provider materialization hook:
   - The metadata field declares the cheap policy; a separate hook does network
     work.
   - Prefer a `sase_workspace` hook such as `ws_resolve_sdd_store(...)`, because
     the GitHub workspace plugin already owns org repo discovery and clone
     helpers. A `sase_vcs` hook is also workable if it delegates to shared
     GitHub helpers.
   - The GitHub implementation should parse the main repo origin, probe
     `<owner>/<repo>-sdd` before `<owner>/sdd`, clone/fetch into
     `<primary>/.sase/sdd`, and return `SddStore(storage="separate_repo", ...)`.
   - Missing repo on write should fail loudly with an actionable message unless
     `create_if_missing` is explicitly enabled. Do not silently fall back to
     in-tree writes for GitHub once the provider opts in.

5. Commit and push SDD independently:
   - Continue using `commit_sdd_files()` for stores whose `repo_root == sdd_dir`.
   - Generalize it to accept `SddStore` before supporting layouts where
     `repo_root != sdd_dir`.
   - Add a push step after successful SDD commits when a remote exists and
     `sdd.push_after_commit` is enabled. Reuse the bead push posture: local
     commit should survive even if push fails.
   - Keep code commits focused on code changes plus logical `PLAN=sdd/...`
     references, not SDD file staging.

6. Update the high-risk call sites together:
   - Plan approval/archive and accepted-plan handling:
     `src/sase/plan_approval_actions.py`,
     `src/sase/ace/tui/actions/agents/_notification_modals.py`,
     `src/sase/axe/run_agent_exec_plan_accept.py`,
     `src/sase/axe/run_agent_exec_plan_sdd.py`.
   - Plan search and SDD validation:
     `src/sase/plan_search/facade.py`, `src/sase/sdd/links.py`,
     `src/sase/doctor/checks_config_sdd.py`.
   - Beads and Rust-backed fast paths:
     `src/sase/bead/cli_common.py`, `src/sase/bead/workspace.py`,
     `src/sase/main/bead_fast_path.py`.
   - Commit hooks/finalizers:
     `src/sase/workflows/commit/precommit_hooks.py`,
     `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`,
     `src/sase/llm_provider/commit_finalizer_git.py`.
   - TUI/watchers and display helpers that hard-code `Path.cwd()/sdd/beads`.

7. Cover research markdown explicitly:
   - Plans and beads mostly flow through SDD APIs; research notes often come
     from prompts that say "write under `sdd/research/...`" and agents then
     edit that literal path.
   - Add an agent-facing helper or generated instruction that gives the
     effective research directory, for example `sase sdd path research` or an
     env var such as `SASE_SDD_DIR`.
   - Teach file-reference resolution that `@sdd/research/...` is logical and
     maps through the active `SddStore`.
   - Without this, research agents will continue creating files in the code
     repo even after plan/bead storage moves.

8. Migration and tests:
   - Provide `sase sdd migrate` or extend `sase sdd init` to create/clone the
     companion repo, copy existing SDD contents, push, and optionally remove
     tracked `sdd/` from the code repo in a clearly labeled commit.
   - Test BareGit invariance, GitHub repo-name precedence, missing-repo errors,
     plan reference resolution, bead read/write location, SDD commit/push, and
     no accidental staging of SDD paths in code commits.

## Open Decisions

- Repo precedence: recommend `<project>-sdd` before `sdd`.
- Shared `sdd` repo layout: require a project namespace unless explicitly
  configured as dedicated.
- Missing repo behavior: recommend error by default; optional create/migrate
  command later.
- Offline behavior: reads may fall back to already-cloned `.sase/sdd`; writes
  should not create in-tree GitHub churn silently.
- Config compatibility window for `sdd.version_controlled`.

## Recommended Approach

Implement a third SDD storage policy, `separate_repo`, as a provider-declared
opt-in. BareGit declares `in_tree`; GitHub declares `separate_repo`. Resolve the
policy through `WorkflowMetadata` instead of another hard-coded provider-name
check, and materialize the GitHub store through a new provider hook that finds
`<owner>/<project>-sdd` first and `<owner>/sdd` second using the main repo's
GitHub host.

For the first implementation, clone the companion repo into
`<primary>/.sase/sdd` and keep the existing root layout (`prompts/`, `tales/`,
`research/`, `beads/`). Add `SddStore` so callers know both the physical root
and the logical `sdd/...` prefix, then update plan, bead, research, search, TUI,
and commit paths to use that resolver. Commit and push SDD changes in the
companion repo; do not stage them in code commits. If the companion repo is
missing for a GitHub project, fail with a clear migration/create message rather
than falling back to main-repo `sdd/` writes.
