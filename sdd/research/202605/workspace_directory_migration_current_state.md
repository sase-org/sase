---
create_time: 2026-05-22
updated_time: 2026-05-22
status: research
---

# Workspace Directory Migration Current State

## Question

We appear to have implemented work to move SASE workspace directories out of adjacent `sase_<N>` sibling checkouts and
into a SASE-managed directory, but current runs still use adjacent workspace directories. What work was implemented, and
how do workspace directories work now?

## Short Answer

The work exists, the epic (`sase-3p`) is marked `done`, but the implementation deliberately did not flip the runtime
default.

Two separate migrations are easy to conflate:

1. **ProjectSpec/state migration to `~/.sase/`.** SASE project files, artifacts, chats, notifications, and related
   state moved under `~/.sase/`, especially `~/.sase/projects/<project>/`. This is the `.gp` → `.sase` ProjectSpec
   migration and durable-state layout. It is unrelated to where Git checkouts physically live.
2. **Checkout workspace directory migration.** SASE implemented an opt-in managed checkout root through
   `workspace.root`, `WorkspaceStore`, a per-project `registry.json`, `.sase/checkout.json` markers, and
   `sase workspace migrate`. This work does **not** default to `~/.sase`. The documented managed default is
   `xdg-state`, which resolves to `~/.local/state/sase/workspaces/...` on Linux unless overridden with an absolute path
   or `SASE_WORKSPACE_ROOT`.

On this machine and in the checked-in defaults, `workspace.root` is still `adjacent`, no user/project/chezmoi config
overrides it, and `SASE_WORKSPACE_ROOT` is not set. The runtime therefore still deliberately materializes numbered
checkouts next to the primary checkout:

```text
/home/bryan/projects/github/sase-org/sase
/home/bryan/projects/github/sase-org/sase_10
/home/bryan/projects/github/sase-org/sase-core_10
/home/bryan/projects/github/sase-org/sase-github_10
```

No managed checkout registry or `.sase/checkout.json` markers were found under `~/.sase`,
`~/.local/state/sase/workspaces`, or another obvious `*/sase/workspaces` root on this machine.

## Implementation History

The managed-workspace work landed as the `sase-3p` workspace directory layout epic. Source design is
[`workspace_directory_layout_research.md`](./workspace_directory_layout_research.md) and the implementation plan is
[`sdd/epics/202605/workspace_directory_layout.md`](../../epics/202605/workspace_directory_layout.md) (`status: done`).

Phase commits:

| Commit       | Phase | Summary                                                                                |
| ------------ | ----- | -------------------------------------------------------------------------------------- |
| `041e3bf35`  | 1     | `WorkspaceStore` core with adjacent parity, config schema fields, key derivation.      |
| `532a62d9a`  | 2     | Target-aware Git materialization: `_ensure_git_clone_at` separates path from clone.    |
| `9cceb103b`  | 3     | Managed workspaces registry plus `.sase/checkout.json` checkout markers.               |
| `c73bee66d`  | 4     | Allocation migrated to a unified claim pool: `#0` primary, `#1`–`#9` reserved, `#10+`. |
| `18a5f494b`  | 5     | Runtime resolution routed through `WorkspaceStore` (incl. legacy `#1` normalization).  |
| `3a75c7370`  | 6     | Marker-first CWD project inference before sibling-basename scanning.                   |
| `8207346ce`  | 7     | `sase workspace` CLI (`list`, `path`, `open`, `cleanup`, `repair`).                    |
| `8145a6843`  | 8     | `sase workspace migrate --to xdg-state` plus `--symlink-transition` and `--finalize`.  |
| `2147ba8c7`  | 9     | Workspace docs (`docs/workspace.md`, `docs/configuration.md`, `docs/project_spec.md`). |
| `d7ed0ce1f`  | —     | Closed the epic and removed obsolete helper code.                                      |
| `986686485`, `a1f319117` | — | Doc refresh/clarification follow-ups.                                          |
| `d760bf9ae`  | —     | Preserve managed workspace markers during migration moves.                             |

Related but separate `.sase` ProjectSpec migration commits (state-only, not checkout layout):

