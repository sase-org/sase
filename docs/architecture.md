# Architecture

SASE is a Python orchestration layer for agentic software engineering, backed by a required Rust core for selected
deterministic data operations. The system keeps work state outside any one chat transcript so agents can be launched,
tracked, resumed, reviewed, retried, and handed off through stable project artifacts.

![SASE component communication diagram](images/sase-component-communication.png)

## System Boundary

| Area         | Responsibility                                                                                                                | Main References                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| CLI          | Top-level `sase` commands, argument parsing, dispatch, and JSON helper bridges.                                               | [CLI reference](cli.md)           |
| ACE          | Interactive TUI for ChangeSpecs, agents, notifications, artifacts, and axe status.                                            | [ACE TUI](ace.md)                 |
| Axe          | Background orchestrator for scheduled hooks, mentors, workflow checks, comments, cleanup, and digests.                        | [Axe](axe.md)                     |
| XPrompt      | Prompt templates, reference expansion, directives, typed inputs, and reusable workflows.                                      | [XPrompts](xprompt.md)            |
| Workflows    | YAML multi-step execution with agent, bash, python, parallel, loop, and human checkpoint steps.                               | [Workflow spec](workflow_spec.md) |
| ChangeSpecs  | PR-sized review records with lifecycle state, commits, hooks, comments, mentors, and timestamps.                              | [ChangeSpecs](change_spec.md)     |
| Memory       | Instruction memory, audited long-term reads, and reviewed write proposals.                                                    | [Memory](memory.md)               |
| SDD          | Durable prompt, tale, epic, and research artifacts.                                                                           | [SDD](sdd.md)                     |
| Beads        | Git-portable issue/dependency tracking and executable epic launch plans.                                                      | [Beads](beads.md)                 |
| Providers    | Pluggable LLM, VCS, workspace, config, and xprompt boundaries.                                                                | [Plugins](plugins.md)             |
| Rust core    | Required `sase_core_rs` extension for ported parsing, query, notification, agent scan, launch prep, and bead data operations. | [Rust backend](rust_backend.md)   |
| Integrations | Public helpers and fixed bridge APIs for editors, mobile gateway, and external packages.                                      | [Integrations](integrations.md)   |

The Python host owns user-facing orchestration, plugin calls, subprocess handling, filesystem context, TUI rendering,
and workflow side effects. Rust owns reusable deterministic backend operations that need speed, stable wire contracts,
or cross-frontend consistency.

## Agent Launch Flow

Most agent work enters through `sase run`, ACE, axe agent chops, bead epic execution, or mobile/editor helper bridges.
The launch path follows the same shape across those entry points:

1. Parse prompt text, directives, and optional multi-prompt separators.
2. Canonicalize ProjectSpec aliases in launch-bound VCS refs, so aliases such as `#gh:bob` become stable project
   directory keys such as `#gh:bob-cli` before history or artifact snapshots are written.
3. Resolve workspace references such as `#git:<project>` or plugin-provided forms, rejecting disabled known projects
   before new work is claimed. Providers may return an optional `canonical_ref` for raw locators such as first-use
   owner/repo refs; when they do, launch metadata, history, and prompt MRU entries use that stable ref instead of the
   raw locator.
4. Allocate or prepare the target workspace through the workspace provider layer.
5. Expand xprompt references and standalone workflow references.
6. Invoke the selected LLM provider or workflow executor.
7. Stream subprocess output, write chat history, and persist launch metadata.
8. Record agent artifacts such as prompts, diffs, generated Markdown PDFs, images, plans, and explicit files.
9. Emit notifications and update ACE-visible status.
10. Hand review, revert, restore, or commit work to the VCS and workspace provider layers when requested.

Detached launches appear in the agent registry and ACE Agents tab. Multi-prompt launches create a sequence of detached
agents. Workflow launches persist step state so ACE and axe can inspect progress and recover meaningful output.

## State Model

SASE avoids making a live chat session the source of truth. The durable state lives in files and stores that can be
inspected by users, agents, and automation:

The project-adjacent taxonomy has three non-overlapping roles:

- A **project** is a named unit of work registered by a valid first-use VCS xprompt argument and backed by
  `~/.sase/projects/<name>/<name>.sase`. Its user-facing lifecycle is exactly enabled or disabled; missing state means
  enabled. An internal `sibling` backing marker supports linked-repo claims but is not a project state.
- A **repo** is a primary project repo, an SDD sidecar repo, or a configured linked repo. One project can therefore own
  several repos.
- A **workspace** is a numbered clone of a project's primary repo, tracked by that project's workspace registry and
  claimed by one SASE agent until completion. Linked/sidecar checkouts materialized within it remain repos, not
  workspaces.

