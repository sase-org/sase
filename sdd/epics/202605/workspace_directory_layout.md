---
bead_id: sase-3p
tier: epic
status: done
---

# Workspace Directory Layout Implementation Plan

## Goal

Implement the managed workspace directory layout recommended by
`sdd/research/202605/workspace_directory_layout_research.md`, including a new `sase workspace` CLI surface.

The target architecture is:

- workspace `#0` resolves to the primary checkout from the ProjectSpec `WORKSPACE_DIR`;
- claim-allocated workspaces use one unified numeric pool starting at `#10`;
- physical workspace paths are resolved through a first-class `WorkspaceStore` instead of by appending `_<num>` to the
  primary path;
- default rollout is compatibility-first: land the abstraction with `adjacent` parity, then enable `xdg-state`/managed
  roots, then add migration and cleanup ergonomics;
- provider plugins materialize checkouts at caller-supplied target directories;
- CWD/project inference works inside managed checkouts without relying on sibling basename parsing;
- `sase workspace` exposes list/path/open/cleanup/repair operations.

Each phase below is sized for a distinct agent instance. Phases should land in order unless explicitly marked
parallel-safe.

## Phase 1: WorkspaceStore Core With Adjacent Parity

Owns:

- `src/sase/workspace_store.py` or `src/sase/workspace_provider/store.py`
- focused tests under `tests/workspace_provider/`
- minimal config access helpers, without changing runtime defaults

Implement a pure-Python `WorkspaceStore` and related value objects:

- `WorkspacePath` with `project_key`, `workspace_num`, `root_dir`, `checkout_dir`, `materialization`, `generation`, and
  display label fields.
- Root policy resolution for:
  - `adjacent`
  - `xdg-state`
  - absolute paths
  - `SASE_WORKSPACE_ROOT` override
- Cross-platform state-root helper:
  - Linux: `$XDG_STATE_HOME/sase/workspaces`, falling back to `~/.local/state/sase/workspaces`
  - macOS: `~/Library/Application Support/sase/workspaces`
  - Windows: `%LOCALAPPDATA%\sase\workspaces`
- Project-key derivation:
  - prefer a single Git remote slug when available;
  - otherwise use a primary-path slug plus short hash;
  - allow explicit `workspace.project_key` in config.
- Adjacent parity path resolution:
  - current primary workspace number `1` remains the primary path during this compatibility phase;
  - secondary adjacent paths match current `_get_git_clone_dir()` output.

Add config schema/defaults for:

```yaml
workspace:
  root: adjacent
  project_key: ""
  cleanup_ttl_days: 14
```

Do not yet change allocation ranges or runtime call sites.

Tests:

- adjacent policy returns exactly the old primary and `primary_<num>/` paths;
- xdg-state policy returns stable paths under a configured fake state root;
- same basename in two different primary paths produces different project keys;
- explicit `workspace.project_key` wins;
- `SASE_WORKSPACE_ROOT` overrides config.

Acceptance criteria:

- `just test tests/workspace_provider/test_workspace_store.py` passes;
- existing `ensure_git_clone(primary, num)` tests still pass unchanged.

## Phase 2: Provider Materialization Target Paths

Owns:

- `src/sase/workspace_provider/utils.py`
- `src/sase/workspace_provider/_hookspec.py`
- `src/sase/workspace_provider/_registry.py`
- built-in workspace plugins
- direct `ensure_git_clone()` call sites that can be safely routed through the new API

Refactor git clone materialization so path choice is separated from clone creation:

- keep `ensure_git_clone(primary_workspace_dir, workspace_num)` as a compatibility wrapper;
- add a target-aware function such as `ensure_git_clone_at(primary_workspace_dir, workspace_num, target_checkout_dir)`;
- make provider hooks capable of receiving or deriving a `WorkspacePath`;
- update `BareGitWorkspacePlugin.ws_get_workspace_directory()` to resolve via `WorkspaceStore`, then materialize into
  `WorkspacePath.checkout_dir`;