| Commit                   | Summary                                                                          |
| ------------------------ | -------------------------------------------------------------------------------- |
| `55a961a40`              | Migrated main runtime paths to project specs under `~/.sase/projects`.           |
| `88bd937b9`              | Finished `.sase` migration across TUI/tests/docs.                                |
| `3d25c0eb2`, `c9bff699e` | Hardened legacy `.gp` → canonical `.sase` migration behavior.                    |

## Code Map

| Responsibility                       | File                                                                | Notes                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Pure path resolver                   | `src/sase/workspace_provider/store.py`                              | `WorkspaceStore`, `WorkspacePath`, root policy resolution, project-key derivation.          |
| Managed registry                     | `src/sase/workspace_provider/registry.py`                           | Atomic write-then-rename `registry.json`; reconciles primary `#0` on every load.            |
| Checkout marker                      | `src/sase/workspace_provider/marker.py`                             | `.sase/checkout.json` writer/reader and ancestor walk (`find_marker_from_cwd`).             |
| Materializer                         | `src/sase/workspace_provider/utils.py`                              | `ensure_workspace_checkout`; calls `_ensure_git_clone_at`, then registry + marker writes.   |
| Allocator                            | `src/sase/running_field/_workspace.py`                              | `UNIFIED_MIN_WORKSPACE=10`, `UNIFIED_MAX_WORKSPACE=999`, reserved `#1`–`#9`.                |
| `sase workspace` CLI                 | `src/sase/main/workspace_handler.py` + `parser_workspace.py`        | `list`, `path`, `open`, `cleanup`, `repair`, `migrate`.                                     |
| Sibling-repo resolver                | `src/sase/sibling_repos.py`                                         | Calls `ensure_workspace_checkout` only when `materialize=True`; otherwise suffix fallback.  |
| Marker-aware CWD inference           | `src/sase/bead/project_name.py`                                     | `infer_project_name_from_cwd` checks marker, then provider hook, then `~/.sase/projects/*`. |
| Config defaults                      | `src/sase/default_config.yml`                                       | `workspace.root: adjacent`, `project_key: ""`, `cleanup_ttl_days: 14`.                      |
| Workspace docs                       | `docs/workspace.md`                                                 | Full reference for layout, CLI, and caveats.                                                |
| Tests                                | `tests/workspace_provider/`, `tests/main/test_workspace_handler_*`, `tests/test_runtime_workspace_managed_roots.py` | Store, registry, marker, CLI subcommands, runtime parity. |

## Current Runtime Model

### Project State (`~/.sase/`)

Project-level state lives under `~/.sase/projects/<project>/`.

- Canonical active ProjectSpec: `~/.sase/projects/<project>/<project>.sase`
- Canonical archive ProjectSpec: `~/.sase/projects/<project>/<project>-archive.sase`
- Legacy `.gp` files remain readable via `preferred_project_spec_path` fallback.
- `WORKSPACE_DIR:` in the ProjectSpec points to the **primary checkout** and is intentionally never rewritten to a
  managed workspace root.

The local `sase` ProjectSpec still points at the primary checkout:

```text
~/.sase/projects/sase/sase.gp:
WORKSPACE_DIR: /home/bryan/projects/github/sase-org/sase/
```

That is the design: workspace `#0` resolves to this primary checkout in every root policy.

### Workspace Numbers

`src/sase/running_field/_workspace.py` defines the allocation contract:

| Number    | Meaning                                                                                                                                              |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `#0`      | Primary checkout (`WORKSPACE_DIR`) and the deferred-launch placeholder.                                                                              |
| `#1`      | Legacy primary alias under adjacent policy. `WorkspaceStore` and `ensure_workspace_checkout` normalize `#1` → `#0` so non-adjacent roots stay safe.  |
| `#1`–`#9` | Reserved. The default allocator never hands these out (`UNIFIED_MIN_WORKSPACE = 10`).                                                                |
| `#10`+    | Unified claim pool. Workflow shares and axe agent launches all allocate from `10`–`999` (`UNIFIED_MAX_WORKSPACE`) unless a caller passes overrides.  |

