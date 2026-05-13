# Sibling Repo Workspace Generalization Research

Date: 2026-05-13

## Question

How should SASE generalize the current "sibling repos" concept so any SASE project can declare its own related
repositories, new users can configure them easily, and agents always work in the sibling repo workspace that matches the
main project's assigned workspace number?

## Executive Summary

SASE already has a strong workspace-provider abstraction for primary workspaces, but sibling repos are not first-class.
The current behavior is mostly a repo-local stop hook that scans hardcoded paths matching `../sase-*/` plus
`~/.local/share/chezmoi`, skipping names ending in `_<N>`. That works for the `sase` development cluster, but it is not
portable to other projects and it directs agents toward primary sibling checkouts instead of workspace-numbered sibling
checkouts.

The best implementation path is to add a first-class `sibling_repos` project/user config model, resolve it once at
agent launch, and pass a concrete workspace mapping into the child agent environment/artifacts. For clone-backed
sibling repos, the sibling workspace path should be derived from the sibling's primary checkout plus the main agent's
workspace number, e.g. main `sase_102` edits `sase-core_102`, not `sase-core`.

This should be a SASE core capability, not a `sase` repo special case. The actual path resolution can begin in Python
because workspace providers and config live there today, but the resolved wire shape should be added to the Rust launch
boundary so future CLI/TUI/mobile callers get identical behavior.

## Current Behavior

### Workspace providers already solve primary workspace selection

Primary workspaces are handled through `sase.workspace_provider` pluggy hooks:

- `WorkflowMetadata` declares a workflow type, ref regex, display name, preallocated env prefix, VCS family, and VCS
  provider name.
- `ResolvedRef` carries `project_file`, `project_name`, `primary_workspace_dir`, and `checkout_target`.
- `ws_get_workspace_directory(workflow_type, workspace_num, project_name, primary_workspace_dir)` returns the concrete
  workspace directory for a numbered slot.

The built-in bare-git and `sase-github` workspace providers both use `ensure_git_clone(primary_workspace_dir,
workspace_num)`, whose path rule is `primary` for workspace `1` and `primary_<N>` for workspace `N > 1`.

Relevant code:

- `src/sase/workspace_provider/_hookspec.py`
- `src/sase/workspace_provider/_registry.py`
- `src/sase/workspace_provider/utils.py`
- `src/sase/workspace_provider/plugins/bare_git_workspace.py`
- `../sase-github/src/sase_github/workspace_plugin.py`

### Agent launch already carries a resolved workspace number

The shared launch executor resolves one workspace number per agent slot. For normal non-home launches it preclaims an
axe workspace, computes a directory, then transfers the claim to the spawned child process. For explicit VCS refs, the
launcher can preallocate a provider-specific workspace and export env such as `SASE_GH_WORKSPACE_NUM` and
`SASE_GH_WORKSPACE_DIR`.

Relevant code:

- `src/sase/agent/launch_executor.py`
- `src/sase/agent/launch_spawn.py`
- `src/sase/axe/run_agent_runner.py`
- `../sase-core/crates/sase_core/src/agent_launch/mod.rs`

The runner changes into the main workspace before dynamic memory, xprompt expansion, file-reference validation, and LLM
invocation. It also sets `SASE_ACTIVE_PROJECT_DIR` to the child workspace.

### Current sibling-repo detection is hardcoded

The repo-local sibling hook is `tools/sase_sibling_commit_stop_hook`. It:

- resolves the current project dir from runtime env vars such as `CLAUDE_PROJECT_DIR`, `QWEN_PROJECT_DIR`,
  `GEMINI_PROJECT_DIR`, and `CODEX_PROJECT_DIR`;
- scans `"$PROJECT_DIR"/../sase-*/` and `$HOME/.local/share/chezmoi`;
- skips directory basenames ending in `_<number>`;
- blocks once per agent session if any scanned repo has `git status --porcelain` output;
- tells the agent to `cd ../sase-core` style primary paths before committing.

This behavior is intentionally repo-specific and was useful for the maintained SASE sibling repos. It is not a general
API for other projects.

Relevant code and prior plans:

- `tools/sase_sibling_commit_stop_hook`
- `tests/test_sibling_commit_stop_hook.py`
- `sdd/tales/202604/sibling_repo_commit_push.md`
- `sdd/tales/202604/fix_codex_sibling_commit_stop_hook.md`
- `sdd/tales/202605/qwen_global_commit_stop_hook.md`

## Problems To Fix

1. **No user-facing sibling-repo configuration.** A new user cannot declare "this project has sibling repo X" without
   writing a project-specific hook or relying on naming conventions.

2. **Hardcoded SASE path assumptions.** The hook only understands `../sase-*` and chezmoi. It cannot express
   non-SASE repo names, nested paths, hosted refs, or project-specific sibling sets.