| State            | Location / Owner                                                   | Use                                                                                                            |
| ---------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| ProjectSpecs     | `<project>/<project>.sase` under `~/.sase/projects/`               | Enabled/disabled lifecycle, primary repo, aliases, claims, and embedded ChangeSpecs.                           |
| Agent metadata   | Agent artifact directories under `~/.sase/`                        | Running/completed status, prompt snapshots, output, diffs, workflow state, and attachments.                    |
| Agent archives   | `~/.sase/dismissed_bundles/` and `~/.sase/dismissed_agent_groups/` | Dismissed-agent recovery bundles and named groups for later ACE revival.                                       |
| SDD artifacts    | Provider-resolved `sdd/`, `.sase/sdd/`, or split sidecar roots     | Prompt snapshots, plans, executable epics, and research notes; resolve with `sase sdd path <kind>`.            |
| Beads            | The resolved SDD beads directory                                   | Issue graph, JSONL export, SQLite query cache, and epic execution metadata; split stores use `--plans/beads/`. |
| Memory context   | `memory/`, `~/.sase/projects/<project>/`                           | Agent instructions, audited reads, and write proposals.                                                        |
| Configuration    | `~/.config/sase/sase.yml`, overlays, optional project-local config | Provider selection, axe jobs, mentors, xprompts, telemetry, mobile gateway, and defaults.                      |
| Notifications    | Notification store facade backed by Rust operations                | User-visible actions, unread state, agent completion, errors, and mobile events.                               |
| Workspace claims | Running-field state and provider metadata                          | Reservation and release of numbered workspaces for parallel agents.                                            |
| Workspace stores | Per-project `registry.json` under the configured workspace root    | Checkout paths, role/materialization, pins, generation, created/last-used times, and cleanup eligibility.      |

`~/.sase` is the default SASE state root. Set `SASE_HOME` to move that root for isolated tests, alternate profiles, or
containerized runs.

This model lets ACE, CLI commands, axe, and future frontends read the same engineering state without depending on one
terminal session.

## Provider Boundaries

Provider abstractions keep SASE above any single agent runtime, version-control host, or workspace strategy:

| Provider Layer     | What It Owns                                                                                                     | Details                         |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| LLM provider       | Agent CLI selection, concrete model mapping, subprocess invocation, retry defaults, usage metadata.              | [LLM providers](llms.md)        |
| VCS provider       | Diff, checkout, commit, amend, proposal/PR dispatch, reword, submit, sync, revert, restore, and review metadata. | [VCS providers](vcs.md)         |
| Workspace provider | Workspace reference resolution, workspace directory allocation, submit/mail preparation, workflow metadata.      | [Workspaces](workspace.md)      |
| Resource plugins   | Extra xprompt/workflow files and default configuration.                                                          | [Plugins](plugins.md)           |
| Integration APIs   | Public Python helpers and fixed JSON bridge contracts for sidecar tools.                                         | [Integrations](integrations.md) |

Core SASE ships built-in providers for common local use: bundled LLM provider entry points, plain-git VCS support, and
bare-git workspaces. Optional packages can add hosted VCS workflows, notification delivery, editor integrations, or
extra prompt resources.

## Rust Core Boundary

The required `sase_core_rs` extension is the shared backend boundary for deterministic logic that benefits from a stable
wire contract or from being reused by non-Python frontends. Current Rust-backed areas include:

- ChangeSpec parsing and batch query operations.
- Project lifecycle parsing, canonical enabled/disabled normalization, the true-project predicate, VCS-kind derivation,
  update planning, and lifecycle-filtered project listing.
- Status transition planning.
- Git command output parsing.
- Notification JSONL reads and mutations.
- Agent artifact scanning and persistent indexing.
- Agent launch preparation, timestamp allocation, fan-out planning, low-level detached spawn, and workspace-claim
  planning.
- Bead read, mutation, JSONL, SQLite, single-store ID allocation, and deterministic work-plan operations.

The frontend-neutral `repo_inventory.py` and `workspace_provider/inventory.py` adapters currently compose those
Rust-owned project records with Python-owned linked-repo configuration, SDD records, workspace registries, and claim
parsing. CLI and TUI surfaces consume the same adapters. They are explicit migration seams for a future Rust core API,
not presentation logic.

The Python host still owns side effects that require app context: plugin dispatch, VCS/workspace calls, process
signalling, file locks, TUI rendering, user confirmation, xprompt lookup, and workflow orchestration. See
[Rust backend](rust_backend.md) for the complete operation list and facade map.

## Read Next

| Need                                     | Page                                                                                                 |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Command discovery                        | [CLI reference](cli.md)                                                                              |
| Contributor setup and source orientation | [Development](development.md)                                                                        |
| Runtime operations                       | [ACE](ace.md), [Axe](axe.md), [notifications](notifications.md)                                      |
| Durable work records                     | [ChangeSpecs](change_spec.md), [memory](memory.md), [SDD](sdd.md), [beads](beads.md)                 |
| Prompt and workflow execution            | [XPrompts](xprompt.md), [workflow spec](workflow_spec.md)                                            |
| Extension boundaries                     | [Plugins](plugins.md), [LLM providers](llms.md), [VCS providers](vcs.md), [workspaces](workspace.md) |
| Backend boundary                         | [Rust backend](rust_backend.md)                                                                      |