The pre–sase-3p split (workflow shares `2`–`99`, axe agents `100`–`199`) is gone. The legacy ranges are still
accessible by passing explicit `min_workspace` / `max_workspace` to `get_first_available_workspace` /
`get_first_available_axe_workspace` (used in tests).

### Root Policy

`WorkspaceStore` (`src/sase/workspace_provider/store.py`) supports four resolution modes:

| Policy/Mode             | Layout                                                                                                                                    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `adjacent` (default)    | Non-primary checkouts at `<primary>_<num>/`. Byte-for-byte parity with the pre-3p `_get_git_clone_dir` output.                            |
| `xdg-state`             | Managed root under the platform state directory, namespaced by `project_key`: `<state-root>/<project_key>/<project>_<num>/`.              |
| absolute path           | Treat the configured path as the managed-root base: `<configured-root>/<project_key>/<project>_<num>/`.                                   |
| `SASE_WORKSPACE_ROOT`   | Environment override. Always coerced to `policy="absolute"` and namespaced as `<env-root>/<project_key>/<project>_<num>/`.                |

Platform-specific `xdg-state` resolution:

| OS      | Root                                                                                                |
| ------- | --------------------------------------------------------------------------------------------------- |
| Linux   | `${XDG_STATE_HOME:-~/.local/state}/sase/workspaces/<project_key>/`                                  |
| macOS   | `~/Library/Application Support/sase/workspaces/<project_key>/`                                      |
| Windows | `%LOCALAPPDATA%\sase\workspaces\<project_key>\` (falls back to `~/AppData/Local/...` when unset).   |

The `project_key` is derived once per `WorkspaceStore` instance:

1. Explicit `workspace.project_key` from merged config (slugified) wins.
2. Otherwise, if the primary repo has exactly one Git remote, use a slug of `<host>_<owner>_<repo>` derived from
   `_normalize_git_url`. This handles SSH (`git@host:owner/repo`) and URL (`scheme://host/path`) remote forms.
3. Otherwise, fall back to `<slug-of-basename>-<sha256(abs_primary_path)[:8]>` so two distinct local checkouts of a
   project with the same basename never collide under the same managed root.

The current default config in `src/sase/default_config.yml`:

```yaml
workspace:
  root: adjacent
  project_key: ""
  cleanup_ttl_days: 14
```

`workspace.root` is not overridden in:

- the repo-local `sase.yml`,
- `~/.config/sase/sase.yml`,
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`,

and `SASE_WORKSPACE_ROOT` is unset in the inspected shell. Confirmed empirically: `ls ~/.local/state/sase` returns no
such directory.

### Adjacent Layout (current behavior)

With `workspace.root: adjacent`, SASE preserves the historical layout:

```text
primary:  /home/bryan/projects/github/sase-org/sase/
#10:      /home/bryan/projects/github/sase-org/sase_10/
#11:      /home/bryan/projects/github/sase-org/sase_11/
```

This is the active behavior on this machine. Existing adjacent workspace directories are present for `sase`,
`sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim`.

### Managed Root Layout (opt-in)

With `workspace.root: xdg-state` on Linux, non-primary checkouts resolve under:

```text
${XDG_STATE_HOME:-~/.local/state}/sase/workspaces/<project_key>/<project>_<num>/
```

With an absolute `workspace.root` (any path beginning with `/`):

```text
<configured-root>/<project_key>/<project>_<num>/
```

`SASE_WORKSPACE_ROOT=/some/root` behaves like an absolute managed-root base:

```text
/some/root/<project_key>/<project>_<num>/
```

Despite the user-facing phrase "move to `~/.sase`", the implemented `xdg-state` default is not `~/.sase/workspaces`; it
is `~/.local/state/sase/workspaces`. Putting checkouts under `~/.sase/workspaces` would require an explicit absolute
path (and on POSIX that path must be absolute, e.g. `/home/<user>/.sase/workspaces`, since `WorkspaceStore` rejects
non-keyword non-absolute values).

### Registry And Checkout Markers

For non-adjacent roots, SASE records managed checkouts atomically in:

```text
<managed-root>/registry.json
```

`registry.json` schema (`SCHEMA_VERSION = 1`):

```json
{
  "schema_version": 1,
  "project_key": "...",
  "primary_workspace_dir": "...",
  "workspaces": {
    "0":   { "checkout_dir": "...", "materialization": "primary",   "role": "primary", "pinned": true,  ... },
    "10":  { "checkout_dir": "...", "materialization": "git-clone", "role": "claim",   "pinned": false, ... }
  }
}
```

Each managed non-primary checkout also writes:

```text
<checkout>/.sase/checkout.json
```

Marker fields (`CheckoutMarker`, schema_version 1): `project_name`, `project_key`, `workspace_num`,
`primary_workspace_dir`, `registry_path`. The marker lets commands run from inside a managed checkout infer the project
without sibling-basename parsing.

Important invariants:

- **Marker writes are skipped for the primary checkout.** `write_marker` short-circuits when
  `workspace_path.workspace_num == PRIMARY_WORKSPACE_NUM` or `materialization == "primary"`. The primary's identity is
  recorded only in `WORKSPACE_DIR`. This deliberately avoids forcing a config decision about whether the primary
  should ever look "managed".
- **Adjacent root policy never writes registry or markers.** `_record_managed_workspace` in
  `workspace_provider/utils.py` short-circuits when `store.root_policy == "adjacent"`. Adjacent layout retains its
  legacy behavior exactly.
- **`load_or_init_registry` is reconciliatory.** Every load rewrites `project_key`, `primary_workspace_dir`, and
  `schema_version` from the current `WorkspaceStore`, and always (re-)inserts a `#0` entry with `role="primary"` and
  `pinned=True`. The on-disk registry is overwritten on the next save.
