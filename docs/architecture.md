# Architecture

SASE is a Python orchestration layer for agentic software engineering, backed by a
required Rust core for selected deterministic data operations. The system keeps work
state outside any one chat transcript so agents can be launched, tracked, resumed,
reviewed, retried, and handed off through stable project artifacts.

![SASE component communication diagram](images/sase-component-communication.png)

## System Boundary

| Area         | Responsibility                                                                                                                                    | Main References                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| CLI          | Top-level `sase` commands, argument parsing, dispatch, and JSON helper bridges.                                                                   | [CLI reference](cli.md)                                            |
| sase's TUI   | Interactive TUI for Patches, agents, notifications, artifacts, and service status.                                                                | [sase's TUI](ace.md)                                               |
| Service host | Beta per-machine supervisor for configured daemon procs and transient oneshots; it can own the scheduler and mobile gateway.                      | [CLI reference](cli.md#sase-service)                               |
| Axe          | Background orchestrator for scheduled hooks, mentors, workflow checks, comments, cleanup, and digests.                                            | [Axe](axe.md)                                                      |
| XPrompt      | Prompt templates, reference expansion, directives, typed inputs, and reusable workflows.                                                          | [XPrompts](xprompt.md)                                             |
| Workflows    | YAML multi-step execution with agent, bash, python, parallel, loop, and human checkpoint steps.                                                   | [Workflow spec](workflow_spec.md)                                  |
| Gates        | Durable, command-backed user decisions and processless family-shell handoffs.                                                                     | [Notifications](notifications.md#command-backed-interaction-gates) |
| Patches      | PR-sized review records with lifecycle state, stitches, hooks, comments, mentors, and timestamps.                                                 | [Patches](change_spec.md)                                          |
| Memory       | Always-loaded and on-demand context, explicit flat-note xprompt inclusion, audited reads, and sase's TUI-backed note/strand changes.              | [Memory](memory.md)                                                |
| SDD          | Durable prompt, tale, epic, and research artifacts.                                                                                               | [SDD](sdd.md)                                                      |
| Beads        | Git-portable issue/dependency tracking and executable epic launch plans.                                                                          | [Beads](beads.md)                                                  |
| Providers    | Pluggable LLM, VCS, workspace, config, and xprompt boundaries.                                                                                    | [Plugins](plugins.md)                                              |
| Rust core    | Required `sase_core_rs` extension for ported parsing, query, notification, agent scan, launch and admission, retention, and bead data operations. | [Rust backend](rust_backend.md)                                    |
| Integrations | Public helpers and fixed bridge APIs for editors, mobile gateway, and external packages.                                                          | [Integrations](integrations.md)                                    |

The Python host owns user-facing orchestration, plugin calls, subprocess handling,
filesystem context, TUI rendering, and workflow side effects. Rust owns reusable
deterministic backend operations that need speed, stable wire contracts, or
cross-frontend consistency.

## Agent Launch Flow

Most agent work enters through `sase run`, sase's TUI, validated axe job proposals, bead
epic execution, or mobile/editor helper bridges. The launch path follows the same shape
across those entry points:

1. Parse prompt text, directives, and optional multi-prompt separators, then
   canonicalize ProjectSpec aliases in launch-bound VCS refs. For example, `#gh:bob`
   becomes the stable directory-key ref `#gh:bob-cli` before history or artifact
   snapshots are written.
2. Expand the swarm, repeat, or alternative directives needed to determine the launch
   slots and validate their names.
3. Resolve each slot's workspace reference, such as `#git:<project>` or a
   plugin-provided form. An explicit ref to a disabled known project re-enables that
   project before the claim. Direct claims that bypass this launch preparation remain
   blocked by the workspace claim guard. Providers may return a `canonical_ref` for a
   raw locator such as a first-use owner/repo ref; launch metadata, history, and prompt
   MRU entries then use that stable ref.
4. Prepare fixed or deferred workspace metadata. For a normal launch, claim the final
   numbered workspace atomically immediately before spawning the process.
5. In the detached runner, wait for `%wait` dependencies and time floors, then pass
   runner admission: no active [agent hold](cli.md#sase-agent-hold) may match the run,
   and its queue weight must fit the global `max_running_agents` budget or its own
   `%queue` capacity budget. A deferred-workspace launch claims its numbered workspace
   only after admission.
6. Continue xprompt or workflow processing and invoke the selected LLM provider or
   workflow executor.
7. Stream subprocess output, write chat history, and persist launch metadata.
8. Record agent artifacts such as prompts, diffs, generated Markdown PDFs, images,
   plans, and explicit files.
9. Emit notifications and update sase's TUI-visible status.
10. Hand review, revert, restore, or commit work to the VCS and workspace provider
    layers when requested.

When the `typed_launch_units` beta flag is enabled, user-initiated sase's TUI and
`sase run` submissions, approved LaunchApproval requests, and typed AXE job proposal
batches share one typed admission path. Recursive xprompt expansion and fan-out still
happen first, keyed `{@<id>}` agent-name markers resolve once across that expanded
batch, then Rust builds an immutable `LaunchPlan` of tagged Agent or Proc units with
stable logical IDs, the complete `%id`/`%clan` identity binding, waits, optional `%if`
predicates, and code digests. Dispatch reconstructs grouping directives from that
binding instead of a positional name alone. Direct user submissions persist that plan in
a durable bundle and dispatch immediately; agent-initiated launches freeze the same
digest behind LaunchApproval; AXE job batches containing an active `%if`/`%proc`
directive dispatch through the same durable bundle under the internal `axe_chop` source
surface, with the originating job run owning the bundle across process restarts (see
[Structured Results and Launch Proposals](axe.md#structured-results-and-launch-proposals)).
Within an AXE job clan, dispatch — not planning — owns the declarer decision: the first
surviving (eligible, dispatched) member of an undeclared clan claims it durably, so a
`%if`-skipped statically planned declarer never leaves later members joining a clan
nobody declared. AXE job proposal `wait_on` edges also have one job-specific dispatch
effect: admission consumes the logical edge for launch ordering, then an admitted Agent
unit receives a restored named-agent `%wait` for the nearest earlier unit that actually
launched. Generic typed logical waits outside AXE remain coordinator-owned and are not
re-emitted into rebuilt agent prompts. A detached launch-admission coordinator —
infrastructure owned by the launch-request bundle, not an Agents-tab row — journals each
unit through reserved, waiting, checking, eligible, and dispatching states to a terminal
launched, skipped, condition-error, launch-error, or cancelled state. Waits resolve
before conditions. For a selected managed project, `%if` briefly claims and prepares a
numbered operational workspace, runs the predicate from that checkout, and releases the
claim before dispatch. Home/unmanaged conditions have no claimable workspace and keep
using their explicit source cwd. A false `%if` is still terminal without allocating a
runner, agent identity, proc identity, or model request. Eligible Agent units still use
the established agent launch path. An eligible `%proc` unit stays undispatched while an
active agent hold matches it, and one that authors `%queue` fields must also fit the
shared runner-capacity budget; it then dispatches as a native `proc-shell` record with
origin `xprompt-proc`. Restarts replay the journal instead of re-running settled
predicates or duplicating reserved identities.

Detached launches appear in the agent registry and sase's TUI Agents tab. Multi-prompt
launches create a sequence of detached agents. Stand-alone `%proc` shells appear in the
same Agents tab as top-level `▣` rows backed only by the proc store, counted separately
from agents. Workflow launches persist step state so sase's TUI and axe can inspect
progress and recover meaningful output.

Agent holds are durable reverse waits. [`sase agent hold`](cli.md#sase-agent-hold) arms
a hold in `~/.sase/agent_holds.json` that selects agents or proc shells by name, tribe,
or hood; it can freeze the WAITING/QUEUED agents already in scope and fence launches
submitted later. Runner admission and undispatched `%proc` dispatch both consult active
holds. A hold ends when it is released, when its armer settles or exits, or when its TTL
expires, and a broken hold store fails open rather than stranding a waiter. The
[`%hold` directive](xprompt.md#hold-directive) describes the same selectors in prompt
text. Typed launches pre-arm the declared hold before admission can dispatch the unit,
then rebind it to the running agent or proc; terminal units that never dispatch release
their pre-armed holds.

The beta service host is a machine-level supervisor gated by `service_host`. Its
`service.procs` catalog comes from builtin, plugin, user, and machine-overlay config;
project-local entries are intentionally ignored. The shipped `scheduler` proc runs AXE
routines and jobs, while the shipped `gateway` proc is disabled by default. Native user
units (`systemd --user` on Linux and LaunchAgents on macOS) can keep the host alive
across TUI and login-session lifetimes. The legacy `sase axe` commands remain the direct
scheduler control surface when the flag is off.

On Linux, when detached work starts inside a SASE-owned systemd unit or scope (such as
`sase.service` or an axe scope), agent runners, launch-admission coordinators, proc
supervisors, and monitor supervisors move into their own transient user scopes, so
restarting that service does not kill them. `SASE_DETACH_SCOPE_DISABLE=1` turns this
off.

## Agent, Monitor, and Gate Shells

A SASE agent is either one standalone agent shell or a sequential family of shells.
Agent shells are provider/LLM turns. Monitor shells are supervised commands attached to
that family. Gate shells are non-LLM members that own a durable user decision; while a
gate is pending, it has no provider or command process. All three appear in one family
timeline. Once their evidence is readable, later family forks can include the agent
transcript, monitor log, or gate decision record.

Questions, plan review, agent-side workflow HITL, agent-initiated launch approval, and
beta [sudo requests](sudo.md) use gate shells. At the handoff boundary SASE persists the
verified gate bundle, names the shell, transfers or releases the workspace claim
according to policy, releases the runner slot, and ends the provider turn. A client
later selects a branch; SASE first writes a write-once decision receipt, so the choice
is durable and a conflicting answer fails before any command runs. It then runs the
branch's hashed commands (normally in a supervised detached proc), records their output,
settles the shell, and optionally launches the next agent-shell family member. The
answered branch can inherit a default follow-up; timeout, stopped, failed, and lost
outcomes require explicit follow-up policy. This makes a human pause durable without
holding a provider process or runner slot open.

## State Model

SASE avoids making a live chat session the source of truth. The durable state lives in
files and stores that can be inspected by users, agents, and automation:

The project-adjacent taxonomy has three non-overlapping roles:

- A **project** is a named unit of work registered by a valid first-use VCS xprompt
  argument and backed by `~/.sase/projects/<name>/<name>.sase`. Its user-facing
  lifecycle is exactly enabled or disabled; missing state means enabled. An internal
  `sibling` backing marker supports linked-repo claims but is not a project state.
- A **repo** is a primary project repo, an SDD sidecar repo, or a configured linked
  repo. One project can therefore own several repos.
- A **workspace** is a numbered clone of a project's primary repo, tracked by that
  project's workspace registry and claimed by one SASE agent until completion.
  Linked/sidecar checkouts materialized within it remain repos, not workspaces. By
  default a managed Git workspace borrows the primary checkout's object database through
  Git alternates, so moving or deleting the primary checkout calls for
  [`sase workspace repair`](workspace.md#sase-workspace-cli).

| State             | Location / Owner                                                                 | Use                                                                                                                                                                                            |
| ----------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ProjectSpecs      | `<project>/<project>.sase` under `~/.sase/projects/`                             | Enabled/disabled lifecycle, primary repo, aliases, claims, and embedded Patches.                                                                                                               |
| Agent metadata    | Agent artifact directories under `~/.sase/`                                      | Running/completed status, prompt files, output, diffs, workflow state, and attachments.                                                                                                        |
| Agent archives    | `~/.sase/dismissed_bundles/` and `~/.sase/dismissed_agent_groups/`               | Dismissed-agent recovery bundles and named groups for later sase's TUI revival.                                                                                                                |
| SDD artifacts     | Provider-resolved `sdd/`, `.sase/sdd/`, or split sidecar roots                   | Plans, executable epics, research notes, and links to canonical agents-sidecar prompts; resolve with `sase repo path plans` or `research`.                                                     |
| Beads             | The resolved SDD beads directory                                                 | Issue graph, JSONL export, SQLite query cache, and epic execution metadata; current split stores use the root of a dedicated `--beads` sidecar, while schema-2 stores retain `--plans/beads/`. |
| Project content   | `sase/sase.yml`, `sase/xprompts/`, `sase/skills/`, `sase/memory/`, `sase/repos/` | Source-controlled project settings/context plus ignored workspace-scoped repository checkouts.                                                                                                 |
| Home content      | `~/sase/xprompts/`, `~/sase/skills/`, `~/sase/memory/`                           | User-wide reusable prompts and agent memory.                                                                                                                                                   |
| Memory audit      | `~/.sase/projects/<project>/memory_reads.jsonl`                                  | Attributable flat-note, strand, and batched reference-memory reads.                                                                                                                            |
| Configuration     | `~/.config/sase/sase.yml`, overlays, project `sase/sase.yml`                     | Provider selection, axe jobs, mentors, xprompts, telemetry, mobile gateway, and defaults.                                                                                                      |
| Notifications     | Notification store facade backed by Rust operations                              | User-visible actions, unread state, agent completion, errors, and mobile events.                                                                                                               |
| Interaction gates | `~/.sase/interaction_requests/<kind>/<request-id>/`                              | Immutable request bundles, owned commands and resources, write-once decision receipts, and terminal responses for user decisions.                                                              |
| Procs             | `~/.sase/procs/`                                                                 | Rust-owned proc rows, logs, and runtime directories for `%proc` shells, gate answers, and other supervised background commands.                                                                |
| Agent holds       | `~/.sase/agent_holds.json`                                                       | Durable reverse-wait holds consulted by runner admission and undispatched `%proc` dispatch.                                                                                                    |
| Service state     | `~/.sase/service/`                                                               | Service-host lock, status, machine enablement/stop overrides, captured environment, and bounded host/proc logs.                                                                                |
| Managed temp      | `$SASE_TMPDIR`, else `~/.sase/tmp/`                                              | Per-launch agent scratch, Cargo targets, handoff files, and workflow scratch, bounded by the owner reaper and runner-exit cleanup.                                                             |
| Workspace claims  | Running-field state and provider metadata                                        | Reservation and release of numbered workspaces for parallel agents.                                                                                                                            |
| Workspace stores  | Per-project `registry.json` under the configured workspace root                  | Checkout paths, role/materialization, pins, generation, created/last-used times, and cleanup eligibility.                                                                                      |

`~/.sase` is the default SASE state root. Set `SASE_HOME` to move that root for isolated
tests, alternate profiles, or containerized runs.

Every SASE-owned disk root has an owner that decides its retention. `sase disk list`
attributes usage to those owners, and `sase disk reap` previews their cleanup passes or,
with `--apply`, delegates cleanup to them: the managed-temp reaper, proc runtime sweeps,
agent artifact-run retention, and workspace Git object compaction. Unowned Cargo-shaped
strays are reported but never deleted. The hourly axe `disk_pressure` job runs the
owner-safe passes early when free space runs low. See
[`sase disk`](configuration.md#sase-disk) and
[axe housekeeping](axe.md#housekeeping-1-hour-interval).

The canonical project/home namespace and legacy read boundary are documented in
[Canonical SASE Content Layout](content_layout.md). Global config, `.sase` runtime
state, package resources, and plugin resources deliberately remain outside that
namespace.

This model lets sase's TUI, CLI commands, axe, and future frontends read the same
engineering state without depending on one terminal session.

## Provider Boundaries

Provider abstractions keep SASE above any single agent runtime, version-control host, or
workspace strategy:

| Provider Layer     | What It Owns                                                                                                     | Details                         |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| LLM provider       | Agent CLI selection, concrete model mapping, subprocess invocation, retry defaults, usage metadata.              | [LLM providers](llms.md)        |
| VCS provider       | Diff, checkout, commit, amend, proposal/PR dispatch, reword, submit, sync, revert, restore, and review metadata. | [VCS providers](vcs.md)         |
| Workspace provider | Workspace reference resolution, workspace directory allocation, submit/mail preparation, workflow metadata.      | [Workspaces](workspace.md)      |
| Resource plugins   | Extra xprompt/workflow files and default configuration.                                                          | [Plugins](plugins.md)           |
| Integration APIs   | Public Python helpers and fixed JSON bridge contracts for sidecar tools.                                         | [Integrations](integrations.md) |

Core SASE ships built-in providers for common local use: bundled LLM provider entry
points, plain-git VCS support, and bare-git workspaces. Optional packages can add hosted
VCS workflows, notification delivery, editor integrations, or extra prompt resources.

## Rust Core Boundary

The required `sase_core_rs` extension is the shared backend boundary for deterministic
logic that benefits from a stable wire contract or from being reused by non-Python
frontends. Current Rust-backed areas include:

- Patch parsing and batch query operations.
- Project lifecycle parsing, canonical enabled/disabled normalization, the true-project
  predicate, VCS-kind derivation, update planning, and lifecycle-filtered project
  listing.
- Status transition planning.
- Git command output parsing.
- Notification JSONL reads and mutations.
- Agent artifact scanning and persistent indexing.
- Agent launch preparation, timestamp allocation, fan-out planning, low-level detached
  spawn, and workspace-claim planning.
- Bead read, mutation, JSONL, SQLite, single-store ID allocation, and deterministic
  work-plan operations.
- Agent hold validation, runner-capacity snapshots, and gate decision acceptance and
  lifecycle policy.
- Managed-temp reaping, disk inventory and pressure classification, and agent
  artifact-run and proc runtime retention.
- Git object-sharing plans for managed workspaces and failure retryability
  classification for `gh` and network Git calls.

The frontend-neutral `repo_inventory.py` and `workspace_provider/inventory.py` adapters
currently compose those Rust-owned project records with Python-owned linked-repo
configuration, SDD records, workspace registries, and claim parsing. CLI and TUI
surfaces consume the same adapters. They are explicit migration seams for a future Rust
core API, not presentation logic.

The Python host still owns side effects that require app context: plugin dispatch,
VCS/workspace calls, process signalling, file locks, TUI rendering, user confirmation,
xprompt lookup, and workflow orchestration. See [Rust backend](rust_backend.md) for the
complete operation list and facade map.

## Read Next

| Need                                     | Page                                                                                                 |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Command discovery                        | [CLI reference](cli.md)                                                                              |
| Contributor setup and source orientation | [Development](development.md)                                                                        |
| Runtime operations                       | [sase's TUI](ace.md), [Axe](axe.md), [notifications](notifications.md)                               |
| Durable work records                     | [Patches](change_spec.md), [memory](memory.md), [SDD](sdd.md), [beads](beads.md)                     |
| Prompt and workflow execution            | [XPrompts](xprompt.md), [workflow spec](workflow_spec.md)                                            |
| Extension boundaries                     | [Plugins](plugins.md), [LLM providers](llms.md), [VCS providers](vcs.md), [workspaces](workspace.md) |
| Backend boundary                         | [Rust backend](rust_backend.md)                                                                      |
