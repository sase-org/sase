---
title: Diagnostics and support reports
description: Read-only validation, diagnostics, logs, and support bundle behavior.
---

# Diagnostics and support reports

## `sase validate`

`sase validate` is the top-level portable SASE validation command. It takes no options
and runs, in order, `sase doctor -C plugins.required` (so a missing required plugin is
never reported as spurious generated-file drift), the explicit
`sase init memory --check`, `sase init repo --check`, and `sase init skills --check`
surfaces, `sase doctor -C config.file_hooks`, `sase plan links validate`, and
`sase agent prompts validate`. It prints one `ok`, `skip`, or `fail` line per check and
exits non-zero if any check fails; the prompt-archive check reports `skip` rather than
failing when no agents-sidecar prompt archive context is available. It deliberately
leaves the machine-local Config and machine planners to bare `sase init --check` and
`sase doctor`, so clean CI hosts do not need a synthetic machine identity. The command
can still fail on user/home memory or skill deployment drift even when repository-local
SDD validation passes.

A check can pass and still have something to say. When a check that exits 0 prints its
own `Warnings:` section — `sase init skills --check` deferring a chezmoi redeploy is the
common case — `sase validate` collects those lines and reprints them under a single
`Warnings:` block, after the per-check status lines and before any failure output. The
block is informational: it does not change the exit code, and it is separate from the
stdout dump that a failing or skipped check still produces.

## `sase doctor`

Runs the read-only support diagnostics bundle for the active runtime, configuration,
provider setup, project/workspace state, bead store, agent index, and telemetry when
configured. Default mode is bounded and safe to run before asking for help; deep mode
adds slower read-only checks.