3. **Agents are pointed at primary sibling checkouts.** Current hook guidance says `cd ../sase-core`. The new
   requirement is that agents use a sibling workspace with the same workspace number as the main project, e.g.
   `../sase-core_102` from `sase_102`.

4. **No shared resolved sibling map at launch time.** The agent process knows its main `workspace_num`, but there is no
   canonical mapping from sibling alias to resolved sibling workspace dir.

5. **Deferred `%wait` agents need late sibling resolution.** Deferred agents initially run with workspace `0` and only
   claim a real workspace after dependencies finish. Their sibling workspace map must be recomputed after the real
   workspace number is assigned.

6. **Stop hooks cannot distinguish user-owned sibling edits from arbitrary nearby dirty repos.** A glob scanner will
   always be too broad or too narrow. First-class config lets hooks check exactly the repos the project opted into.

## Recommended Model

Add a top-level config section:

```yaml
sibling_repos:
  - name: core
    path: ../sase-core
  - name: github
    path: ../sase-github
  - name: docs
    path: ~/projects/company/product-docs
```

Keep the first version intentionally small:

- `name`: stable alias for prompts, logs, env vars, and hook messages.
- `path`: primary checkout path, expanded like `~` and env vars.
- `workspace`: optional object for later extension. Default is clone-style `path_<N>` for `N > 1` and `path` for
  `N == 1`.

An extended future shape can support:

```yaml
sibling_repos:
  - name: core
    path: ../sase-core
    workspace:
      strategy: suffix
      template: "{primary}_{workspace_num}"
  - name: vendored
    path: ../vendor/tooling
    workspace:
      strategy: none
  - name: plugin
    workflow_type: gh
    ref: my-org/plugin-repo
```

For the first implementation, avoid `workflow_type/ref` until the basic path-backed model is stable. It is enough to
support "I already have a sibling primary checkout; make/use a matching numbered checkout for agents."

## Resolution Contract

At agent launch, resolve sibling repos from the merged config in the main project context:

1. Read `sibling_repos` from `load_merged_config()`. Because SASE already supports local `sase.yml`, new users can add
   this in a project-local config without editing global config.
2. Resolve each primary `path` relative to the main primary workspace, not relative to the current agent workspace.
   This avoids turning `../core` from `myapp_102` into the wrong path when the primary layout is `myapp/` and `core/`.
3. For the agent's assigned `workspace_num`, compute each sibling workspace:
   - `workspace_num == 0`: no numbered sibling workspace; use primary only for read-only discovery or defer.
   - `workspace_num == 1`: primary sibling checkout.
   - `workspace_num > 1`: default `primary_<workspace_num>`.
4. Ensure clone-backed sibling workspaces exist before exposing them to the agent. For Git repos, reuse the same
   `ensure_git_clone(primary, workspace_num)` helper used by primary workspaces.
5. Export both machine-readable JSON and convenient per-sibling env vars.

Suggested env:

```text
SASE_SIBLING_REPOS_JSON=[{"name":"core","primary_dir":".../sase-core","workspace_dir":".../sase-core_102","workspace_num":102}]
SASE_SIBLING_REPO_CORE_DIR=.../sase-core_102
SASE_SIBLING_REPO_CORE_PRIMARY_DIR=.../sase-core
```

The JSON env is the canonical API. The alias-specific env vars are ergonomics and should sanitize `name` to uppercase
`[A-Z0-9_]`.

Also write the same data into `agent_meta.json`, so the TUI and post-run tools can render and audit what was made
available.

## Agent Guidance

The user-facing instruction should be generated from the resolved map, not from hardcoded repo names. A concise
AGENTS-style note can be appended to the agent prompt during launch:

```text
Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/projects/github/sase-org/sase-core_102
- github: /home/bryan/projects/github/sase-org/sase-github_102

When editing a sibling repo, use its workspace-matched directory, not the primary checkout.
```

This is better than relying only on environment variables because agents often inspect prompt text before env. Keep it
short to avoid turning every launch into a large instruction payload.

## Stop-Hook Behavior

Replace hardcoded scanning in `tools/sase_sibling_commit_stop_hook` with:

1. If `SASE_SIBLING_REPOS_JSON` is present, scan exactly those `workspace_dir` paths.
2. If it is absent, fall back to current hardcoded behavior for compatibility with older sessions.
3. In block messages, tell agents to `cd <workspace_dir>`, not primary sibling paths.
4. Preserve one-shot session deduplication and runtime-specific block payloads.

This makes the hook portable while preserving the SASE repo's current behavior during rollout.

## Where The Logic Should Live

Recommended first landing:

- Python config parsing/resolution in a new module such as `src/sase/sibling_repos.py`.
- Launch integration in `src/sase/agent/launch_spawn.py` / `src/sase/agent/launch_executor.py`, where
  `workspace_num` and `workspace_dir` are already finalized.