- keep `CdWorkspacePlugin` direct and non-claiming.

Handle direct callers:

- `src/sase/scripts/git_setup.py`
- `src/sase/ace/scheduler/workflows_runner/starter.py`
- fallback logic in `src/sase/running_field/_workspace.py`

These should call a shared resolver/materializer helper rather than rebuilding path rules locally.

Tests:

- compatibility wrapper preserves old behavior under `workspace.root: adjacent`;
- target-aware materializer creates/validates the explicit checkout path;
- corrupt checkout replacement still works;
- direct git setup and CRS workflow paths use the same helper.

Acceptance criteria:

- `just test tests/workspace_provider/test_utils.py tests/test_running_field_operations.py` passes;
- no call site outside the compatibility wrapper computes `primary_<num>` by string concatenation.

## Phase 3: Registry And Checkout Marker

Owns:

- registry read/write implementation under the workspace store module
- marker helpers for `.sase/checkout.json`
- tests for crash-safe registry persistence

Add a registry per managed project root:

```json
{
  "schema_version": 1,
  "project_key": "...",
  "primary_workspace_dir": "...",
  "workspaces": {
    "0": {
      "checkout_dir": "...",
      "materialization": "primary",
      "role": "primary"
    }
  }
}
```

Implementation requirements:

- write registry updates atomically;
- include `created_at`, `last_used_at`, `role`, `pinned`, and `materialization` for managed workspaces;
- always register primary workspace `#0`;
- write `.sase/checkout.json` inside managed checkouts with enough metadata to infer project name, project key,
  workspace number, primary workspace path, and registry path;
- do not write marker files into the user's primary checkout without a separate compatibility decision. The primary
  remains discoverable from ProjectSpec.

Tests:

- registry initializes with primary `#0`;
- registry update survives partial write simulation;
- marker read returns the expected project context;
- deleting a checkout leaves a registry entry that repair/cleanup can detect.

Acceptance criteria:

- registry exists for xdg-state or absolute-root policies;
- adjacent policy can still operate without requiring registry for parity, but may write one if implementation is
  simpler and non-invasive.

## Phase 4: Allocation Range Migration To Unified Pool

Owns:

- `src/sase/running_field/_workspace.py`
- `src/sase/running_field/_operations.py`
- launch/deferred workspace allocation call sites
- tests currently expecting `100-199`

Change claim allocation semantics:

- workspace `#0` remains the deferred placeholder and primary checkout identity, depending on context;
- allocator for claim-backed workspaces starts at `10`;
- reserve `1-9`;
- replace axe-specific default range `100-199` with unified claim range `10-999` or a documented bounded range chosen
  for current Rust helper compatibility;
- preserve explicit `min_workspace`/`max_workspace` arguments for tests and advanced callers.

Update hot paths:

- `claim_next_axe_workspace()` defaults;
- `get_first_available_axe_workspace()` defaults;
- `agent.launch_executor_workspace._preclaim_axe_workspace()`;
- `axe.run_agent_phases.claim_deferred_workspace()`;
- workflow/share allocation paths that still call `get_first_available_workspace()`.

Keep the Rust boundary narrow. The current Rust-backed claim allocator already receives min/max values, so this phase
should not move path resolution into Rust. Only involve `../sase-core` if a claim model change becomes necessary.

Tests:

- empty project allocates `#10`;
- occupied `#10` allocates `#11`;
- `#0` duplicate deferred claims remain allowed;
- explicit legacy test ranges still work;
- launch executor and deferred `%wait` tests expect `#10+` where defaults are used.

Acceptance criteria:

- no default code path allocates `#100` as the first new workspace;
- user-facing suffix labels use `<project>_<num>` for managed checkouts.

## Phase 5: Runtime Integration For Managed Roots

Owns:

- `src/sase/running_field/_workspace.py`
- `src/sase/agent/launch_executor_workspace.py`
- `src/sase/axe/run_agent_phases.py`
- TUI/file-panel path lookup call sites that resolve workspace directories

Switch runtime workspace resolution to `WorkspaceStore`:

- `get_workspace_directory(project, workspace_num)` and `get_workspace_directory_for_num()` resolve through the
  store/provider materializer;
- non-primary claim paths clean the resolved checkout before use;
- primary lookup maps `#0` and legacy `#1` carefully:
  - new store API uses `#0` for primary;
  - compatibility wrappers may continue accepting `#1` where older call sites still mean "primary";
- launch result, preallocated env, `SASE_ACTIVE_PROJECT_DIR`, and artifact metadata carry the resolved checkout path.

Update display code only where it currently assumes suffix paths. Keep TUI labels numeric (`#10`) and reveal full paths
where existing detail views already show workspace paths.

Tests:

- xdg-state config launches/materializes under the managed root;
- adjacent config remains byte-for-byte compatible for existing path tests;
- stale inherited `SASE_*_WORKSPACE_DIR` values are scrubbed and replaced by the resolved managed checkout path;
- file panel and notification path lookup can resolve an agent's workspace number after restart.

Acceptance criteria:

- setting `workspace.root: xdg-state` in a test config makes agent workspace checkouts appear under the managed store;
- existing adjacent default behavior is still available.

## Phase 6: CWD Project Inference Without Sibling Parsing

Owns:

- `src/sase/bead/project_name.py`
- `src/sase/bead/workspace.py`
- workspace provider `ws_get_workspace_name()` fallback behavior
- bead workspace resolution tests

Make managed checkout inference marker-first:

- when CWD is inside a managed checkout, read nearest `.sase/checkout.json`;
- use marker metadata to return project name and primary workspace path;
- fall back to provider detection and existing sibling-pattern scanning for legacy adjacent workspaces;
- tighten `_is_workspace_variant()` so legacy fallback only accepts numeric suffixes where feasible, without breaking
  documented variant-to-variant tests unless product decides to drop that legacy behavior.

Tests:

- managed checkout marker resolves project name from xdg-state path;
- bead directory lookup from managed checkout prefers current checkout bead store when present;
- fallback sibling scan still works for adjacent legacy directories;
- malformed marker is ignored with fallback behavior.

Acceptance criteria:

- `sase bead ...` from a managed checkout resolves the owning project without depending on `<project>_<num>` being
  adjacent to the primary checkout.

## Phase 7: `sase workspace` CLI

Owns:

- new `src/sase/main/parser_workspace.py`
- new `src/sase/main/workspace_handler.py`
- `src/sase/main/parser.py`
- `src/sase/main/entry.py`
- docs and CLI tests

Add:

```bash
sase workspace list [--project PROJECT] [--json]
sase workspace path WORKSPACE_NUM [--project PROJECT]
sase workspace open WORKSPACE_NUM [--project PROJECT] [--print]
sase workspace cleanup --stale [--project PROJECT] [--include-shares] [--dry-run]
sase workspace repair [--project PROJECT] [--dry-run]
```

Behavior:

- `list` reads the registry and also shows primary `#0`;
- `path` prints the checkout path, materializing when appropriate only if the selected workspace already has a claim or
  registry entry;
- `open` should be conservative: print the path by default if no editor/shell integration exists. If invoking an editor
  is implemented, require an explicit config or environment command;
- `cleanup --stale` removes unclaimed stale managed checkouts older than the configured TTL and removes transition
  symlinks if present;
- `repair` drops registry entries whose checkout is gone and re-materializes checkouts for live RUNNING claims.

Tests:

- parser dispatch and usage errors;
- human and JSON `list`;
- `path 0` prints primary checkout;
- `path 10` prints managed checkout from registry;
- dry-run cleanup reports without deleting;
- repair handles missing checkout entries.

