---
title: "Environment variables"
description:
  "Environment variables that configure providers, SDD, plugins, runtime, and
  workspaces."
---

# Environment variables

Environment variables that configure providers, SDD, plugins, runtime, and workspaces.

<a id="environment-variables-1"></a>

## Environment Variables

### LLM Provider

The detailed [LLM environment-variable reference](#environment-variable-reference)
covers provider and model-selection variables.

### VCS Provider

| Variable                                   | Description                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_VCS_PROVIDER`                        | Override VCS provider selection (`git`, `hg`, or `auto`).                                                                                                                                                                                                                                                                    |
| `SASE_WORKSPACE_ROOT`                      | Override the workspace-root base for this process. Use an absolute path; `WorkspaceStore` appends `<project_key>/<project>_<num>/` for managed checkouts.                                                                                                                                                                    |
| `SASE_BUG_ID`                              | Bug ID for PR workflows. When set and non-zero, injects `SASE_BUG=<id>` into PR tags and Patch.                                                                                                                                                                                                                              |
| `SASE_BEAD_ID`                             | Assigned bead ID for commit workflows. When set, `sase stitch create` adds a linked `SASE_BEAD=` footer tag, leaves the subject unchanged, and requires an explicit `-B/--bead-action keep\|close` (see [Explicit Bead Action](../contribute/commit-workflow-orchestrator.md#explicit-bead-action)).                         |
| `SASE_GH_TIMEOUT`                          | Positive per-attempt timeout, in seconds, for SASE's retried `gh` CLI calls (default: `20`).                                                                                                                                                                                                                                 |
| `SASE_GH_MAX_RETRY_SLEEP`                  | Positive cap, in seconds, on one wait between `gh` retries, including a server-requested retry delay (default: `60`).                                                                                                                                                                                                        |
| `SASE_GIT_LOCK_RETRY_DELAYS`               | Comma-separated finite non-negative delays, in seconds, for shared Git `index.lock` recovery backoff (default: `0.1,0.2,0.4,0.8,1.6,3.2`). Invalid, empty, negative, NaN, or infinite values use that built-in schedule. An explicit empty caller schedule means no backoff; it does not skip the 15-second stale-age check. |
| `SASE_LINKED_REPOS_JSON`                   | Resolved linked-repo metadata passed to launched agents.                                                                                                                                                                                                                                                                     |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`          | Workspace-matched directory for one configured linked repo.                                                                                                                                                                                                                                                                  |
| `SASE_LINKED_REPO_<ENV_NAME>_PRIMARY_DIR`  | Primary checkout directory for one linked repo.                                                                                                                                                                                                                                                                              |
| `SASE_SIBLING_REPOS_JSON`                  | Compatibility alias for `SASE_LINKED_REPOS_JSON`.                                                                                                                                                                                                                                                                            |
| `SASE_SIBLING_REPO_<ENV_NAME>_DIR`         | Compatibility alias for `SASE_LINKED_REPO_<ENV_NAME>_DIR`.                                                                                                                                                                                                                                                                   |
| `SASE_SIBLING_REPO_<ENV_NAME>_PRIMARY_DIR` | Compatibility alias for `SASE_LINKED_REPO_<ENV_NAME>_PRIMARY_DIR`.                                                                                                                                                                                                                                                           |

`<ENV_NAME>` is the uppercase, sanitized repository name. Duplicate names receive a
numeric suffix.

### SDD Git Operations

| Variable                                    | Description                                                                                                                                                                  |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_SDD_STORE_WRITE_LOCK_TIMEOUT`         | Non-negative seconds to wait for the cooperative SDD store lock. Overrides both the 10-second metadata-write default and 180-second worktree-mutation default.               |
| `SASE_SDD_GIT_LOCK_RETRY_DELAYS`            | Comma-separated finite non-negative delays, in seconds, for SDD Git lock failures. Invalid, empty, negative, NaN, or infinite values use the built-in shared retry schedule. |
| `SASE_SDD_GIT_LOCAL_TIMEOUT`                | Positive seconds allowed for one local SDD Git command (default: 30).                                                                                                        |
| `SASE_SDD_GIT_NETWORK_TIMEOUT`              | Positive seconds allowed for one network SDD Git attempt (default: 120). For progress-reporting clone, fetch, and push, it is the no-progress stall limit.                   |
| `SASE_SDD_GIT_NETWORK_TRANSFER_CEILING`     | Positive wall-clock cap, in seconds, on one progress-reporting clone, fetch, or push even while it keeps making progress (default: 900).                                     |
| `SASE_SDD_GIT_SLOW_MS`                      | Positive duration, in milliseconds, at which a successful SDD Git command is logged as slow (default: 1000).                                                                 |
| `SASE_SDD_REMOTE_CLONE_CONCURRENCY`         | Positive number of SDD sidecar remote clones allowed to run at once on this machine (default: 1).                                                                            |
| `SASE_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT`        | Positive seconds an epic plan launch waits for another launch in the same project (default: 900).                                                                            |
| `SASE_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT` | Positive seconds an approval preflight waits for an in-flight epic launch before deferring its health check to the detached launch (default: 120).                           |

See
[SDD storage concurrency and recovery](../contribute/sdd-storage.md#concurrency-and-recovery)
for the lock, recovery snapshot, and failed-integration cooldown behavior.

### Plugin System

These switches affect plugin-provided resources and declarative artifact providers. The
VCS, workspace, and LLM registries load provider entry points directly.

| Variable                            | Description                                                              |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `SASE_DISABLE_PLUGINS`              | Disable plugin resources and third-party artifact-provider entry points. |
| `SASE_DISABLE_PLUGIN_MACROS`        | Disable plugin-provided macro and workflow files.                        |
| `SASE_DISABLE_PLUGIN_CONFIG`        | Disable plugin-provided `default_config.yml` files and config macros.    |
| `SASE_DISABLE_PLUGIN_ARTIFACT_REFS` | Disable plugin-provided artifact-reference specifications.               |
| `SASE_DISABLE_PLUGIN_FILE_HOOKS`    | Disable plugin-provided file-hook templates.                             |
| `SASE_DISABLE_PLUGIN_TASK_TYPES`    | Disable plugin-provided task-type specifications.                        |

### State Root

| Variable                  | Description                                                                                                                                                                                                                                                                                                           |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_HOME`               | Override the SASE state root. Defaults to `~/.sase`; project files, chats, artifacts, notifications, dismissed bundles, saved groups, and logs move under this root.                                                                                                                                                  |
| `SASE_PROC_LOG_MAX_BYTES` | Maximum active proc-log segment size in bytes (default: 2 MiB); `0` disables rotation.                                                                                                                                                                                                                                |
| `SASE_CUTOVER_BACKUP_DIR` | Root the [local state cutover kit](upgrading/local-state.md#local-state-cutover-1) writes backups, restores, and run journals under. Defaults to `~/cutover-backups`; it must not be nested beneath `~/.sase`, `~/.local/state/sase`, or `~/sase`, and users of other runtime roots must keep it separate themselves. |

### General

| Variable                             | Description                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_TMPDIR`                        | Override SASE's [managed temp root](config/runtime-and-storage.md#managedtmp). When unset, the root is `$SASE_HOME/tmp` (`~/.sase/tmp` by default). Keep it off tmpfs and out of file-sync folders, because build scratch can be large.                                                                                                                                                                                               |
| `SASE_DETACH_SCOPE_DISABLE`          | Set to `1`, `true`, `yes`, or `on` to stop detached agent runners, procs, monitors, and scheduler/hook/bead-sync workers from escaping SASE's systemd cgroup. By default on Linux, when the launcher runs inside a SASE-owned systemd unit or scope, or anywhere under a reachable user systemd manager, and `systemd-run` exists, SASE starts that work in its own transient `systemd-run --user --scope` with `OOMPolicy=continue`. |
| `SASE_AXE_DISABLE_SYSTEMD_SCOPE`     | Compatibility alias for `SASE_DETACH_SCOPE_DISABLE`: set to a truthy value to stop the same detached work from escaping SASE's systemd cgroup.                                                                                                                                                                                                                                                                                        |
| `SASE_FEATURE_FLAGS`                 | Strict JSON object of booleans carrying the resolved feature-flag snapshot for this process and its children. Outranks config layers and a saved machine preference. Root `-f/--enable-feature` and `-F/--disable-feature` merge into this variable so launched processes inherit those CLI overrides.                                                                                                                                |
| `SASE_MACRO_LSP_CMD`                 | Override the command used by `sase lsp` to launch the macro language server.                                                                                                                                                                                                                                                                                                                                                          |
| `SASE_CORE_DIR`                      | Preferred `sase-core` source checkout for `Justfile` Rust build/install targets; overrides `../sase-core`.                                                                                                                                                                                                                                                                                                                            |
| `SASE_RUST_DEV_PROFILE`              | Cargo profile for the `just` Rust dev-install recipes and editable `sase-core` update prebuilds (default: `dev-update`); set `release` to force the published release profile. See [Rust Backend](../contribute/rust-backend.md).                                                                                                                                                                                                     |
| `SASE_FORMAT_VENV_DIR`               | Virtualenv the `just` formatting recipes install their narrow formatter tool set into (default: `.venv-format`).                                                                                                                                                                                                                                                                                                                      |
| `SASE_PYTEST_DIST`                   | xdist scheduler for the `just` pytest recipes: `worksteal` (default) or `loadfile` (fallback). Invalid values fail before worker-token acquisition; serial inline-snapshot modes ignore it.                                                                                                                                                                                                                                           |
| `SASE_PYTEST_SANDBOX_DIR`            | Pytest-published sandbox root inherited by test subprocesses; bead-store writes during pytest must target a path at or below this directory.                                                                                                                                                                                                                                                                                          |
| `SASE_PYTEST_WORKERS`                | Request exactly this positive number of governed xdist workers for the `just` pytest recipes. The request must fit the active host pool unless accounting is deliberately disabled.                                                                                                                                                                                                                                                   |
| `SASE_PYTEST_WORKER_FLOOR`           | Positive minimum token grant required to start an automatically sized `just` pytest run. Defaults to 4, clamped on smaller hosts, and cannot exceed the ceiling or host pool.                                                                                                                                                                                                                                                         |
| `SASE_PYTEST_WORKER_CEILING`         | Positive maximum token grant for an automatically sized `just` pytest run. Defaults to at most 28 while reserving another floor-sized grant when capacity permits.                                                                                                                                                                                                                                                                    |
| `SASE_ALLOW_UNSANDBOXED_BEAD_WRITES` | Test-only override; set to `1` to allow a pytest bead-store write outside `SASE_PYTEST_SANDBOX_DIR` for a deliberate exception.                                                                                                                                                                                                                                                                                                       |
| `SASE_ACE_PAGE_GROUP_ISOLATION`      | Test-only override; set to `1` to make `AcePageGroup` create a fresh `AcePage` for each checkout instead of sharing one app across related tests. `just test-ace-page-group-isolated` sets this for every module in `tests/ace/tui/ace_page_group_files.txt`.                                                                                                                                                                         |
| `SASE_TEST_GATE_SLOTS`               | Override the host-wide pytest capacity in worker tokens. Unlike the former whole-suite gate, one token now represents one xdist worker.                                                                                                                                                                                                                                                                                               |
| `SASE_TEST_GATE_DIR`                 | Override the shared pytest token-pool directory. Defaults to a UID-scoped `sase-pytest-tokens-<uid>` directory under `/tmp`.                                                                                                                                                                                                                                                                                                          |
| `SASE_TEST_GATE_TIMEOUT`             | Non-negative seconds to wait for a sufficient worker-token grant before failing with requested capacity and current-holder diagnostics.                                                                                                                                                                                                                                                                                               |
| `SASE_TEST_GATE_STALE`               | Non-negative seconds without a progress heartbeat before a _live_ holder is treated as wedged and reclaimed. Default `1800` (30 minutes). `0` disables stale-heartbeat reclaim.                                                                                                                                                                                                                                                       |
| `SASE_TEST_GATE_MAX_HOLD`            | Non-negative seconds a live holder may keep its grant even while heartbeats continue. Default `14400` (4 hours). `0` disables the absolute age cap.                                                                                                                                                                                                                                                                                   |
| `SASE_TEST_GATE_WATCHDOG`            | Non-negative seconds between a holder's self-checks of those bounds. Default `30`. `0` disables the holder-side watchdog; waiters still reclaim.                                                                                                                                                                                                                                                                                      |
| `SASE_TEST_GATE_DISABLED`            | Set to `1` to bypass the pytest worker-token pool deliberately. The bypass takes no tokens and never waits, but its width is still clamped to the host budget and announced on stderr; raise `SASE_TEST_GATE_SLOTS` to run wider. Every held lease also exports it to prevent nested pytest deadlocks.                                                                                                                                |
| `SASE_TEST_GATE_GOVERNED`            | Internal marker exported by every held worker-token lease, meaning an ancestor already paid for this process's workers. It is what separates a corroborated exemption from a top-level bypass; inherited pytest configuration must not lease again.                                                                                                                                                                                   |
| `SASE_TEST_SHARD`                    | `<1-based index>/<1-based count>` (e.g. `3/8`). Runs exactly one deterministic, balanced slice of the whole fast suite instead of all of it; `just` pytest recipes only accept this in `fast` mode and reject an explicit test selector alongside it. Set by `.github/workflows/master-gate.yml`, not intended for manual use.                                                                                                        |
| `SASE_JUST_INVOCATION_DIR`           | Internal value set by `just` so test selectors are normalized from the caller's directory.                                                                                                                                                                                                                                                                                                                                            |

The pytest variables above describe one UID-scoped pool shared by `just` recipes and
direct parallel pytest controllers. The first active lease records the effective
capacity; later launchers honor that capacity until every holder exits, even if
`MemAvailable` changes in the meantime. Automatic launchers require their floor
atomically and then take currently free tokens up to the ceiling. Exact
`SASE_PYTEST_WORKERS` requests wait for the complete request, and an explicit
`SASE_TEST_GATE_SLOTS` value must match an already-active pool. The former whole-suite
slot gate is fully superseded: admission, diagnostics, and SIGKILL-safe release are all
expressed in worker tokens. A live holder also writes a progress heartbeat (collection
and completed test calls). Waiters and a holder-side watchdog reclaim a grant whose
heartbeat is older than `SASE_TEST_GATE_STALE` or whose age exceeds
`SASE_TEST_GATE_MAX_HOLD`: the watchdog releases its own tokens, and a waiter SIGTERMs
(then SIGKILLs) a still-held wedged process so `flock` can return the tokens to the
pool. Waiting and timeout messages print each holder's age, heartbeat age, and reclaim
reason.

### Workspace Management (Internal)

These are set automatically by sase when launching agent subprocesses and are not
intended for manual use. Workspace plugins declare an env-var prefix, then SASE passes
`<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and `<PREFIX>_WORKSPACE_DIR` into
the child process. Built-in prefixes include `SASE_GIT` for `#git`; plugin packages may
add prefixes such as `SASE_GH` for GitHub. The launcher clears inherited
`SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` variables
before applying the current launch's values so follow-up agents cannot inherit stale
workspace claims.

| Variable                 | Description                                                                |
| ------------------------ | -------------------------------------------------------------------------- |
| `SASE_SYNC_CWD`          | Working directory override for sync operations.                            |
| `<PREFIX>_PRE_ALLOCATED` | Set to `"1"` when a workspace provider has pre-allocated a launch context. |
| `<PREFIX>_WORKSPACE_NUM` | Pre-allocated workspace number.                                            |
| `<PREFIX>_WORKSPACE_DIR` | Pre-allocated workspace directory path.                                    |
| `SASE_GIT_*`, ...        | Concrete forms for built-in and plugin-provided workspace prefixes.        |

## Environment Variable Reference

Complete reference of environment variables used by the LLM provider layer.

### Generic (Provider-Agnostic)

| Variable                             | Description                                                                                                                                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_LLM_EXEC_PROVIDER`             | Execute through this provider while retaining the requested provider/model metadata                                                                                                                       |
| `SASE_LLM_LARGE_ARGS`                | Extra CLI args for `large` tier invocations                                                                                                                                                               |
| `SASE_LLM_SMALL_ARGS`                | Extra CLI args for `small` tier invocations                                                                                                                                                               |
| `SASE_MODEL_TIER_OVERRIDE`           | Force all invocations to a specific model tier                                                                                                                                                            |
| `SASE_MODEL_SIZE_OVERRIDE`           | Compatibility alias for `SASE_MODEL_TIER_OVERRIDE`                                                                                                                                                        |
| `SASE_PROVIDER_SYNC_CEILING_SECONDS` | Set by the agent runner around each provider invocation: that harness's hard per-command kill ceiling in seconds (unset when the provider declares none); scrubbed at agent, monitor, and proc boundaries |

`SASE_LLM_EXEC_PROVIDER` must name a registered provider. It changes subprocess dispatch
and execution-provider retry policy only; agent, step, and chat metadata continue to
show the provider and model the user requested. Run artifacts record the dispatched
provider separately as `exec_llm_provider`.

### Claude-Specific

| Variable                             | Description                                                                                          |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `SASE_CLAUDE_LARGE_ARGS`             | Claude-specific extra args for `large` tier                                                          |
| `SASE_CLAUDE_SMALL_ARGS`             | Claude-specific extra args for `small` tier                                                          |
| `SASE_CLAUDE_MAX_WAIT_CONTINUATIONS` | [Single-turn wait guard](providers/claude.md#single-turn-wait-guard) continuation cap (default: `2`) |

### Codex-Specific

| Variable                         | Description                                     |
| -------------------------------- | ----------------------------------------------- |
| `SASE_CODEX_PATH`                | Path to the Codex CLI binary                    |
| `SASE_CODEX_LARGE_ARGS`          | Codex-specific extra args for `large` tier      |
| `SASE_CODEX_SMALL_ARGS`          | Codex-specific extra args for `small` tier      |
| `SASE_CODEX_DISABLE_SHADOW_HOME` | Set to `1` to disable the disposable Codex home |

### Qwen-Specific

| Variable               | Description                               |
| ---------------------- | ----------------------------------------- |
| `SASE_QWEN_PATH`       | Path to the Qwen Code CLI binary          |
| `SASE_QWEN_LARGE_ARGS` | Qwen-specific extra args for `large` tier |
| `SASE_QWEN_SMALL_ARGS` | Qwen-specific extra args for `small` tier |

### Antigravity (`agy`)-Specific

| Variable                                 | Description                                                        |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `SASE_AGY_PATH`                          | Path to the Antigravity CLI binary (default: `"agy"`).             |
| `SASE_AGY_PRINT_TIMEOUT`                 | Override the `agy --print-timeout` Go duration (default: `"24h"`). |
| `SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS` | Override the no-progress continuation cap (default: `2`).          |
| `SASE_AGY_LARGE_ARGS`                    | Antigravity-specific extra args for `large` tier                   |
| `SASE_AGY_SMALL_ARGS`                    | Antigravity-specific extra args for `small` tier                   |

### OpenCode-Specific

| Variable                   | Description                                   |
| -------------------------- | --------------------------------------------- |
| `SASE_OPENCODE_PATH`       | Path to the OpenCode CLI binary               |
| `SASE_OPENCODE_LARGE_ARGS` | OpenCode-specific extra args for `large` tier |
| `SASE_OPENCODE_SMALL_ARGS` | OpenCode-specific extra args for `small` tier |

### Muse Code-Specific

| Variable                           | Description                                                                                        |
| ---------------------------------- | -------------------------------------------------------------------------------------------------- |
| `SASE_MUSE_PATH`                   | Path to the Muse Code CLI binary (default: `muse` on `PATH`)                                       |
| `SASE_MUSE_LARGE_ARGS`             | Muse-specific extra args for `large` tier                                                          |
| `SASE_MUSE_SMALL_ARGS`             | Muse-specific extra args for `small` tier                                                          |
| `SASE_MUSE_SANDBOX`                | Set to `on` to keep Muse's sandbox with `--sandbox-network enabled`                                |
| `SASE_MUSE_MAX_WAIT_CONTINUATIONS` | [Stranded-wait guard](providers/muse.md#single-turn-normalization) continuation cap (default: `2`) |

SASE always launches Muse with `MUSE_NO_AUTO_UPDATE=1` so the launcher cannot swap the
binary mid-run; `sase agent-cli update muse` sets `MUSE_SYNC_UPDATE=1` instead. The two
must never be set together.

### Grok-Specific

| Variable               | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `SASE_GROK_PATH`       | Path to the Grok Build CLI binary (default: `grok` on `PATH`) |
| `SASE_GROK_LARGE_ARGS` | Grok-specific extra args for `large` tier                     |
| `SASE_GROK_SMALL_ARGS` | Grok-specific extra args for `small` tier                     |

SASE always launches Grok with `--no-auto-update` so it cannot swap its own binary
mid-run; `sase agent-cli update grok` runs Grok Build's own `update` subcommand instead.

External provider plugins document their own environment variables in their respective
repos.

## Related

- [Configuration reference](config/index.md) — generated key paths and defaults.
- [Providers and models](providers/index.md) — provider setup.
