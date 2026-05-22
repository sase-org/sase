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

The work exists, but it did not flip the default.

There are two separate migrations that are easy to conflate:

1. **ProjectSpec/state migration to `~/.sase`.** SASE project files, artifacts, chats, notifications, and related state
   now live under `~/.sase/`, especially `~/.sase/projects/<project>/`. This is the `.gp` -> `.sase` ProjectSpec
   migration and durable-state layout.
2. **Checkout workspace directory migration.** SASE implemented an opt-in managed checkout root through
   `workspace.root`, `WorkspaceStore`, a registry, markers, and `sase workspace migrate`. This does not default to
   `~/.sase`; the documented managed default is `xdg-state`, which resolves to
   `~/.local/state/sase/workspaces/...` on Linux unless overridden.

On this machine and in the checked-in defaults, `workspace.root` is still `adjacent`, and `SASE_WORKSPACE_ROOT` is not
set. That means runtime workspace resolution still deliberately materializes numbered checkouts next to the primary
checkout, such as:

```text
/home/bryan/projects/github/sase-org/sase_10
/home/bryan/projects/github/sase-org/sase-core_10
/home/bryan/projects/github/sase-org/sase-github_10
```

I found no existing managed checkout registry or checkout marker under `~/.sase`, `~/.local/state/sase/workspaces`, or
another obvious `*/sase/workspaces` root on this machine.

## Implementation History

The managed-workspace work landed as the `sase-3p` workspace directory layout epic. Relevant commits:

| Commit | Summary |
| --- | --- |
| `041e3bf35` | Added `WorkspaceStore` with adjacent parity, config/schema fields, and tests. |
| `532a62d9a` | Split materialization from path choice with target-aware Git checkout helpers. |
| `9cceb103b` | Added managed workspace registry and `.sase/checkout.json` checkout markers. |
| `c73bee66d` | Migrated allocation to one unified claim pool starting at workspace `#10`. |
| `18a5f494b` | Routed runtime workspace resolution through `WorkspaceStore`. |
| `3a75c7370` | Added marker-first CWD project inference before sibling basename scanning. |
| `8207346ce` | Added `sase workspace` CLI for list/path/open/cleanup/repair. |
| `8145a6843` | Added `sase workspace migrate --to xdg-state` and transition symlink support. |
| `2147ba8c7` | Documented workspace directory layout and config. |
| `d7ed0ce1f` | Closed the epic and removed obsolete helper code. |
| `986686485`, `a1f319117` | Refreshed and clarified docs after the implementation. |

Related but separate `.sase` ProjectSpec migration commits:

| Commit | Summary |
| --- | --- |
| `55a961a40` | Migrated main runtime paths to project specs under `~/.sase/projects`. |
| `88bd937b9` | Finished `.sase` migration across TUI/tests/docs. |
| `3d25c0eb2`, `c9bff699e` | Hardened legacy `.gp` -> canonical `.sase` migration behavior. |

## Current Runtime Model

### Project State

Project-level state lives under `~/.sase/projects/<project>/`.

- Canonical active ProjectSpec: `~/.sase/projects/<project>/<project>.sase`
- Canonical archive ProjectSpec: `~/.sase/projects/<project>/<project>-archive.sase`
- Legacy `.gp` files remain readable as fallback.
- `WORKSPACE_DIR:` in the ProjectSpec points to the **primary checkout**. It is not rewritten to a managed workspace
  root.

The local `sase` ProjectSpec still points at the primary checkout:

```text
~/.sase/projects/sase/sase.gp:
WORKSPACE_DIR: /home/bryan/projects/github/sase-org/sase/
```

That is expected. Workspace `#0` resolves to this primary checkout.

### Workspace Numbers

The current numeric contract is:

| Number | Meaning |
| --- | --- |
| `#0` | Primary checkout and deferred-launch placeholder. |
| `#1` | Legacy compatibility alias for primary in some wrappers. |
| `#1`-`#9` | Reserved. New claims should not allocate these. |
| `#10+` | Unified claim pool for agent and workflow workspaces. |

The implementation lives in `src/sase/running_field/_workspace.py`.

### Root Policy

`WorkspaceStore` is the path resolver for numbered checkouts. It supports:

| Policy | Behavior |
| --- | --- |
| `adjacent` | Legacy default. Non-primary checkouts are `<primary>_<num>/`. |
| `xdg-state` | Managed root under the platform state directory, namespaced by project key. |
| absolute path | Managed root under the configured absolute path, namespaced by project key. |
| `SASE_WORKSPACE_ROOT` | Environment override for the managed-root base. |