Acceptance criteria:

- `sase workspace path 0` and `sase workspace list --json` work in a registered project;
- docs mention the new command and environment/config knobs.

## Phase 8: Migration And Symlink Transition

Owns:

- workspace CLI migration subcommands if implemented in this release
- cleanup interaction with transition symlinks
- docs

Add an opt-in migration path:

```bash
sase workspace migrate --project PROJECT --to xdg-state [--symlink-transition]
sase workspace migrate --finalize --project PROJECT
```

Migration behavior:

- leave existing adjacent checkouts in place unless the user opts in;
- for `--symlink-transition`, create `../project_<num>` symlinks to the managed checkout path when a managed checkout is
  materialized;
- cleanup removes both canonical managed checkout and transition symlink;
- finalize removes transition symlinks after the user has adapted workflows.

Tests:

- symlink points to managed checkout;
- deleting symlink does not delete canonical checkout;
- cleanup removes symlink and target for stale workspaces;
- migration refuses to overwrite a real adjacent directory.

Acceptance criteria:

- existing projects remain on `adjacent` unless explicitly migrated;
- new installs can later flip the default without stranding old projects.

## Phase 9: Documentation And Default Flip Readiness

Owns:

- `docs/workspace.md`
- `docs/configuration.md`
- `docs/project_spec.md`
- release notes or migration guide location used by this repo

Document:

- `workspace.root` values and platform defaults;
- `SASE_WORKSPACE_ROOT`;
- numeric identity changes (`#0` primary, `#10+` claims, `1-9` reserved);
- `sase workspace` workflows;
- backup/container/NFS caveats from the research doc;
- adjacent compatibility and migration.

Do not flip default to `xdg-state` until:

- CLI observability exists;
- cleanup/repair exists;
- managed CWD inference is reliable;
- symlink transition behavior is either implemented or explicitly deferred;
- sibling repo resolver, if present by then, uses the same `WorkspaceStore`.

Acceptance criteria:

- docs match CLI behavior;
- config schema and docs agree;
- a final integration pass can choose whether this release keeps `workspace.root: adjacent` or flips new projects to
  `xdg-state`.

## Cross-Cutting Risks

- Some direct call sites use `ensure_git_clone()` rather than the provider registry. Phase 2 must remove or wrap these
  before managed roots are considered complete.
- `#0` already means deferred workspace placeholder in RUNNING rows. The plan preserves that behavior but requires
  careful wording: primary checkout is identity `#0` in the store, while deferred launches can temporarily claim `#0`
  without owning the primary checkout.
- `WORKSPACE_DIR` remains the primary checkout source of truth. Do not rewrite it to the managed store.
- Rust owns claim parsing and allocation over a caller-provided range. Avoid duplicating Rust claim semantics in Python;
  only change Rust if claim metadata must grow to include `workspace_dir`.
- Existing tests and docs often assume first agent workspace is `#100`. The allocation migration should be one focused
  phase to avoid half-updated expectations.
- Sibling repository support must call into `WorkspaceStore` when it exists. If sibling repo work lands first, add it as
  a follow-up owner in Phases 5 and 8.

## Suggested Verification Matrix

Run targeted tests inside each phase, then before handoff run:

```bash
just install
just check
```

Additional smoke tests after Phase 7:

```bash
sase workspace list --json
sase workspace path 0
sase workspace path 10
SASE_WORKSPACE_ROOT="$(mktemp -d)" sase workspace list --json
```

Manual smoke after runtime integration:

1. Configure a test project with `workspace.root: adjacent`; launch an agent and confirm the checkout path remains
   `../project_<num>/`.
2. Configure the same project with `workspace.root: xdg-state`; launch an agent and confirm the checkout path is under
   the managed state root.
3. Run a bead command from inside the managed checkout and confirm it resolves the owning project.
4. Run `sase workspace cleanup --stale --dry-run` and confirm it does not touch active RUNNING claims.