- **Atomic writes.** Both `registry.json` and `checkout.json` use tempfile + `fsync` + `os.replace` so concurrent
  `sase` processes never observe a half-written file.

### Subtle Behaviors

These are easy to miss when reading the public docs:

1. **Legacy `#1` normalization.** `ensure_workspace_checkout` maps `workspace_num == 1` to `0` before resolving, and
   `WorkspaceStore.resolve` additionally treats `#1` as primary under `adjacent` (`LEGACY_PRIMARY_WORKSPACE_NUM = 1`).
   Without this, a config flip to `xdg-state` would try to materialize a managed `proj_1/` clone for every legacy
   primary lookup.
2. **`migrate --finalize` always uses xdg-state policy.** `_handle_migrate_finalize` builds a `WorkspaceStore` with
   `policy="xdg-state"` regardless of the project's configured root. It scans for adjacent symlinks (real symlinks
   whose name matches `<primary>_<num>`) and removes them. Projects migrated to an absolute managed root still get
   their adjacent transition symlinks removed because finalize keys off symlink presence, not registry policy.
3. **`migrate --to` accepts any non-adjacent policy.** The CLI is not restricted to literal `xdg-state`. It accepts
   absolute paths too; `migrate --to /tmp/managed-roots` materializes the managed root there. Only the literal value
   `adjacent` is rejected (with a non-zero exit) since it would not create a managed root.
4. **`cleanup` requires `--stale`.** `sase workspace cleanup` with no flags exits with status 2 and a usage hint. The
   command always preserves `#0` and any workspace number with an active RUNNING claim, and skips workflow-share
   entries unless `--include-shares` is passed.
5. **Generic-fallback materialization.** `running_field._workspace.get_workspace_directory` has a fallback for cases
   where no workspace provider plugin claims the project. If the ProjectSpec has a usable `WORKSPACE_DIR` and the
   directory exists, it routes the lookup through `ensure_workspace_checkout` directly. This keeps configured agent
   chops working when provider entry points are temporarily unavailable.
6. **Generation field is reserved.** `WorkspacePath.generation` and `WorkspaceEntry.generation` exist but are always
   `0` today. They are reserved for a future cache-invalidation/regeneration story.

### Materialization

`ensure_workspace_checkout(primary_workspace_dir, workspace_num, *, config=None, env=None)` is the single materializer
entrypoint. The flow is:

1. Normalize legacy `workspace_num == 1` to `0`.
2. Load merged config when not provided.
3. Build a `WorkspaceStore` for the primary directory.
4. Call `store.resolve(workspace_num)` to pick a `WorkspacePath` (pure, no I/O).
5. Call `_ensure_git_clone_at(primary, num, path.checkout_dir)` which validates an existing clone with `git status`,
   recreates corrupt clones, or runs `git clone <primary> <target>` and optionally restores the upstream origin URL
   via `git remote set-url origin`.
6. Best-effort `_record_managed_workspace(store, path)` → `record_workspace` + `write_marker`, only for non-adjacent
   roots and non-primary numbers. Failures are swallowed so a transient state-root permission error never blocks a
   workspace claim.

Direct call sites: the bare-git workspace plugin (`plugins/bare_git_workspace.py`), the generic fallback in
`running_field._workspace.get_workspace_directory`, the `sase workspace path/repair` CLI handlers, and
`sibling_repos._resolve_workspace_dir` when `materialize=True`.

The `sase-github` plugin similarly delegates numbered workspace creation to core `ensure_workspace_checkout`, so it
inherits managed-root support automatically once core is configured for it. Its docs
(`sase-github_10/docs/configuration.md:37–38`) still describe GitHub numbered workspaces only as
`<project>_<N>/` siblings — accurate for the current `adjacent` default but incomplete for managed roots.

### CWD-Based Project Inference

`bead/project_name.py:infer_project_name_from_cwd` resolves in a deliberate three-tier order:

1. **Marker (most precise).** `find_marker_from_cwd` walks from the CWD upward looking for `.sase/checkout.json`. The
   nearest marker wins; malformed or unreadable markers are ignored.
2. **Workspace provider hook.** `ws_get_workspace_name` from a registered workspace plugin. Returns the project name
   when the CWD is recognized by a provider (e.g. inside a known bare-git checkout) and the project's `.sase`
   spec exists.
3. **Project scan (legacy fallback).** `scan_projects_for_cwd` enumerates `~/.sase/projects/*` and checks whether the
   CWD is the primary `WORKSPACE_DIR` or a sibling whose basename matches `<project>_<N>` for that project. This is
   the only remaining sibling-basename matcher and exists only to support adjacent legacy layouts.

For managed checkouts the marker tier is authoritative; for adjacent layouts the marker tier always misses and the
scan tier takes over.

## `sase workspace` CLI

`src/sase/main/workspace_handler.py` implements the surface. All subcommands accept `-p/--project NAME`; without it the
project is inferred via the three-tier order above.

| Command                                                                | Purpose                                                                                                                                                  |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase workspace list [-j/--json]`                                      | Show registry/project view, including primary `#0`. Loads or initializes the registry on the fly.                                                        |
| `sase workspace path NUM`                                              | Print the checkout path. Materializes only when `NUM == 0`, the registry already has an entry for `NUM`, or `NUM` has an active RUNNING claim.           |
| `sase workspace open NUM`                                              | Currently delegates to `path`. `--print` is reserved for a future editor/shell integration.                                                              |
| `sase workspace cleanup -s/--stale [-n/--dry-run] [--include-shares]`  | Remove unclaimed managed checkouts older than `cleanup_ttl_days`. Also removes any transition symlink at the adjacent location.                          |
| `sase workspace repair [-n/--dry-run]`                                 | Drop registry entries whose checkout is gone; re-materialize missing registered checkouts that still have live RUNNING claims.                           |
| `sase workspace migrate --to <policy> [-s/--symlink-transition] [-n]`  | Move existing adjacent `<primary>_<num>` checkouts under a managed root and register them. `--to adjacent` is rejected. Exits non-zero on skipped paths. |
| `sase workspace migrate --finalize [-n/--dry-run]`                     | Remove leftover transition symlinks. Always uses `xdg-state` as the policy when constructing the target store; symlink detection is policy-agnostic.     |

Migration is explicitly opt-in. With `--symlink-transition`, SASE leaves adjacent `<primary>_<num>` symlinks pointing
at the managed checkout so older tooling that still walks `..` for siblings keeps working during a transition. The
migration refuses to overwrite a real directory at the managed destination and reports each refusal.