- Deferred `%wait` recomputation in `claim_deferred_workspace()` after the real workspace is claimed.
- Hook consumption in `tools/sase_sibling_commit_stop_hook`.

Recommended durable shape:

- Add sibling-repo wire records to the Rust launch boundary in `../sase-core/crates/sase_core/src/agent_launch/mod.rs`.
- Add matching Python dataclasses in `src/sase/core/agent_launch_wire.py`.
- Keep filesystem cloning/ensuring in Python initially, because `ensure_git_clone()` and workspace providers currently
  live there.

This respects the Rust core boundary: the portable contract and launch metadata belong in core; host-specific checkout
and config plumbing can remain Python until there is a broader workspace-provider migration.

## Open Design Questions

1. **Should missing primary sibling paths be an error?**
   Recommended: default to a warning and omit that sibling from the resolved map. Add `required: true` later for teams
   that want strict enforcement.

2. **Should SASE auto-clone missing sibling repos?**
   Recommended: not in phase 1 for path-backed config. Auto-clone needs a remote/ref model and auth decisions. New users
   can start by checking out sibling repos once and adding paths.

3. **How should workspace `1` behave?**
   Use the primary sibling checkout for workspace `1`, matching existing primary workspace behavior. If users want even
   workspace `1` isolated, add a future `primary_is_workspace: false` option.

4. **How should non-git sibling repos work?**
   Phase 1 can support existing directories with `strategy: none`, but same-number isolation requires a provider.
   Clone-backed git is the practical first target.

5. **Should sibling repos get RUNNING claims?**
   Not initially. The main project RUNNING claim owns the agent slot. Sibling repo workspaces should be recorded in
   agent metadata and hook logs. A later cross-project claim model may be useful, but it is a larger coordination
   feature.

## Proposed Implementation Phases

### Phase 1: Config and resolver

- Add `sibling_repos` to `config/sase.schema.json` and `docs/configuration.md`.
- Add a resolver module that returns `SiblingRepoResolution` records.
- Unit test path expansion, relative path anchoring, alias sanitization, workspace-number suffixing, missing paths, and
  JSON serialization.

### Phase 2: Launch integration

- Resolve sibling repos after the main workspace number is known.
- Export `SASE_SIBLING_REPOS_JSON` and alias env vars to child agents.
- Write the resolved map into `agent_meta.json`.
- Append a short prompt note listing workspace-matched sibling dirs.
- Add tests around `spawn_agent_subprocess()` env and metadata.

### Phase 3: Deferred workspace support

- For `%wait` agents, do not expose numbered sibling dirs while the agent is in workspace `0`.
- After `claim_deferred_workspace()` assigns a real workspace, recompute sibling workspace dirs and update env before
  execution continues.
- Add focused tests for deferred agents transitioning from `0` to `100+`.

### Phase 4: Stop hook conversion

- Teach `tools/sase_sibling_commit_stop_hook` to prefer `SASE_SIBLING_REPOS_JSON`.
- Keep the current hardcoded scanner as fallback.
- Update tests so dirty sibling workspace dirs block, dirty primary sibling dirs do not block when the session has a
  numbered sibling workspace, and block messages point at the numbered workspace.

### Phase 5: Rust wire contract

- Add a sibling-repo resolved record to `AgentLaunchRequestWire` / `AgentLaunchPreparedWire`.
- Expose it through the Python facade.
- Keep backward compatibility by treating missing fields as empty lists.

## Test Matrix

Minimum regression coverage:

- Config schema accepts the basic list form and rejects malformed entries.
- Resolver maps `../core` from primary `/repo/main` plus workspace `102` to `/repo/core_102`.
- Resolver does not accidentally anchor relative paths to `/repo/main_102`.
- Launch env includes `SASE_SIBLING_REPOS_JSON` with workspace-matched dirs.
- The hook scans configured `workspace_dir` and ignores `primary_dir` for numbered sessions.
- Deferred `%wait` agents recompute sibling dirs after real workspace claim.
- Multi-prompt and multi-model fanout give every slot its own sibling mapping using that slot's workspace number.

## Recommendation

Implement path-backed `sibling_repos` first and make the resolved sibling workspace map part of the launch contract.
This gives new users a simple project-local `sase.yml` setup, removes SASE-specific hardcoded globs, and directly
satisfies the requirement that agents use sibling workspaces with the same workspace number as their main workspace.

Do not begin with a new plugin system for sibling repos. The existing workspace-provider layer already knows how to
create numbered clone workspaces; sibling repos need a small configuration and launch-resolution layer first. If later
teams need hosted refs, non-git providers, or stricter claim coordination, those can build on the same resolved record
shape without changing the agent-facing contract.