<a id="cli-options-31"></a> Moved to [sase doctor](diagnostics.md#sase-doctor).

<a id="command-behavior-19"></a> Moved to
[Diagnostics and support reports](diagnostics.md#command-behavior-19).

## Command behavior {#command-behavior-19}

Use `sase doctor -L` to list targeted check IDs. Useful focused checks include
`runtime`, `llm.default`, `plugins.required`, `plugins.resources`, `beads.task_types`,
`project.junk_directories`, `project.primary_sidecar_link_dirt`,
`workspace.missing_checkouts`, `workspace.occupancy_conflicts`, and
`config.model_macros`, `config.macro_definitions`, `config.macro_input_types`, and
`config.macro_directives`. The two inventory checks report telemetry-only directories
without ProjectSpecs and registered workspace paths missing from disk; both are
read-only and provide cleanup/repair guidance. `workspace.occupancy_conflicts` reports
RUNNING-field and occupant-record collisions and never auto-repairs. `llm.cli_shadow`
reports different installed versions of the same provider CLI found on `PATH` or in
`NVM_BIN`; see [provider inventory](providers/agent-clis.md#inventory-and-updates) for
the executable selection and recovery details. `config.macro_input_types` lists unknown
type names, the deprecated `string` alias, and enum choice issues across macro sources.
`config.macro_directives` locates definition files that still use retired directive
syntax. `agent_holds.stale` warns about
[agent holds](agents/agent-holds.md#sase-agent-hold) whose armer died or whose TTL
passed; it reconciles the hold store the same way `sase agent hold list` does, so the
stale records it reports are pruned as a side effect.

Default exit behavior is `0` for `OK`, `WARN`, and `SKIP`, and `1` for `ERROR`. Attach
`sase doctor -v` or `sase doctor -j` when asking for help.

## `sase version`

`sase version` reports the local runtime that the current `sase` process is using. It
does not query PyPI, GitHub, or latest available releases. The inventory always includes
the host `sase` package and the required `sase-core-rs` Rust core distribution, then
adds installed SASE plugin packages discovered through SASE entry points, SASE console
scripts, or `sase-*` distribution names.

The default human output is a compact runtime panel plus a package table with role,
effective version, and code directory. Development checkouts use PEP 440 local versions
such as `0.1.2+4.g26c39e004` or `0.1.2+0.g26c39e004.dirty`. Editable installs prefer
source metadata over stale installed distribution metadata, while `--verbose` and
`--json` expose both values for auditability.

<a id="cli-options-34"></a> Moved to [sase version](diagnostics.md#sase-version).

## `sase telemetry`

With no subcommand, `sase telemetry` prints a delegation notice and runs
`sase telemetry list`.

<a id="cli-options-36"></a> Moved to [sase telemetry](diagnostics.md#sase-telemetry).

<a id="command-behavior-23"></a> Moved to
[Diagnostics and support reports](diagnostics.md#command-behavior-23).

## Command behavior {#command-behavior-23}

See [Telemetry details](../contribute/telemetry.md) for the full CLI reference including
per-subcommand flags.

## `sase logs`

<a id="cli-options-37"></a> Moved to [sase logs](diagnostics.md#sase-logs).

<a id="command-behavior-24"></a> Moved to
[Diagnostics and support reports](diagnostics.md#command-behavior-24).

## Command behavior {#command-behavior-24}

Supported date range formats:

- **Absolute**: `YYmmdd` or `YYmmddHHMMSS`
- **Relative**: `-Nd` (days ago), `-Nh` (hours ago), `-Nm` (minutes ago), `0d` (today)
- **Ranges**: `START..END` (e.g., `-7d..0d`); single point means "from that point to
  now"

The run and event inputs at `~/.sase/logs/runs.jsonl` and `events.jsonl` rotate
independently before appending a record would make a non-empty file exceed 2 MiB.
Rotation keeps one `.1` generation and replaces an older backup; set
`SASE_RUN_LOG_MAX_BYTES` to another byte limit, or `0` for no size rotation. The current
`sase logs` collector reads only the active `.jsonl` files and skips malformed lines
there, so copy the matching `.1` files separately when a support bundle must include
records from the previous generation.

## `sase usage`

Bare `sase usage` defaults to `sase usage list`. Listing is strictly offline: it reads
the cached subscription-usage store and never starts AXE, logs in, or calls a provider
CLI/API. Output is Rich on an interactive color terminal and automatically becomes plain
for redirected output, `NO_COLOR`, or a dumb terminal.

<a id="cli-options-44"></a> Moved to [sase usage](diagnostics.md#sase-usage).

<a id="command-behavior-28"></a> Moved to
[Diagnostics and support reports](diagnostics.md#command-behavior-28).

## Command behavior {#command-behavior-28}

`--json` and `--plain` are mutually exclusive. Background mode returns after submission
and renders the receipt instead of the cache. Unknown providers are usage errors.
Collection requires `llm_provider.usage_metrics.enabled`; see
[Subscription Usage](providers/usage.md#subscription-usage).

## Operations And Diagnostics

Flag and option details live in the generated [CLI command groups](cli/index.md):

- [sase doctor](cli/doctor.md), [sase config](cli/config.md),
  [sase usage](cli/usage.md), [sase flag](cli/flag.md),
  [sase file-hook](cli/file-hook.md), [sase core](cli/core.md)
- [sase migrate](cli/migrate.md), [sase validate](cli/validate.md),
  [sase telemetry](cli/telemetry.md), [sase version](cli/version.md)
- [sase plugin](cli/plugin.md), [sase update](cli/update.md),
  [sase completion](cli/completion.md), [sase logs](cli/logs.md),
  [sase revive-log](cli/revive-log.md)
- [sase artifact](cli/artifact.md), [sase agent-cli](cli/agent-cli.md),
  [sase var](cli/var.md), [sase path](cli/path.md), [sase repo](cli/repo.md),
  [sase tool](cli/tool.md), [sase disk](cli/disk.md),
  [sase workspace](cli/workspace.md), [sase mobile](cli/mobile.md)

Workflows: [Configuration](config/index.md), [Plugins](integrations/plugins.md),
[Shell completion](integrations/completion.md), [Telemetry](../contribute/telemetry.md),
[Workspace](agents/index.md), [Mobile gateway](integrations/mobile-gateway.md).

The `sase artifact show`, `read`, `path`, `open`, and `link` commands take logical
references without a leading `@`, for example
`sase artifact show file:default:<digest>`. Add the sigil when embedding the same
reference in a launch prompt: `sase run "review @file:default:<digest>"`. This
bare-CLI/`@`-in-prompts rule also applies to document roles, chats, beads, agents,
commits, and bugs. `path` accepts only references with a filesystem identity; `open` can
also open a bug in a browser but rejects commits.

`stats`, `prune`, `reclaim`, and `trash` are the store's lifecycle commands, and they
are deliberately staged: `stats` only reports, `prune` and `reclaim` print a plan and
change nothing unless `--apply` is passed, and every removal either of them makes moves
the stored bytes **and** the complete index row into a restorable trash under
`~/.sase/artifacts/trash/`. `sase artifact trash restore` puts an entry back; only
`sase artifact trash purge` deletes permanently, and without `-a/--all` it purges only
entries older than `artifacts.retention.trash_grace_days`. Trashed bytes still occupy
disk until that purge runs. Explicit artifacts, artifacts a ProjectSpec, plan, bead, or
research document references, artifacts recorded in the consumption ledger, and the
newest capture of every label are never selected; if a required protection source cannot
be read, `--apply` refuses rather than under-protecting. See
[Store Lifecycle](agent-attachments.md#store-lifecycle).

`sase artifact list` inventories only the persistent artifact-file index; it is not a
catalog of every reference kind and it does not browse the agents-sidecar prompt
archive. Use `sase agent prompts list/show/validate` for archived prompts and their
published `ARTIFACTS` links. Use sase's TUI grouped `@` completion to browse prompt
references, or its contextual **Copy as…** palette to copy a reference or pre-fill a new
agent prompt from the selected entry. See [Artifact References](artifact-references.md)
for the handoff workflow and
[prompt preprocessing](../contribute/llm-invocation.md#prompt-preprocessing-pipeline)
for launch-time resolution.

Operational commands are intentionally narrow. Helper bridges expose fixed JSON
operations for editor and mobile clients; they are not general shell or filesystem APIs.

`sase --full-help` also lists durable-operation entrypoints that sase's TUI submits as
durable procs rather than commands meant for everyday typing: Patch lifecycle actions
(`sase patch accept`, `archive`, `mail`, `rebase`, `restore`, `revert`, `rewind`,
`reword`, `status`, `submit`, `sync`, and `tag`), `sase agent revert`,
`sase agent persist-cleanup`, `sase agent persist-directive`, `sase bead apply-status`,
and `sase notify apply-state` / `apply-state-many`. They take `-Q/--request-path` and
`-R/--result-path` for the private request and typed result sidecars, defaulting to
`$SASE_PROC_REQUEST_PATH` and `$SASE_PROC_RESULT_PATH`. Several everyday commands, such
as `sase run`, `sase agent drain`, `sase gate act`, `sase launch approve`, and
`sase plugin install`, accept the same two options so the TUI can run them as procs.

### Doctor Support Reports

`sase doctor` is the first command to run when SASE behaves unexpectedly. It is
read-only by default (apart from the agent-hold reconciliation described below): it does
not launch agents, call LLM APIs, repair state, run tests, or scan full artifact
history. The human output is grouped by subsystem and puts next-step commands beside
warnings and errors.

Common forms:

```bash
sase doctor                 # compact human report
sase doctor -v              # include every check plus bounded details
sase doctor -j              # stable JSON report for scripts or support bundles
sase doctor -D              # add slower read-only deep checks
sase doctor -C runtime      # run one group
sase doctor -C llm.default  # run one check
sase doctor -C project.junk_directories -C workspace.missing_checkouts
sase doctor -F              # preview and confirm ProjectSpec duplicate-block repair
sase doctor -R              # preview and confirm restore of stranded primary sidecar link-index deletions
```

Exit codes are designed for support-first use. `OK`, `WARN`, and all-skipped reports
exit `0`; `ERROR` exits `1`. Use `sase doctor -s` / `--strict` when automation should
treat warnings as failures.

The JSON report uses `schema_version: 1` and stable top-level fields such as `status`,
`counts`, `selected_checks`, and `checks`. Individual check `data` payloads stay bounded
and may gain additional keys over time, so scripts should key off check ids and statuses
rather than assuming every nested field is permanent.

The `completion` group is advisory and never fails a report: `completion.install` reads
the [shell-completion](integrations/completion.md) install stamps, and the deep-only
`completion.registration` spawns a real shell to confirm the script is actually
registered (`sase doctor -D -C completion.registration`). Selecting a deep check without
`-D` is rejected rather than silently skipped.

`plugins.commands` loads mounted command adapters and reports command and claim
problems. A load failure is `ERROR` on this check. A name collision is `ERROR` and names
every owner; the suggested next step is an uninstall command for the first owner
alphabetically; doctor does not run it. A shadowed or invalid name is `WARN`. The
deep-only `plugins.commands-parsers` check
(`sase doctor -D -C plugins.commands-parsers`) also builds each mounted command's
parser, and a parser failure is `ERROR` too. A load or parser failure's suggested next
step currently uses `sase plugin update <command-name>`. The command name may differ
from the plugin name; use the owning distribution in the diagnostic to identify the
plugin before updating it. See
[Where a command shows up](integrations/plugins-commands.md#where-a-command-shows-up).

`project.junk_directories` reports directories under `~/.sase/projects/` that have no
canonical ProjectSpec and gives a manual-review cleanup hint.
`project.duplicate_patch_blocks` reports duplicate raw Patch blocks in active and
archive ProjectSpec files. `sase doctor -F` / `--fix-duplicate-blocks` previews that
repair and, after confirmation or `-y` / `--yes`, keeps the newest block per Patch name
without changing the default read-only doctor behavior.
`project.primary_sidecar_link_dirt` flags uncommitted `links/` dirt in sidecar clones
nested under a project's primary checkout, which blocks pull-based sidecar auto-sync.
`sase doctor -R` / `--fix-primary-sidecar-links` restores stranded canonical link-index
deletions (`git restore`) as a user-origin action; it does not commit them, because
durable deletions must land via the machine write lane and reach the primary through
auto-sync. `workspace.missing_checkouts` scans enabled and disabled projects through the
shared inventory, lists registered checkout paths missing from disk, and suggests a
per-project `sase workspace repair -n` preview. `workspace.occupancy_conflicts` reads
every project's RUNNING field and each checkout's occupant record, then reports
duplicate workspace-number claims, a live claim whose occupant names a different live
pid, and occupant records with no matching claim. Conflicts include the last
workspace-claim ledger mutation and caller tag when one exists; the check never
auto-repairs. `config.macro_directives` locates macro and workflow definition files that
still use retired directive syntax, such as a `%wait(priority=...)` that has moved to
`%queue`. `agent_holds.stale` warns about
[agent holds](agents/agent-holds.md#sase-agent-hold) whose armer has died or whose TTL
has passed; like `sase agent hold list`, it reconciles the hold store as it reads it, so
the stale records it reports are also pruned. Apart from that reconciliation, default
doctor checks do not mutate state.

When asking for help, attach `sase doctor -v` for a readable report or `sase doctor -j`
for a machine-readable report.