## Sibling Repos

The project-local `sase.yml` configures sibling repos:

```yaml
sibling_repos:
  - name: core
    path: ../sase-core
  - name: github
    path: ../sase-github
  - name: telegram
    path: ../sase-telegram
  - name: nvim
    path: ../sase-nvim
  - name: chezmoi
    path: ~/.local/share/chezmoi
    workspace:
      strategy: none
```

`sibling_repos.resolve_sibling_repos_for_project(...)` chooses a path per sibling using
`_resolve_workspace_dir(primary_dir, workspace_num, strategy, materialize)`:

| Inputs                                                  | Output                                                                                  |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `strategy="none"`                                       | The sibling's primary path. No numbered checkout.                                       |
| `workspace_num <= 1`                                    | The sibling's primary path.                                                             |
| `strategy="suffix"`, `materialize=True`, `num >= 2`     | `ensure_workspace_checkout(sibling_primary, num)`, which honors `workspace.root`.       |
| `strategy="suffix"`, `materialize=False`, `num >= 2`    | `_suffix_workspace_path(...)`: returns `<sibling_primary>_<num>/` **without consulting `WorkspaceStore`**. |

The `materialize=False` branch is the one residual place outside the store that still hand-rolls a `<primary>_<num>`
path. It is used by callers that need a deterministic, side-effect-free path string (for example, building prompt text
or env vars before any clone is created). Once a sibling is actually materialized, it goes back through
`ensure_workspace_checkout` and lands wherever `workspace.root` says it should — so this fallback only matters when
SASE has to print a managed path **before** materializing it. It is a known sharp edge if a future product decision
moves managed-root displays into pre-materialization paths.

Because the active config default is `adjacent`, the resolved sibling directories on this machine are adjacent
siblings: `sase-core_10`, `sase-github_10`, `sase-telegram_10`, and `sase-nvim_10`.

## Tests And Coverage

The workspace migration has dedicated test coverage:

| Test file                                                            | Coverage                                                                              |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `tests/workspace_provider/test_workspace_store.py`                   | Root policy resolution, project-key derivation, primary `#0`/`#1` normalization, env override. |
| `tests/workspace_provider/test_workspace_registry.py`                | Registry init, atomic save, primary reconciliation, entry add/remove, schema version. |
| `tests/workspace_provider/test_checkout_marker.py`                   | Marker write/read, primary skip, ancestor walk, malformed file handling.              |
| `tests/workspace_provider/test_utils.py`                             | Materialization parity, corrupt-clone recovery, registry/marker side-effects.         |
| `tests/main/test_workspace_handler_parser.py`                        | CLI argparse dispatch and usage errors.                                               |
| `tests/main/test_workspace_handler_list_path.py`                     | `list` (human + JSON), `path` with/without materialization.                           |
| `tests/main/test_workspace_handler_cleanup_repair.py`                | `cleanup --stale` dry-run/live, `repair` dropping and re-materialization.             |
| `tests/main/test_workspace_handler_migrate.py`                       | `migrate --to`, `--symlink-transition`, `--finalize`, refusal of overwrite.           |
| `tests/test_runtime_workspace_managed_roots.py`                      | End-to-end runtime behavior under managed roots (`xdg-state` config harness).         |
| `tests/test_bead/test_workspace_resolution.py`                       | Marker-first CWD inference; adjacent fallback through `scan_projects_for_cwd`.        |

## Why Managed Workspaces Are Not Being Used Here

The direct reasons:

1. **Default remains adjacent.** `src/sase/default_config.yml` sets `workspace.root: adjacent`. Phase 9 deliberately
   deferred the default flip until the sibling-repo resolver consumed `WorkspaceStore`.
2. **No local override is configured.** No `workspace.root: xdg-state` or absolute root in the repo-local, user, or
   chezmoi SASE config files.
3. **No environment override is present.** `SASE_WORKSPACE_ROOT` is unset in the current shell.
4. **No managed-root artifacts exist locally.** No `registry.json` or `.sase/checkout.json` markers under `~/.sase`,
   `~/.local/state/sase/workspaces`, or another obvious `*/sase/workspaces` path.
