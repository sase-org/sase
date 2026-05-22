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

The schema in `config/sase.schema.json` accepts a top-level `sibling_repos` array. Each entry requires:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Stable alias used in prompts, metadata, and generated env var names. |
| `path` | yes | Primary checkout path. Relative paths resolve from the primary workspace, not the current numbered workspace. |
| `workspace.strategy` | no | `suffix` by default, or `none` for a singleton path. |

Use project-local config when the sibling set belongs to one project. Use user config only for entries that should
apply broadly; if you put relative paths in user config, they still resolve relative to each launched project's primary
workspace, so absolute or `~` paths are usually safer there.

Config list merging matters:

- Bundled defaults start with `sibling_repos: []`.
- User `~/.config/sase/sase.yml` replaces default lists.
- User overlays (`sase_*.yml`) and project-local `./sase.yml` concatenate lists.
- The sibling resolver deduplicates exact duplicate entries before resolving paths.

## Workspace Strategies

### `suffix`

`suffix` is the default and is the right choice for cloneable project siblings. It keeps agent changes isolated by
matching the main agent workspace number.

With the default adjacent workspace layout:

| Main workspace | Configured sibling path | Resolved sibling workspace |
| --- | --- | --- |
| `/repo/myapp` or workspace `#0` | `/repo/myapp-core` | `/repo/myapp-core` |
| workspace `#1` | `/repo/myapp-core` | `/repo/myapp-core` |
| `/repo/myapp_10` | `/repo/myapp-core` | `/repo/myapp-core_10` |

The implementation calls `ensure_workspace_checkout(primary_dir, workspace_num)` when materialization is enabled, so
numbered sibling checkouts can be created on demand for Git-backed primary checkouts. Under non-adjacent
`workspace.root` policies, the same workspace-store rules can place materialized checkouts under the configured managed
workspace root rather than beside the primary checkout.

### `none`

`none` always exposes the primary path, regardless of workspace number. Use it for:

- singleton repos such as chezmoi/dotfiles;
- non-Git directories that cannot be cloned into numbered workspaces;
- intentionally shared external state.

Do not use `none` for a normal code repo unless it is acceptable for multiple agents to edit the same checkout.

## Resolution Rules

The resolver is `src/sase/sibling_repos.py::resolve_sibling_repos_for_project()`.

For each configured entry, SASE:

1. Determines the primary workspace directory from the project file's `WORKSPACE_DIR`; if unavailable, it falls back to
   the supplied workspace directory or current directory.
2. Reads sibling entries from merged config and explicitly reads the primary checkout's `sase.yml`.
3. Expands `~` and environment variables in `path`.
4. Resolves relative paths from the primary workspace directory.
5. Skips entries with missing/blank names, missing/blank paths, unsupported strategies, missing primary paths, or
   failed workspace materialization.
6. Sanitizes `name` into env-safe uppercase aliases. For example, `sase-core` becomes `SASE_CORE`; colliding aliases
   become `SASE_CORE_2`, `SASE_CORE_3`, and so on.

The resolver returns warnings for skipped entries, but normal launch paths currently use the successful resolved map
and do not prominently surface every warning to the user. If a sibling is missing from the prompt/env, check that the
primary path exists and that the strategy fits the repo.

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
`src/sase/axe/run_agent_directives.py`. If an agent starts in deferred-workspace mode (`%wait` style launch), SASE
does not expose numbered siblings until the real workspace is claimed. After `claim_deferred_workspace()` assigns a real
workspace, `refresh_sibling_repos_for_workspace()` recomputes sibling paths, updates `os.environ`, rewrites
`agent_meta.json`, and appends the prompt note.

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

- Dirty primary sibling checkouts are ignored when the current session has a numbered sibling workspace. For example,
  if `core` resolves to `sase-core_10`, a dirty `sase-core` primary checkout does not trigger the finalizer for that
  agent.
- The sibling dirty-check path is Git-specific. Non-Git sibling paths can still be shown to the agent through prompts
  and env vars, but the finalizer ignores paths where `git status` fails.
- The legacy `tools/sase_sibling_commit_stop_hook` is now compatibility-only and remains repo-specific. It scans
  hardcoded `../sase-*` and `~/.local/share/chezmoi` paths and does not consume `sibling_repos`; active SASE-launched
  runs should rely on the provider-neutral finalizer.

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
