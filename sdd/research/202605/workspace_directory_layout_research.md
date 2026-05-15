---
create_time: 2026-05-13
updated_time: 2026-05-13
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
    <project>_10/   # first claim-allocated workspace
      checkout/
    <project>_11/
      checkout/
    registry.json
```

Workspace `#0` is the primary checkout and resolves to the user's existing primary working tree
(e.g. `~/projects/github/sase-org/sase/`) — it is *not* a directory inside the managed store. Claim-allocated
workspaces live in one unified numeric pool starting at `10` (shared by xprompts and agent runs), with `1-9` reserved
for future special-purpose use. Each on-disk basename uses the project name as prefix (`sase_10`, `sase-core_11`, etc.)
so that an isolated `cd` into the directory still tells the user which project they are in.

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

Cross-platform default resolution should not be raw `$XDG_STATE_HOME`. Linux follows the XDG spec; macOS does not, and
Windows has no XDG concept at all. Use a `platformdirs`-style helper:

- Linux: `$XDG_STATE_HOME/sase/workspaces` (fall back to `~/.local/state/sase/workspaces`).
- macOS: `~/Library/Application Support/sase/workspaces` (Apple does not publish a separate "state" directory; Caches
  is wrong because checkouts are not rebuildable byproducts).
- Windows: `%LOCALAPPDATA%\sase\workspaces` (e.g. `C:\Users\<user>\AppData\Local\sase\workspaces`).

This avoids reinventing per-OS rules and matches how `pip`, `poetry`, `pipx`, and `rye` already locate user state.

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

The numeric namespace is partitioned by purpose, not just by allocation order:

- `1` is the primary checkout (the user's hand-managed working tree).
- `2-99` are workflow-allocated shares (`get_first_available_workspace` in `src/sase/running_field/_workspace.py:6`).
- `100-199` are axe-allocated workspaces for agent runs (`get_first_available_axe_workspace`,
  `src/sase/running_field/_workspace.py:28`).

The path layout (`primary`, `primary_2`, ..., `primary_102`, ...) discards that semantic split: every share looks
identical on disk. A from-scratch design should flatten the partition into one unified pool of claim slots starting
at `10` and recover any per-purpose distinction (workflow share vs. axe run) from the registry, not from the numeric
range. Workspace `#0` becomes the dedicated identifier for the primary checkout, replacing today's `#1`.

There is a second, indirect coupling worth naming: `src/sase/bead/workspace.py:63` and
`src/sase/bead/project_name.py:12` resolve the current project by scanning sibling directories whose basename matches
`<project>` or `<project>_<N>`. CWD-based project inference depends on the sibling convention today; a managed store
must replace this fallback with a registry lookup or an explicit per-checkout marker file (e.g. `.sase/checkout.json`)
so `cd ~/.local/state/sase/workspaces/.../checkout` still reports the right project.

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
- Editor and shell ergonomics suffer. VS Code "Recent Folders", JetBrains recent projects, fish/zsh `cd -` history,
  fzf project pickers, and `Z`-style directory rankers all surface `project_102/` next to `project/`. Users have to
  filter generated checkouts out of every recency list by hand.
- Backup, snapshot, and sync tools double-count execution state. Users who back up `~/projects` via Time Machine,
  Borg, Restic, BTRFS snapshots, or Syncthing capture every numbered clone as if it were source, wasting space and
  occasionally syncing half-mutated agent state across machines. A managed state root keeps execution state out of the
  user's primary backup surface unless they explicitly opt in.
- Recursive globs across the parent fan out badly. `rg`, `fd`, `grep -r`, and IDE workspace-wide search must learn to
  skip `*_<N>` siblings, or accept N-times slower searches over duplicated working trees.

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

Other tools that manage many parallel working trees offer concrete shapes worth comparing:

- Cargo and Rust pick a managed root by default. `target/` lives inside the workspace, but `CARGO_TARGET_DIR` and
  `build.target-dir` let users redirect it to a single host-wide directory; `sccache` and `cargo-target-dir` plugins
  exist precisely because in-repo defaults clutter source trees.
  Source: https://doc.rust-lang.org/cargo/reference/config.html#buildtarget-dir
- Jujutsu (`jj`) exposes a first-class workspace model: `jj workspace add <path>` registers a workspace by *name*, and
  `jj workspace list` enumerates them. Paths are arbitrary; identity is the workspace name, not the directory. This is
  the cleanest prior art for "numeric ID is the identity, path is a deployment detail."
  Source: https://jj-vcs.github.io/jj/latest/working-copy/#workspaces
- Bazel uses an explicit `output_base` per workspace, with `$OUTPUT_USER_ROOT/<hash>` derived from the workspace path
  so two checkouts of the same repo do not collide. SASE faces the same collision question for project keys.
  Source: https://bazel.build/remote/output-directories
- Nix and pnpm both use content-addressed stores with symlink farms in user-visible locations. The pattern is
  reusable here: the store is hidden, but a thin user-visible surface (`/nix/store`, `node_modules/.pnpm`) is
  enumerable and predictable.

These confirm two design moves: (1) make identity orthogonal to filesystem path, and (2) derive collision-safe keys
from a stable identifier rather than from basename alone.

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

### 1a. Derive Project Keys Safely

A managed store needs a `project_key` to namespace workspaces. Basename alone is unsafe: a user with
`~/projects/personal/sase-core` and `~/work/sase-core` cannot coexist under
`~/.local/state/sase/workspaces/sase-core/`. The current adjacent layout sidesteps this by carrying full project paths
implicitly; a managed store has to encode origin.

Recommended derivation order:

1. If the primary repo has a single Git remote, use a slugified `<host>/<owner>/<repo>` (e.g.
   `github.com_sase-org_sase`). This matches Bazel's "hash of workspace path" technique but with a stable, readable
   key.
2. If no remote or multiple remotes exist, fall back to a slug of the absolute primary path plus a short content hash
   suffix (`sase-core-3f7a`). The suffix prevents collisions when the same repo is checked out twice locally.
3. Allow explicit override via `workspace.project_key` in `sase.yml` for cases where the auto-derivation is wrong.

The registry must store both the resolved key and the inputs that produced it, so a remote URL rewrite or repository
move surfaces as a detected mismatch rather than a silent split between old and new workspace pools.

### 2. Use a Registry, Not Path Derivation

Store a small registry under the workspace store:

```json
{
  "schema_version": 1,
  "project_key": "sase-org_sase",
  "primary_workspace_dir": "/home/bryan/projects/github/sase-org/sase",
  "workspaces": {
    "0": {
      "checkout_dir": "/home/bryan/projects/github/sase-org/sase",
      "materialization": "primary",
      "role": "primary"
    },
    "10": {
      "checkout_dir": "/home/bryan/.local/state/sase/workspaces/sase-org_sase/sase_10/checkout",
      "materialization": "git-clone",
      "role": "claim",
      "created_at": "2026-05-14T10:00:00-04:00",
      "last_used_at": "2026-05-14T10:05:00-04:00"
    }
  }
}
```

The ProjectSpec `RUNNING` field can still contain `#10` for readability, but the claim layer should also persist either
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

Git offers four realistic materializers with different trade-offs:

| Materializer | Disk | Setup time | Isolation | Caveats |
| --- | --- | --- | --- | --- |
| Full clone (`git clone`) | ~1x repo size per workspace | Slow on large repos | Strong (independent refs/config/HEAD) | Origin URL must be re-pointed; current implementation in `ensure_git_clone` |
| Local clone (`git clone --local`) | Hard-linked objects, working tree only | Fast on same filesystem | Strong (independent refs/config) | Hard-link only works when both paths share a filesystem, fails for `xdg-state` on a separate volume |
| Shared alternates (`git clone --reference` / `--shared`) | One shared object DB | Fastest | Medium (refs/config independent, objects shared) | Pruning the primary repo's reachable objects can corrupt dependents; `git repack -a -d` on primary becomes dangerous |
| Linked worktree (`git worktree add`) | One shared object DB and config | Fastest | Weak (cannot check out the same branch twice; shared `index.lock` quirks) | Requires `git worktree prune/repair` integration; same-branch policy must be designed; submodule support is incomplete |

I would keep independent clones (with `--local` when filesystems match) as the initial materializer unless SASE can
prove all agent workflows tolerate Git's shared refs/config behavior. The big design change is not "use worktrees"; it
is "the materializer receives an explicit target path." Picking between `--local`, `--reference`, and `--shared` then
becomes a policy knob on the materializer, not a structural change.

Same-filesystem matters: a clone with `--local` hard-links objects and uses tens of MB instead of hundreds. If the
managed root lives on a different mount than the user's primary checkout, that optimization silently vanishes. The
store should detect cross-device targets and fall back to either a packfile transfer or `--reference` against the
primary repo.

Directory workflows such as `#cd` should stay direct. Today `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py:5`
marks `cd` as non-workspace and `src/sase/workspace_provider/plugins/cd_workspace.py:60` returns the primary directory.
That remains correct.

### 4. Make Allocation Path-Aware

Allocation should become one atomic operation:

1. choose the first free numeric workspace in the unified pool (`10+`; `0` is reserved for the primary checkout and
   `1-9` are reserved for future special-purpose slots);
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
sase workspace path 10
sase workspace open 10
sase workspace cleanup --stale
sase workspace repair
```

The TUI should show `#10` as it does now for the current `#102`-style label, but reveal the full path in detail views
and completion notifications. This preserves debuggability without making generated directories compete with primary
project checkouts.

## Sibling-Repo Coupling

The in-progress sibling-repo work documented in
[`sibling_repos_workspace_generalization.md`](./sibling_repos_workspace_generalization.md) currently assumes the same
`primary_<N>` suffix convention for sibling checkouts: main `sase_102` edits `sase-core_102`. A from-scratch managed
store changes this in two ways:

1. The sibling resolver must call back into the same `WorkspaceStore`, asking it to materialize the sibling's
   workspace `N` rather than concatenating suffixes itself. Otherwise main moves to
   `~/.local/state/sase/workspaces/...` but siblings stay adjacent, and the two halves of the project group drift apart.
2. The store should expose a "project group" concept so that, given a workspace number `N` for the primary, every
   declared sibling resolves to its own `workspace_num = N` checkout under the same managed root. This is a small
   extension to the registry: each workspace entry gains an optional `group_id` and `role` (`primary` | `sibling:<name>`).

The two efforts should land in the right order: ship `sibling_repos` Phase 1 first with the existing suffix convention
(so users get the feature), then introduce `WorkspaceStore` and migrate both primary and sibling materialization to it
in the same release. Trying to introduce a managed store before sibling repos exist makes the migration twice as
expensive because the suffix scanner in `tools/sase_sibling_commit_stop_hook` is still authoritative.

## GC, Lifecycle, And Crash Recovery

The adjacent convention has no GC: stale `project_102` directories sit in source parents forever, and the only signal
they are stale is whether the user remembers to delete them. A managed store should make lifecycle explicit:

- Each workspace registry entry carries `created_at`, `last_used_at`, `role` (`axe` vs. `workflow-share`), and an
  optional `pinned: bool`. The unified `10+` pool no longer encodes role in the number itself, so the registry has to
  carry it.
- `sase workspace cleanup --stale` reaps any unclaimed workspace whose `last_used_at` is older than a configurable
  TTL (suggested default: 14 days for `role == axe`, never for `role == workflow-share` without `--include-shares`).
- Crash recovery walks the registry, drops entries whose `checkout_dir` no longer exists, and re-materializes entries
  with a live RUNNING claim but missing on-disk checkout.
- `git worktree prune` and `git worktree repair` should be invoked by the materializer when the worktree strategy is
  selected, so stale linked worktrees do not accumulate inside the primary repo's `.git/worktrees/`.

Today's behavior is implicitly "reuse the directory; clean it via `clean_workspace` before reassigning"
(`src/sase/running_field/_workspace.py:92`). The from-scratch model keeps that hot-path behavior and adds a slower,
explicit reaper for cold workspaces.

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
6. Update project-name and bead resolution to stop depending on sibling path recognition except as a legacy fallback;
   drop a small `.sase/checkout.json` marker inside every managed checkout so CWD-based inference works without
   filename pattern matching.
7. Add cleanup and repair commands before flipping the default away from adjacent.
8. Offer a **symlink transition mode** as the bridge step: when migrating an existing project, leave
   `../project_<N>` in place as a symlink pointing at the managed store path, so muscle memory (`cd ../project_102`),
   shell history, and editor recents keep working through the deprecation window. Remove the symlink on workspace
   cleanup or when the user runs `sase workspace migrate --finalize`.
9. Flip new installs to `xdg-state`; leave existing projects on adjacent unless the user opts into migration.

The safe rollout is "new config path first, default later." Existing long-lived workspaces and scripts probably depend
on `../project_101`.

## Decision Matrix

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| Keep sibling default | Simple, visible, compatible with current code | Clutters source parents; path convention leaks everywhere; encourages sibling scans | Good compatibility mode, poor default |
| Hidden global state root | Clean source parents; explicit ownership; central cleanup | Needs list/open/repair commands; migration work | Best default |
| Per-project `.sase/workspaces` under primary repo | Keeps state near project but not sibling clutter | Risks nesting generated clones inside repo trees; easy to accidentally commit/scan | Avoid |
| Git linked worktrees in managed root | Efficient and standard Git lifecycle | Shared refs/config constraints; same-branch policy complexity | Worth evaluating after path abstraction |
| Shared-alternates clones in managed root | Tiny disk cost; full refs/config isolation | `git repack -ad` on primary can corrupt dependents; users editing the primary repo break agents | Viable with strict primary-repo guardrails |
| Symlink farm: managed store + adjacent symlinks | Preserves muscle memory and editor recents during migration | Two paths to the same checkout; symlink-aware tools needed; clutter returns | Best transition strategy, not a long-term default |
| Temp directory workspaces | No persistent clutter | Bad for long agents, debugging, crash recovery, dependency reuse | Not suitable for normal SASE agents |

## Risks And Counterarguments

Moving execution state out of `~/projects/...` is not free. Honest counterarguments:

- **Discoverability loss.** Some agents fail in ways that are easiest to debug by `cd ../sase_102 && git status`. A
  hidden store means users must learn a new command (`sase workspace open 102`). Mitigation: short shell helper
  (`saswd 102` or `cd $(sase workspace path 102)`), plus a TUI keymap that opens the workspace path in the user's
  default editor.
- **Backup story changes both ways.** Adjacent layout over-captures execution state in user backups; managed-store
  layout *under*-captures it for users who want to inspect a crashed agent's working tree the next morning. The fix is
  documentation: `~/.local/state/sase/workspaces/` is included by Borg/Restic profiles for users who want it, and
  excluded by default for users who do not.
- **Snapshot semantics.** A BTRFS/ZFS snapshot of `~/projects` today freezes every workspace atomically. With a
  managed store on a different subvolume, snapshots become two-step. This is rarely load-bearing, but worth a note.
- **NFS / network home directories.** Some users have `$HOME` on NFS while `~/projects` is on local SSD. Moving
  workspaces to `~/.local/state` could put them on slow storage. The config knob (`workspace.root`) handles this; the
  default heuristic should detect a network-mounted `$HOME` and fall back to a local path.
- **Sandboxing tools (e.g. devcontainers, Toolbx, Distrobox).** These often bind-mount `~/projects` into the
  container. Workspaces under `~/.local/state` will not be visible unless the user adds another mount. Document this
  and offer a `workspace.root: adjacent` override for containerized workflows.
- **The `cd ..` pattern is genuinely useful.** Power users navigate between siblings reflexively. The symlink
  transition mode addresses this for the first release; long-term, a `sase ws shell 102` command plus shell prompt
  integration (`$SASE_WORKSPACE_NUM`) covers the remaining ergonomics.

None of these are blockers, but together they explain why "just move everything to XDG state" is too blunt a
prescription. The right framing is configurable default + ergonomics surface, not unconditional relocation.

## Test Plan

Tests that lock in the new contract should cover:

- `WorkspaceStore.resolve(project_key, workspace_num)` returns identical paths to the legacy `_get_git_clone_dir`
  under the `adjacent` policy (regression parity).
- `xdg-state` policy produces a path under the configured root and is stable across processes.
- Cross-device materialization falls back from `--local` to a non-hardlinked clone with the same final checkout
  contents.
- Project-key collision: two repos with the same basename but different remotes do not share a workspace pool.
- Registry survives an unexpected process kill mid-materialization (write-then-rename, or fsync-then-link, on the
  registry file).
- `sase workspace cleanup --stale` reaps an unclaimed `role == axe` workspace older than the TTL but leaves a pinned
  workspace alone.
- Allocator skips `0-9` and starts assigning at `10`; `#0` consistently resolves to the configured primary working
  tree without ever appearing as a free slot.
- The CWD-based inference in `bead/project_name.py` finds the correct project from a managed checkout path using the
  `.sase/checkout.json` marker, without relying on `<project>_<N>` basename matching.
- Sibling-repo resolver, when run with `workspace.root: xdg-state`, materializes both primary and sibling under the
  managed root and keeps their workspace numbers aligned.
- Symlink transition mode: `../project_102` is a symlink into the managed store; deleting the symlink does not delete
  the canonical checkout; `sase workspace cleanup` removes both.
- Inherited env scrub: a spawned child does not see a stale `SASE_*_WORKSPACE_DIR` from a different parent
  workspace's adjacent path when the policy has switched to `xdg-state`.

## Final Recommendation

If doing it again from scratch, model SASE workspaces as managed application state:

- numeric IDs remain the user-facing identity, with `#0` reserved for the primary checkout and claim slots starting
  at `#10` in a single unified pool;
- physical paths are resolved through a `WorkspaceStore`;
- default storage for claim slots is `$XDG_STATE_HOME/sase/workspaces/<project-key>/<project>_<num>/checkout`, while
  `#0` resolves back to the user's existing primary working tree;
- adjacent `primary_<num>` directories remain an explicit compatibility/debugging policy;
- provider plugins materialize checkouts into caller-supplied target directories;
- claims and artifacts store enough resolved-path metadata that no caller has to infer paths by suffix.

This keeps the operational strengths of today's design while removing the main product cost: generated execution
checkouts filling the same parent directory as the user's real projects.

## Related Research

- [`sibling_repos_workspace_generalization.md`](./sibling_repos_workspace_generalization.md): first-class sibling
  repo configuration; co-evolves with the `WorkspaceStore` proposed here.
- [`prompt_deterministic_vcs_workspace_launch.md`](./prompt_deterministic_vcs_workspace_launch.md): the
  prompt-deterministic launch invariant that any new path resolver must continue to satisfy.
- [`multi_machine_sync.md`](./multi_machine_sync.md): confirms that workspace clones are explicitly out of scope for
  cross-machine sync, which simplifies the managed-store design.