5. **Sibling resolver is partially through.** Sibling materialization now consumes `WorkspaceStore` whenever
   `materialize=True`, so the "sibling resolver readiness" gate that Phase 9 named is functionally cleared for the
   common case. The pre-materialization `materialize=False` fallback is the last remaining adjacent-coded path.

## Current Documentation/Memory Drift

Up to date:

- `README.md` documents `#0`, `#10+`, `workspace.root`, and the managed-root commands.
- `docs/workspace.md` has the detailed managed layout, the CLI, and the backup/container/NFS caveats.
- `docs/configuration.md` documents `workspace.root`, `project_key`, and `cleanup_ttl_days`.
- `docs/project_spec.md` separates primary `WORKSPACE_DIR` from managed numbered checkouts.

Stale or incomplete:

- `memory/short/workspaces.md` (always-loaded short-term memory) still describes agent runs only as ephemeral sibling
  `sase_<N>` clones. Accurate for today's default but silent about managed roots.
- Generated SASE skill docs in chezmoi (`dot_claude/`, `dot_codex/`, `dot_gemini/`, `dot_opencode/`, `dot_qwen/`) all
  contain `sase_agents_status/SKILL.md` saying `workspace_num` resolves to `<parent-of-this-repo>/sase_<N>/`. They
  should mention the managed-root layout once the default is closer to flipping.
- `sase-github_10/docs/configuration.md:37–38` still describes GitHub numbered workspaces only as
  `<project>_<N>/` siblings. It delegates to `ensure_workspace_checkout`, so it inherits managed roots automatically.
- Several pre-3p epic specs under `sdd/epics/202602/` describe the old adjacent-only contract; those are historical
  artifacts and likely should be left as-is.

## How To Opt In

Two ways to force managed roots:

```yaml
workspace:
  root: xdg-state
```

or:

```yaml
workspace:
  root: /absolute/path/to/sase-workspaces
```

For one process:

```bash
SASE_WORKSPACE_ROOT=/absolute/path/to/sase-workspaces sase run "..."
```

To migrate existing adjacent checkouts for a project (opt-in, idempotent, supports dry-run):

```bash
sase workspace migrate --to xdg-state --symlink-transition -p sase
```

After transition symlinks are no longer needed:

```bash
sase workspace migrate --finalize -p sase
```

For the user's original expectation of `~/.sase/workspaces`, the closest explicit configuration is an absolute path:

```yaml
workspace:
  root: /home/bryan/.sase/workspaces
```

`workspace.root` does **not** expand `~` (it must be a literal `adjacent`, `xdg-state`, or an absolute path) so the
expanded form is required.

## Assessment

The managed workspace architecture is implemented enough to use end-to-end: store, registry, marker, allocator,
runtime resolution, CLI, migration, marker-aware CWD inference, and dedicated tests at every layer. The epic is closed.

The rollout intentionally stopped at compatibility mode. The current behavior is the configured default, not a
regression.

Cleanup path if/when the user wants the managed default:

1. Decide whether the desired managed root is `xdg-state` (`~/.local/state/sase/workspaces` on Linux) or an explicit
   absolute path like `/home/bryan/.sase/workspaces`.
2. Test `workspace.root` opt-in for the `sase` project and verify: launch, sibling repo materialization,
   commit/finalizer flows, `sase workspace list/path/repair/cleanup`, `sase bead` CWD inference from a managed
   checkout, and `migrate --to ... --symlink-transition` plus `migrate --finalize`.
3. Decide the `materialize=False` sibling fallback policy: either keep it as a deliberate "best-effort suffix" preview
   (recommended) or route it through `WorkspaceStore.resolve(...)` so all displayed paths match the runtime root.
4. Update `memory/short/workspaces.md`, the chezmoi-generated `sase_agents_status` skill files, and the `sase-github`
   configuration doc to mention managed roots.
5. Consider flipping the default in `src/sase/default_config.yml` once the above is validated. Add a release note that
   describes the migration command for upgraders.