The current default config is:

```yaml
workspace:
  root: adjacent
  project_key: ""
  cleanup_ttl_days: 14
```

Source: `src/sase/default_config.yml`.

No user or project config currently overrides `workspace.root` in:

- `sase.yml`
- `~/.config/sase/sase.yml`
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`

`SASE_WORKSPACE_ROOT` was not set in the inspected shell environment.

### Adjacent Layout

With `workspace.root: adjacent`, SASE preserves the historical layout:

```text
primary:  /home/bryan/projects/github/sase-org/sase/
#10:      /home/bryan/projects/github/sase-org/sase_10/
#11:      /home/bryan/projects/github/sase-org/sase_11/
```

This is the current behavior on this machine. Existing adjacent workspace directories are present for `sase`,
`sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim`.

### Managed Root Layout

With `workspace.root: xdg-state` on Linux, non-primary checkouts resolve under:

```text
${XDG_STATE_HOME:-~/.local/state}/sase/workspaces/<project_key>/<project>_<num>/
```

With an absolute `workspace.root`, non-primary checkouts resolve under:

```text
<configured-root>/<project_key>/<project>_<num>/
```

`SASE_WORKSPACE_ROOT=/some/root` behaves like an absolute managed-root base:

```text
/some/root/<project_key>/<project>_<num>/
```

Despite the user-facing phrase "move to `~/.sase`", the implemented managed default is not `~/.sase/workspaces`; it is
`xdg-state`. Moving into `~/.sase/workspaces` would require an explicit absolute config or env override.

### Registry And Checkout Markers

For non-adjacent roots, SASE records managed checkouts in:

```text
<managed-root>/<project_key>/registry.json
```

Each managed non-primary checkout can also contain:

```text
<checkout>/.sase/checkout.json
```

The marker records project name, project key, workspace number, primary checkout path, and registry path. It exists so
commands run from inside managed checkouts can infer their project without relying on sibling basename parsing.

Markers are deliberately not written into primary checkouts. Adjacent layout also normally avoids registry writes.

### Materialization

Runtime callers resolve and materialize Git checkouts through:

- `src/sase/workspace_provider/store.py`
- `src/sase/workspace_provider/utils.py`
- `src/sase/running_field/_workspace.py`
- workspace provider hooks in `src/sase/workspace_provider/_registry.py`

The built-in bare-git provider calls `ensure_workspace_checkout(primary_workspace_dir, workspace_num)`, which loads
merged config, asks `WorkspaceStore` for the path, clones if needed, and records registry/marker data only for
non-adjacent roots.

The `sase-github` plugin also delegates numbered workspace creation to core `ensure_workspace_checkout`, so it can honor
managed roots when core config asks it to. Its docs still describe GitHub workspaces as sibling paths, which is accurate
for the default `adjacent` policy but incomplete for `workspace.root: xdg-state`.

## `sase workspace` CLI

The CLI exists and is wired into the top-level parser:

| Command | Purpose |
| --- | --- |
| `sase workspace list [-j] [-p PROJECT]` | Show registry/project view, including primary `#0`. |
| `sase workspace path NUM [-p PROJECT]` | Print a checkout path; materializes only when the workspace is primary, already registered, or actively claimed. |
| `sase workspace open NUM [-p PROJECT]` | Currently same as `path`; editor/shell integration is reserved. |
| `sase workspace cleanup --stale [-n] [-p PROJECT]` | Remove unclaimed stale managed checkouts older than `cleanup_ttl_days`. |
| `sase workspace repair [-n] [-p PROJECT]` | Reconcile registry entries with the filesystem; re-materialize live missing claims. |
| `sase workspace migrate --to xdg-state [-s] [-n] [-p PROJECT]` | Move existing adjacent `<primary>_<num>` checkouts into the `xdg-state` managed root. |
| `sase workspace migrate --finalize [-n] [-p PROJECT]` | Remove transition symlinks left by migration. |

Migration is explicitly opt-in. With `--symlink-transition`, SASE leaves adjacent `<primary>_<num>` symlinks that point
at the managed checkout so older tooling can continue to find sibling-looking paths during a transition.

## Why Managed Workspaces Are Not Being Used Here

The direct reasons are:

1. **Default remains adjacent.** `src/sase/default_config.yml` sets `workspace.root: adjacent`.
2. **No local override is configured.** I found no `workspace.root: xdg-state` or absolute root in the repo-local,
   user, or chezmoi SASE config files inspected.
3. **No environment override is present.** `SASE_WORKSPACE_ROOT` is not set in the current shell.
4. **No managed-root artifacts exist locally.** No `registry.json` or `.sase/checkout.json` markers were found under
   `~/.sase`, `~/.local/state/sase/workspaces`, or another obvious `*/sase/workspaces` path.
5. **The docs intentionally deferred the default flip.** `docs/workspace.md` says the default value remains `adjacent`
   and the default flip was deferred until the sibling-repo workspace resolver consumes the same `WorkspaceStore`.

The last point is partially stale now: `src/sase/sibling_repos.py` materializes suffix-strategy siblings through
`ensure_workspace_checkout`, so with `workspace.root: xdg-state` it should now use `WorkspaceStore` for siblings too.
However, the user-facing sibling docs and prompt wording still talk primarily in adjacent/suffix terms.

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

Sibling resolution:

- resolves each primary sibling path relative to the main primary checkout;
- for `workspace.strategy: none`, always uses the primary path;
- for `workspace.strategy: suffix` and workspace `#0`/`#1`, uses the primary sibling path;
- for `suffix` and workspace `#10+`, calls `ensure_workspace_checkout(primary_dir, workspace_num)`.

Because the active config default is `adjacent`, the resolved sibling directories are currently adjacent siblings such
as `sase-core_10`, `sase-github_10`, `sase-telegram_10`, and `sase-nvim_10`. If `workspace.root` were changed to
`xdg-state` or an absolute managed root, the materialized sibling paths should follow `WorkspaceStore` rather than
simple `<primary>_<num>` suffixing when `materialize=True`.

## Current Documentation/Memory Drift

Several docs are current:

- `README.md` documents `#0`, `#10+`, `workspace.root`, and the managed-root commands.
- `docs/workspace.md` has the detailed managed layout and migration reference.
- `docs/configuration.md` documents `workspace.root`, `project_key`, and `cleanup_ttl_days`.
- `docs/project_spec.md` correctly separates primary `WORKSPACE_DIR` from managed numbered checkouts.

Stale or incomplete areas:

- `memory/short/workspaces.md` still describes agent runs only as ephemeral sibling `sase_<N>` clones. That is accurate
  for today's default but not for managed-root configurations.
- Generated SASE skill docs in chezmoi, such as `sase_agents_status`, still say `workspace_num` resolves to
  `<parent-of-this-repo>/sase_<N>/`.
- `sase-github/docs/configuration.md` still describes GitHub numbered workspaces only as siblings. It delegates to core
  `ensure_workspace_checkout`, so it should mention managed roots if this plugin is expected to support them.
- `docs/workspace.md` says the default flip is blocked until sibling-repo resolution consumes `WorkspaceStore`; the code
  path now appears to do that for materialized Git siblings, but docs/tests may still be centered on adjacent examples.

## How To Opt In

There are two ways to force managed roots:

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

To migrate existing adjacent checkouts for a project:

```bash
sase workspace migrate --to xdg-state --symlink-transition -p sase
```

After transition symlinks are no longer needed:

```bash
sase workspace migrate --finalize -p sase
```

For the user's original expectation of `~/.sase`, the closest explicit configuration would be:

```yaml
workspace:
  root: ~/.sase/workspaces
```

However, `WorkspaceStore` currently requires absolute paths for non-keyword root values, so this would need to be
written as:

```yaml
workspace:
  root: /home/bryan/.sase/workspaces
```

## Assessment

The managed workspace architecture is implemented enough to use, but rollout stopped at compatibility mode. The current
behavior is not a regression from the implementation; it is the configured default.

The likely cleanup path is:

1. Decide whether the desired managed root is `xdg-state` (`~/.local/state/sase/workspaces` on Linux) or an explicit
   `~/.sase/workspaces` path.
2. Test `workspace.root` opt-in for the `sase` project and verify launch, sibling repo materialization, commit
   finalizer, `sase workspace list/path/repair/cleanup`, and CWD inference from managed checkouts.
3. Update stale memory/generated skills and `sase-github` docs once the desired policy is confirmed.
4. Consider flipping the default only after sibling docs/tests, existing external plugins, and migration ergonomics are
   revalidated.
