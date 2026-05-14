---
create_time: 2026-05-14
updated_time: 2026-05-14
status: research
---

# Workspace Directory Layout Research

## Question

If SASE were being implemented again from scratch, should ephemeral agent workspace directories live in the same parent
directory as the primary workspace, or should they live somewhere else? What implementation shape would keep the useful
parts of today's workspace model while avoiding a directory explosion next to the user's main checkout?

## Summary Recommendation

Do not make sibling directories the default in a from-scratch design. Keep numeric workspace identity, but separate it
from physical path layout.

The better default is a SASE-managed workspace store:

```text
${SASE_WORKSPACE_ROOT:-$XDG_STATE_HOME/sase/workspaces}/
  <project-key>/
    ws-0001/        # optional primary alias/metadata, not necessarily a clone
    ws-0100/
      checkout/
    ws-0101/
      checkout/
    registry.json
```

For Linux, `$XDG_STATE_HOME` is the best default class: these checkouts are durable local application state that should
survive restarts, but they are not user-authored source-of-truth data. Fall back to `~/.local/state/sase/workspaces`
when `$XDG_STATE_HOME` is unset. Use `$XDG_CACHE_HOME` only for rebuildable byproducts inside each workspace, not for
the workspace checkout itself. The XDG spec defines state, cache, and runtime homes separately, with state defaulting to
`$HOME/.local/state` and cache defaulting to `$HOME/.cache`.

Keep an opt-in project or global setting for adjacent workspaces:

```yaml
workspace:
  root: adjacent   # or /absolute/path, or xdg-state
```

Adjacent workspaces are still useful for debugging and for provider ecosystems that already encode sibling layout. They
should be a compatibility mode, not the hidden global assumption.

## Current Shape

The current system stores the primary checkout in the ProjectSpec `WORKSPACE_DIR` field, then derives numbered Git
workspaces by appending `_<workspace_num>` to that path:

- `src/sase/workspace_provider/utils.py:173` computes the Git clone path. For workspace `1`, it returns the primary
  directory; for `2+`, it returns `f"{primary.rstrip('/')}_{workspace_num}/"`.
- `src/sase/workspace_provider/utils.py:190` materializes those directories as independent local clones of the primary
  workspace, validates existing clones with `git status`, and recreates corrupt clones.
- `src/sase/workspace_provider/plugins/bare_git_workspace.py:133` delegates Git workspace resolution to
  `ensure_git_clone(primary_workspace_dir, workspace_num)`.
- `src/sase/running_field/_workspace.py:28` allocates axe workspaces from the numeric range `100-199`; `:61` resolves a
  workspace number to a directory; `:92` cleans non-primary workspaces before handing them out.
- `src/sase/agent/launch_executor.py:327` preclaims a numeric workspace in the ProjectSpec `RUNNING` field, resolves
  the directory, and then transfers the claim to the spawned child process.
- `src/sase/axe/run_agent_phases.py:30` uses the same number plus directory contract when deferred `%wait` agents
  finally claim a real workspace.

So today's sibling directories are not just a filesystem convention. They are an implementation detail under a more
important invariant: a workspace number must map deterministically to a prepared checkout that can be claimed, cleaned,
used, displayed, and released.

## What Works Well Today

The current design has real strengths:

- It is easy to inspect manually. If the primary repo is `sase`, agent workspace `#102` is visibly nearby as
  `sase_102`.
- It is deterministic without a separate registry. `WORKSPACE_DIR + "_" + workspace_num` is enough to locate a clone.
- It works with simple tools. Shells, editors, `rg`, and manual `cd ../sase_102` all work without a SASE command.
- It makes crash recovery possible even when SASE state is partially stale, because the directory name itself carries
  enough information to guess what it is.
- It keeps numeric identity stable across the TUI, `RUNNING` field, artifact metadata, and completion cleanup.

Those properties are worth keeping. The problem is only that the physical namespace is the user's project namespace.

## What Hurts

The sibling layout scales poorly as SASE usage becomes normal rather than occasional:

- Directory clutter: one active project can create dozens of peers beside the primary checkout.
- Weak ownership boundary: SASE-managed scratch clones look like user-managed projects.
- Accidental scans: tools that enumerate `~/projects/github/sase-org/*` now see long-lived generated checkouts.
- Cross-workspace leakage: older bead behavior treated sibling workspace stores as a family to merge. Recent work is
  deliberately removing that model so each checkout's `sdd/beads/issues.jsonl` is its own source of truth.
- Path parsing hardens into architecture. `src/sase/bead/project_name.py:12` and `src/sase/bead/workspace.py:63` still
  know how to recognize numbered variants of a primary workspace path.
- Multi-project machines become noisy. The pain is multiplicative when every SASE-managed project gets `project_100`,
  `project_101`, and so on in its source parent.

The strongest product objection is that SASE workspaces are not primary work artifacts from the user's perspective.
They are managed execution state. That argues for a managed state directory.

## External Prior Art

Git itself does not require linked worktrees to be siblings. `git worktree add <path>` accepts an arbitrary target path;
the Git documentation's examples use sibling paths such as `../hotfix`, but the details section shows Git tracks the
chosen path through per-worktree administrative metadata under the main repository's `.git/worktrees/` directory.
Source: https://git-scm.com/docs/git-worktree.html

Git also provides lifecycle commands that matter if SASE ever uses linked worktrees instead of independent clones:
`git worktree prune`, `git worktree repair`, `git worktree lock`, `git worktree list --porcelain`, and
worktree-specific config. That is useful prior art for the SASE registry: workspaces need explicit metadata, stale-entry
cleanup, repair, and machine-readable listing.

The XDG Base Directory specification draws the relevant storage boundary: user-specific state belongs under
`$XDG_STATE_HOME` with a default of `$HOME/.local/state`; non-essential cached data belongs under `$XDG_CACHE_HOME`;
runtime files have a separate, short-lived runtime directory. Source:
https://specifications.freedesktop.org/basedir-spec/0.8/

## From-Scratch Design

### 1. Introduce a `WorkspaceStore`

Make path layout a first-class service instead of a string convention.

```python
@dataclass(frozen=True)
class WorkspacePath:
    project_key: str
    workspace_num: int
    root_dir: Path
    checkout_dir: Path
    materialization: Literal["git-clone", "git-worktree", "provider", "direct"]
    generation: str
```

Resolver inputs:

- project name and ProjectSpec path;
- primary `WORKSPACE_DIR`;
- workspace number;
- workflow/provider type;
- policy: `xdg-state`, `adjacent`, or absolute root.

Resolver outputs:

- checkout directory;
- display label;
- cleanup policy;
- provider-specific metadata.

This keeps `workspace_num` as the stable user-facing and claim-facing ID, while making the checkout path explicit.

### 2. Use a Registry, Not Path Derivation

Store a small registry under the workspace store:

```json
{
  "schema_version": 1,
  "project_key": "sase-org_sase",
  "primary_workspace_dir": "/home/bryan/projects/github/sase-org/sase",
  "workspaces": {
    "100": {
      "checkout_dir": "/home/bryan/.local/state/sase/workspaces/sase-org_sase/ws-0100/checkout",
      "materialization": "git-clone",
      "created_at": "2026-05-14T10:00:00-04:00",
      "last_used_at": "2026-05-14T10:05:00-04:00"
    }
  }
}
```

The ProjectSpec `RUNNING` field can still contain `#100` for readability, but the claim layer should also persist either
the resolved `workspace_dir` or a registry generation ID. Artifacts already record `workspace_dir` in several paths; a
from-scratch design should make that required for completed agents.

### 3. Keep Provider-Specific Materialization Behind One Interface

Git should not be hard-coded as "primary path plus suffix." A provider should be asked to materialize a checkout at a
target directory chosen by the store:

```python
class WorkspaceProvider:
    def materialize_workspace(
        self,
        primary_workspace_dir: Path,
        target_checkout_dir: Path,
        workspace_num: int,
    ) -> WorkspacePath: ...
```

For Git, there are two viable materializers:

- Independent local clone: closest to today's behavior; strong isolation; more disk and setup cost.
- Linked worktree: less disk and faster; requires careful branch/detached-head policy and Git worktree repair/prune
  integration.

I would keep independent clones as the initial materializer unless SASE can prove all agent workflows can tolerate
Git's shared refs/config behavior. The big design change is not "use worktrees"; it is "the materializer receives an
explicit target path."

Directory workflows such as `#cd` should stay direct. Today `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py:5`
marks `cd` as non-workspace and `src/sase/workspace_provider/plugins/cd_workspace.py:60` returns the primary directory.
That remains correct.

### 4. Make Allocation Path-Aware

Allocation should become one atomic operation:

1. choose the first free numeric workspace in the configured range;
2. reserve it in the ProjectSpec `RUNNING` field;
3. resolve or materialize its checkout directory;
4. store the resolved path in the claim metadata;
5. transfer the claim to the child process on spawn.

Today's preclaim flow already has the right concurrency shape. The from-scratch change is to resolve through
`WorkspaceStore`, not through `get_workspace_directory_for_num(project_name, num)`.

### 5. Add Explicit User Surfaces

Moving workspaces out of sight makes observability more important.

Useful commands:

```bash
sase workspace list
sase workspace path 102
sase workspace open 102
sase workspace cleanup --stale
sase workspace repair
```

The TUI should show `#102` as it does now, but reveal the full path in detail views and completion notifications. This
preserves debuggability without making generated directories compete with primary project checkouts.

## Migration Shape

This is a medium-sized architecture migration, not a one-line path change.

1. Add `WorkspaceStore` with default policy `adjacent` and tests proving parity with current paths.
2. Add config support for `workspace.root`, accepting `adjacent`, `xdg-state`, or an absolute path.
3. Change `ensure_git_clone()` into a materializer that accepts an explicit target directory. Keep the old
   `primary_<num>` helper as a compatibility policy.
4. Update allocation paths:
   - `running_field._workspace.get_workspace_directory_for_num()`
   - `agent.launch_executor._preclaim_axe_workspace()`
   - deferred workspace claim in `axe.run_agent_phases.claim_deferred_workspace()`
   - scheduler/workflow runners that call `get_workspace_directory_for_num()`
5. Persist resolved `workspace_dir` in claim metadata or a side registry before spawn.
6. Update project-name and bead resolution to stop depending on sibling path recognition except as a legacy fallback.
7. Add cleanup and repair commands before flipping the default away from adjacent.
8. Flip new installs to `xdg-state`; leave existing projects on adjacent unless the user opts into migration.

The safe rollout is "new config path first, default later." Existing long-lived workspaces and scripts probably depend
on `../project_101`.

## Decision Matrix

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| Keep sibling default | Simple, visible, compatible with current code | Clutters source parents; path convention leaks everywhere; encourages sibling scans | Good compatibility mode, poor default |
| Hidden global state root | Clean source parents; explicit ownership; central cleanup | Needs list/open/repair commands; migration work | Best default |
| Per-project `.sase/workspaces` under primary repo | Keeps state near project but not sibling clutter | Risks nesting generated clones inside repo trees; easy to accidentally commit/scan | Avoid |
| Git linked worktrees in managed root | Efficient and standard Git lifecycle | Shared refs/config constraints; same-branch policy complexity | Worth evaluating after path abstraction |
| Temp directory workspaces | No persistent clutter | Bad for long agents, debugging, crash recovery, dependency reuse | Not suitable for normal SASE agents |

## Final Recommendation

If doing it again from scratch, model SASE workspaces as managed application state:

- numeric IDs remain the user-facing identity;
- physical paths are resolved through a `WorkspaceStore`;
- default storage is `$XDG_STATE_HOME/sase/workspaces/<project-key>/ws-<num>/checkout`;
- adjacent `primary_<num>` directories remain an explicit compatibility/debugging policy;
- provider plugins materialize checkouts into caller-supplied target directories;
- claims and artifacts store enough resolved-path metadata that no caller has to infer paths by suffix.

This keeps the operational strengths of today's design while removing the main product cost: generated execution
checkouts filling the same parent directory as the user's real projects.
