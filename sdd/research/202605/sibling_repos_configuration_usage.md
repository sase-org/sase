# Sibling Repo Configuration And Usage Research

Date: 2026-05-22

## Question

How are sibling repositories configured in SASE today, and how does SASE use that configuration when launching and
finalizing agent work? This note is written for a new SASE user who wants to configure related repositories for their
own project for the first time.

## Short Answer For First-Time Setup

Add a `sibling_repos` list to the project-local `sase.yml` in the primary checkout:

```yaml
sibling_repos:
  - name: core
    path: ../myapp-core
  - name: docs
    path: ../myapp-docs
  - name: dotfiles
    path: ~/.local/share/chezmoi
    workspace:
      strategy: none
```

Configure the primary checkout path, not the numbered workspace path. With the default `workspace.strategy: suffix`,
an agent assigned workspace `#10` will see `../myapp-core` as the workspace-matched sibling checkout
`../myapp-core_10` under the default adjacent workspace layout. Use `workspace.strategy: none` for singleton repos that
should not get numbered checkouts, such as a personal dotfiles/chezmoi repo.

When an agent is launched, SASE appends a prompt note listing the resolved sibling paths, exports environment
variables such as `SASE_SIBLING_REPO_CORE_DIR`, records the same map in `agent_meta.json`, and checks configured Git
sibling worktrees during commit finalization.

## Current Project Example

The SASE project config in `sase.yml` declares five siblings:

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

For this workspace (`sase_10`), the resolver returns:

| Name | Strategy | Primary checkout | Agent workspace path |
| --- | --- | --- | --- |
| `core` | `suffix` | `/home/bryan/projects/github/sase-org/sase-core` | `/home/bryan/projects/github/sase-org/sase-core_10` |
| `github` | `suffix` | `/home/bryan/projects/github/sase-org/sase-github` | `/home/bryan/projects/github/sase-org/sase-github_10` |
| `telegram` | `suffix` | `/home/bryan/projects/github/sase-org/sase-telegram` | `/home/bryan/projects/github/sase-org/sase-telegram_10` |
| `nvim` | `suffix` | `/home/bryan/projects/github/sase-org/sase-nvim` | `/home/bryan/projects/github/sase-org/sase-nvim_10` |
| `chezmoi` | `none` | `/home/bryan/.local/share/chezmoi` | `/home/bryan/.local/share/chezmoi` |

This is why agent prompts in this project include:

```text
Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/projects/github/sase-org/sase-core_10
- github: /home/bryan/projects/github/sase-org/sase-github_10
- telegram: /home/bryan/projects/github/sase-org/sase-telegram_10
- nvim: /home/bryan/projects/github/sase-org/sase-nvim_10
- chezmoi: /home/bryan/.local/share/chezmoi
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.
```

## Configuration Model

The shipped default is an empty list in `src/sase/default_config.yml`:

```yaml
sibling_repos: []
```

`config/sase.schema.json` defines the accepted shape and enforces it with `additionalProperties: false`. Unknown
fields under an entry — including typos like `paths:` or `worktree:` — cause schema validation to fail rather than
being silently ignored:

| Field | Required | Constraint |
| --- | --- | --- |
| `name` | yes | Non-empty string. Stable alias used in prompts, metadata, and generated env var names. |
| `path` | yes | Non-empty string. Primary checkout path. Relative paths resolve from the project's primary `WORKSPACE_DIR`, not the current numbered workspace. |
| `workspace` | no | Object. Currently only `workspace.strategy` is defined. |
| `workspace.strategy` | no | `"suffix"` (default) or `"none"`. Other values cause the entry to be skipped at resolve time. |

Use project-local config when the sibling set belongs to one project. Use user config (`~/.config/sase/sase.yml` or
`sase_*.yml` overlays) only for entries that should apply broadly; relative paths there still resolve relative to
each launched project's primary workspace, so absolute or `~` paths are usually safer in user config.

`docs/configuration.md#sibling_repos` is the public reference. The deep-merge rules in that document apply here:

| Layer | Source | List behavior on `sibling_repos` |
| --- | --- | --- |
| 1 | `src/sase/default_config.yml` | Starts as `[]`. |
| 2 | Plugin `default_config.yml` files (via `sase_config` entry points) | Concatenate. |
| 3 | `~/.config/sase/sase.yml` | **Replaces** earlier layers (this is the one layer that does not concatenate). |
| 4 | `~/.config/sase/sase_*.yml` overlays (sorted) | Concatenate. |
| 5 | Project-local `./sase.yml` | Concatenate (highest priority). |

In addition, `_configured_entries()` in `src/sase/sibling_repos.py` re-reads the **primary checkout's**
`./sase.yml` and appends its entries, even when the agent runs from a numbered workspace clone. This is what makes
project-local sibling config "follow" the project across workspace clones rather than being whatever happens to be
checked into the current branch of the numbered workspace.

`_dedupe_entries()` then collapses entries whose `(name, path, workspace.strategy)` tuple is identical, so the same
entry merged in from multiple layers does not produce duplicate env vars or duplicate prompt lines. Entries that
differ in any of those three fields are kept; differing `env_name` collisions are uniquified per
[What Agents Receive](#what-agents-receive).

## Workspace Strategies

### `suffix`

`suffix` is the default and is the right choice for cloneable project siblings. It keeps agent changes isolated by
matching the main agent workspace number.

With the default adjacent workspace layout (`workspace.root: adjacent`):

| Main workspace | Configured sibling path | Resolved sibling workspace |
| --- | --- | --- |
| `#0` (primary) | `/repo/myapp-core` | `/repo/myapp-core` |
| `#1` (legacy alias for primary) | `/repo/myapp-core` | `/repo/myapp-core` |
| `#10` (`/repo/myapp_10`) | `/repo/myapp-core` | `/repo/myapp-core_10` |

`_resolve_workspace_dir()` in `sibling_repos.py` returns the primary path verbatim whenever `workspace_num <= 1`
(see the workspace numeric-identity reference in `docs/workspace.md`: `#0` is the primary, `#1`–`#9` are reserved
for legacy/manual use, and managed claims start at `#10`). For workspace numbers `>= 2`, suffix siblings are
materialized by calling `ensure_workspace_checkout(primary_dir, workspace_num)`, which:

1. Normalizes `workspace_num == 1` to `0` so managed roots route consistently.
2. Asks the active `WorkspaceStore` for the checkout path for that workspace number.
3. For Git-backed primaries, ensures a Git clone exists at that path (`_ensure_git_clone_at()`).
4. Records the checkout in the workspace registry and writes a checkout marker so `sase workspace` can find it
   later.

Under non-adjacent `workspace.root` policies (`xdg-state` or an absolute path), the same store rules place each
sibling's materialized checkout under `<managed-root>/<sibling-project-key>/<sibling-name>_<num>/` rather than
beside the primary checkout. `SASE_WORKSPACE_ROOT` overrides the managed-root base for the current process.

If `ensure_workspace_checkout` raises (for example, the primary path is not a Git repo and the workspace store
cannot clone it for workspace `N`), the resolver emits a warning like
`"Skipping sibling repo 'core': <error>"` and drops that entry from the resolution. The warning is collected on
`SiblingRepoResolution.warnings` but is **not** surfaced through `launch_spawn.py` today, so the visible symptom
to the user is simply "the sibling is missing from the prompt/env" — see
[Troubleshooting](#troubleshooting-sibling-not-visible).

### `none`

`none` always exposes the primary path, regardless of workspace number. Use it for:

- singleton repos such as chezmoi/dotfiles;
- non-Git directories that cannot be cloned into numbered workspaces;
- intentionally shared external state.

Do not use `none` for a normal code repo unless it is acceptable for multiple agents to edit the same checkout.

## Resolution Rules

The resolver is `src/sase/sibling_repos.py::resolve_sibling_repos_for_project()`.

For each configured entry, SASE:

1. Determines the primary workspace directory from the project file's `WORKSPACE_DIR`; if unavailable, it falls back
   to the supplied workspace directory, then to `os.getcwd()`.
2. Reads sibling entries from merged config and explicitly re-reads the primary checkout's `sase.yml`, appending
   those entries (see [Configuration Model](#configuration-model)).
3. Deduplicates by `(name, path, workspace.strategy)`.
4. Expands `~` first and then environment variables in `path` (`os.path.expandvars(os.path.expanduser(path))`).
   Resolves relative paths from the primary workspace directory.
5. Skips entries with missing/blank names, missing/blank paths, unsupported strategies, primary paths that are not
   existing directories, or workspace materialization failures. Each skip produces a warning string on the result.
6. Sanitizes `name` into env-safe uppercase aliases. Examples:
    - `core` → `CORE`
    - `sase-core` → `SASE_CORE`
    - `dotfiles/personal` → `DOTFILES_PERSONAL`
    - `1config` → `1CONFIG` (digits are kept; only non-alphanumerics collapse to `_`)
    - Empty after sanitization → `REPO`
    - Collisions get a numeric suffix in encounter order: `CORE`, then `CORE_2`, then `CORE_3`, …

The resolver returns warnings for skipped entries (`SiblingRepoResolution.warnings`), but the launch path discards
them and the finalizer's config fallback discards them too. Treat warning visibility as an open gap and lean on the
checklist in [Troubleshooting](#troubleshooting-sibling-not-visible) when diagnosing.

## What Agents Receive

At low-level agent spawn, `src/sase/agent/launch_spawn.py` resolves siblings after the main workspace number is known.
It then:

- appends the short sibling note to the child prompt;
- scrubs inherited `SASE_SIBLING_REPOS_JSON` and stale `SASE_SIBLING_REPO_*` env vars;
- exports fresh env vars for the child process;
- records the same env in the chop agent launch record.

The canonical environment variable is `SASE_SIBLING_REPOS_JSON`. It contains JSON objects shaped like:

```json
{
  "name": "core",
  "env_name": "CORE",
  "primary_dir": "/home/bryan/projects/github/sase-org/sase-core",
  "workspace_dir": "/home/bryan/projects/github/sase-org/sase-core_10",
  "workspace_num": 10,
  "workspace_strategy": "suffix"
}
```

Convenience env vars are also set:

```text
SASE_SIBLING_REPO_CORE_DIR=/home/bryan/projects/github/sase-org/sase-core_10
SASE_SIBLING_REPO_CORE_PRIMARY_DIR=/home/bryan/projects/github/sase-org/sase-core
```

Agent metadata also receives `sibling_repos` from the same JSON map in
`src/sase/axe/run_agent_directives.py` (via `_sibling_repos_from_env()`).

`scrub_sibling_repo_env()` only removes `SASE_SIBLING_REPOS_JSON` and `SASE_SIBLING_REPO_*` vars whose suffix is
exactly `_DIR` or `_PRIMARY_DIR`. Other `SASE_SIBLING_REPO_*` env vars set by the user are intentionally
preserved across the launch boundary; the scrub is precisely scoped so that only sibling-state set by SASE itself
is cleared before a fresh resolution is applied.

### Deferred-Workspace Lifecycle

Some launches (e.g. `%wait` dependencies) defer workspace assignment. In that case `launch_spawn.py` constructs a
`SiblingRepoResolution(())` — an empty resolution — so the child starts with no sibling env vars, no prompt note,
and no `sibling_repos` field in `agent_meta.json`. Sibling paths would otherwise be wrong because the workspace
number is not yet known.

Once the real workspace is claimed in `src/sase/axe/run_agent_phases.py` (`claim_deferred_workspace()`),
`src/sase/axe/run_agent_runner_setup.py::refresh_sibling_repos_for_workspace()` runs:

1. Resolves siblings with the now-known `(workspace_dir, workspace_num)` and materialization enabled.
2. Calls `apply_sibling_repo_env(os.environ, resolution)` — scrubs and rewrites the current process env.
3. Updates `agent_meta.workspace_dir` and either sets `agent_meta["sibling_repos"]` or removes the key when empty.
4. Persists the updated `agent_meta.json` via `write_agent_meta()`.
5. Returns a new prompt with the sibling note appended (or the unchanged prompt if no siblings resolved).

Inside an agent, you can always re-read `SASE_SIBLING_REPOS_JSON` to get the authoritative current map; the
convenience `_DIR` / `_PRIMARY_DIR` vars are derived from it.

## Commit Finalizer Behavior

The provider-neutral commit finalizer in `src/sase/llm_provider/commit_finalizer.py` is the main runtime behavior that
uses sibling configuration after the agent finishes a successful provider invocation.

The finalizer:

1. Skips when `commit.finalizer.enabled` is false, `SASE_DISABLE_COMMIT_STOP_HOOK=1` is set, or the process is not a
   SASE agent session.
2. Checks the main workspace through the active VCS provider.
3. Checks configured siblings as Git worktrees using `git status --porcelain=v1 --untracked-files=all`.
4. If `SASE_SIBLING_REPOS_JSON` exists, checks exactly those `workspace_dir` paths.
5. If the env JSON is absent, falls back to resolving siblings from project config without materializing missing
   workspaces.
6. When dirty sibling repos are found, runs a bounded follow-up provider invocation telling the same agent to `cd` into
   each sibling workspace and use `/sase_git_commit`.
7. Re-checks the dirty targets and fails the run if they remain dirty after `commit.finalizer.max_passes`.

Important details:

- The finalizer only checks the sibling **workspace_dir**, not the primary path. If `core` resolves to
  `sase-core_10`, a dirty `sase-core` primary checkout does not trigger the finalizer for that agent.
- The sibling dirty-check path is Git-specific (`git status --porcelain=v1 --untracked-files=all`). Non-Git
  sibling paths can still be shown to the agent through prompts and env vars, but the finalizer silently ignores
  paths where `git status` fails or returns non-zero — including `workspace.strategy: none` entries pointing at a
  non-Git directory.
- The config fallback path (no `SASE_SIBLING_REPOS_JSON` set) needs to know which numbered workspace it is in.
  `_workspace_num_for_project_file()` derives it in this order:
  1. From env: `SASE_AGENT_WORKSPACE_NUM`, then `SASE_GIT_WORKSPACE_NUM`, then `SASE_CD_WORKSPACE_NUM`.
  2. By comparing `project_dir` to the parsed primary `WORKSPACE_DIR`: identical paths yield `0`; otherwise the
     suffix after `<primary>_` is parsed (e.g. `sase_10` → `10`). Anything else returns `None` and the fallback
     skips sibling checks entirely.
- `SASE_DISABLE_COMMIT_STOP_HOOK=1` and `commit.finalizer.enabled: false` disable only the finalizer. Prompt
  notes, env vars, and `agent_meta.sibling_repos` are still set, so the agent can still `cd` into siblings — it
  just will not be auto-corrected for forgetting to commit.
- The legacy `tools/sase_sibling_commit_stop_hook` is compatibility-only and repo-specific. It scans hardcoded
  `../sase-*` and `~/.local/share/chezmoi` paths and does not consume `sibling_repos`; active SASE-launched runs
  should rely on the provider-neutral finalizer.

## Troubleshooting: Sibling Not Visible

If a configured sibling does not appear in an agent's prompt note, env, or `agent_meta.json`, check in this order:

1. **Does the primary path exist?** `Path(primary_dir).is_dir()` must be `True`. Missing directories are silently
   dropped with a warning that is not surfaced to the user.
2. **Did the schema accept the entry?** Run a config-merging command (`sase ace` startup or any `sase` subcommand
   that loads config) and look for schema errors. Unknown fields under `sibling_repos[]` (e.g. `paths:`,
   `worktree:`) fail validation because the schema sets `additionalProperties: false`.
3. **Is `workspace.strategy` one of `"suffix"` or `"none"`?** Any other value, including `null` explicitly, is
   skipped. Omitting the key entirely is fine and defaults to `"suffix"`.
4. **Is `name` non-empty and `path` non-empty after expansion?** Empty strings, missing keys, or non-string values
   are skipped.
5. **For `suffix` siblings on workspace `#>=2`, can the workspace store materialize a numbered checkout?**
   `ensure_workspace_checkout()` requires either a Git-backed primary checkout (so it can clone) or a
   managed-root layout that already contains the numbered checkout. If neither holds, the entry is dropped.
6. **Are you on workspace `#0` or `#1`?** Both return the primary path for `suffix` siblings. If you are testing
   the `sase-core_10` naming, you must be running from a workspace numbered `>= 2` (in practice `>= 10`, since
   managed claims start there).
7. **Are you looking at a child agent?** Sibling env vars on `_DIR` / `_PRIMARY_DIR` are scrubbed and rewritten
   per launch, but other `SASE_SIBLING_REPO_*` env vars set by the user are passed through unchanged — those will
   not reflect the current resolution.
8. **Deferred-workspace agent?** Until `claim_deferred_workspace()` runs, `sibling_repos` is intentionally empty
   in `agent_meta.json` and `SASE_SIBLING_REPOS_JSON` is unset. Expect them to appear only after the workspace is
   assigned.
9. **Finalizer silently skipping siblings?** Confirm `SASE_AGENT_TIMESTAMP` is set (the finalizer no-ops outside a
   SASE agent session) and that `SASE_AGENT_PROJECT_FILE` is set when relying on the config fallback.

If none of the above explains it, instrument
`src/sase/sibling_repos.py::_resolve_sibling_repos` (or write a unit test mirroring `tests/test_sibling_repos.py`)
to inspect `SiblingRepoResolution.warnings` directly.

## Practical Onboarding Checklist

1. Put primary sibling checkouts somewhere stable.
2. Add `sibling_repos` to the primary project's `sase.yml`.
3. Use relative paths for project-local siblings that live beside the primary checkout.
4. Use `workspace.strategy: none` for singleton or non-cloneable directories.
5. Launch an agent and confirm the prompt includes the sibling note.
6. Inside an agent, use `SASE_SIBLING_REPO_<ENV_NAME>_DIR` or the prompt-listed path when editing sibling code.
7. Let the commit finalizer guide commits for dirty Git siblings, and commit singleton repos manually when the finalizer
   cannot enforce them.

## Limitations And Open Edges

- There is no `sase sibling add/list/remove` CLI yet; first-time setup is YAML editing.
- The current model is path-backed only. It does not declare hosted refs such as `workflow_type: gh` plus `ref: org/repo`.
- The normal launch path uses materialized workspace paths, but the finalizer's config fallback uses non-materializing
  suffix resolution. The exported env JSON is the reliable source for active launched sessions.
- The Rust launch wire in `sase-core` does not carry first-class sibling records yet; sibling handling is currently
  Python launch/env/prompt behavior.
- Some older code still has direct sibling assumptions. For example, `src/sase/integrations/mobile_gateway.py` still
  searches for the gateway binary under `../sase-core` rather than resolving the configured `core` sibling.

## Source Map

- `sase.yml`: this project's configured sibling list.
- `src/sase/default_config.yml`: default empty `sibling_repos`.
- `config/sase.schema.json`: accepted config shape.
- `docs/configuration.md`: public config reference.
- `src/sase/sibling_repos.py`: resolver, env serialization, prompt note, env scrubbing.
- `src/sase/agent/launch_spawn.py`: launch-time resolution and child env setup.
- `src/sase/axe/run_agent_directives.py`: initial `agent_meta.json` sibling metadata.
- `src/sase/axe/run_agent_runner_setup.py`: deferred-workspace sibling refresh.
- `src/sase/axe/run_agent_phases.py`: deferred workspace claim and sibling env refresh trigger.
- `src/sase/llm_provider/commit_finalizer.py`: dirty sibling Git checks and follow-up commit instructions.
- `tests/test_sibling_repos.py`: core resolver behavior.
- `tests/test_cd_spawn_env.py`: launch env and stale-env scrub coverage.
- `tests/test_run_agent_runner_setup.py`: metadata/prompt refresh coverage.
- `tests/test_axe_run_agent_runner_deferred_workspace.py`: deferred workspace recompute coverage.
- `tests/llm_provider/test_commit_finalizer_siblings.py`: commit finalizer sibling behavior.
