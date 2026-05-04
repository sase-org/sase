# sase — Structured Agentic Software Engineering

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

## Overview

**sase** (pronounced "sassy") is a Python toolkit for AI-powered software engineering workflows. It combines an
interactive TUI, a scheduling daemon, a YAML workflow engine, and pluggable LLM/VCS abstractions into a cohesive system
for managing code changes at scale.

<img src="docs/images/sase_overview.jpg" alt="Visual overview of sase" width="800">

## Supported Coding Agents

sase is designed to work with the coding agents you already use:

| Agent                                                         | Status                     |
| ------------------------------------------------------------- | -------------------------- |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | **Supported**              |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli)     | **Supported**              |
| [Codex](https://github.com/openai/codex)                      | **Supported**              |
| Jetski (Google's successor to Gemini CLI)                     | **Via sase-google plugin** |

sase doesn't replace these agents — it **orchestrates** them. It provides the scheduling, tracking, and workflow
infrastructure that turns individual agent runs into a managed software engineering pipeline.

## Vision

Coding agents are powerful — but **using them in a real engineering workflow is still painful.**

Running a single agent on a single task works fine. The problems start when you try to do it repeatedly, across multiple
changes, with any kind of structure. sase exists to solve the coordination problems that show up at that point:

> **Scheduling** — Agent runs are hard to schedule, monitor, and resume reliably.
>
> **Prompt Logic** — Multi-step prompt pipelines get fragile fast when they're scattered across shell scripts and
> scratch files.
>
> **Tracking** — Work gets lost without a first-class unit for status, ownership, metadata, and review state.
>
> **Portability** — Teams need one system above the agent layer, not a separate workflow for every provider.
>
> **Supervision** — Automation still needs human checkpoints, VCS integration, and reproducible execution.

---

<table>
<tr><th>Before sase</th><th>After sase</th></tr>
<tr>
<td>

Prompts live in shell history and scratch files. Each agent run is a one-off terminal session. Status is tracked in your
head (or not at all). Switching agents means rewriting your wrapper scripts. There's no audit trail and no way to hand
work off to a teammate.

</td>
<td>

**ChangeSpecs** give each unit of work a tracked lifecycle. **Workflows** define reproducible multi-step pipelines.
**ACE** provides the operational layer for navigating and supervising changes. **AXE** handles background scheduling.
The whole system is agent-agnostic — swap providers without rewriting your workflow definitions.

</td>
</tr>
</table>

The goal isn't to make agents smarter. It's to make **agent-driven software engineering dependable.**

## Key Features

- **ACE** — Interactive TUI for navigating, filtering, and managing ChangeSpecs
- **AXE** — Lumberjack-based daemon for continuous automation via configurable chop scripts
- **XPrompt** — Typed prompt templates with reference expansion, YAML front matter, semantic tags, and CLI tools for
  expansion, listing, workflow visualization, and DAG graphing
- **Workflows** — YAML-defined multi-step pipelines with agent, bash, and python steps, control flow, parallel
  execution, and human-in-the-loop support
- **SDD** — Spec-driven development artifacts that persist expanded prompts plus approved tales, executable epics, and
  higher-level legends under `sdd/` or `.sase/sdd/`
- **ChangeSpec** — Tracked unit of work with a full status lifecycle
- **Beads** — Git-native issue tracking for SDD epics, phase dependencies, and multi-agent execution plans
- **Mentors** — Automated AI code review agents with configurable profiles, structured JSON output, and TUI-based review
  and apply workflow
- **Telemetry** — Prometheus-based observability with 33 metrics across 7 subsystems, live TUI dashboard, health checks,
  and a bundled Docker Compose monitoring stack (Prometheus + Grafana)
- **Agent Artifacts** — Completion notifications can include chat, diff, error logs, generated Markdown PDFs, and
  generated image files touched by agents so downstream notification plugins can deliver the full result
- **LLM Providers** — Pluggable AI abstraction (Claude, Codex, Gemini bundled; Jetski via sase-google plugin) with
  pre/post-processing and token usage tracking
- **VCS Providers** — Pluggy-based version control abstraction (git bundled; GitHub and Mercurial via plugin packages)
- **Query Language** — Boolean expression language for filtering and searching ChangeSpecs

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                        sase CLI                        │
├─────────────┬────────────┬────────────┬────────────────┤
│  ace        │  axe       │  run       │    commit      │
│  (TUI)      │  (daemon)  │ (workflows)│  (VCS ops)     │
├─────────────┴────────────┴────────────┴────────────────┤
│                      Core Engine                       │
│    ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│    │ ChangeSpec │  │  XPrompt   │  │  Workflows │      │
│    │  Tracking  │  │  Templates │  │   (YAML)   │      │
│    └────────────┘  └────────────┘  └────────────┘      │
├───────────────────┬─────────────────┬──────────────────┤
│   LLM Provider    │  VCS Provider   │ Workspace Prov.  │
│ (pluggy plugins;  │ (pluggy plugins)│ (pluggy plugins) │
│  Claude, Codex,   │                 │                  │
│  Gemini bundled)  │                 │                  │
├───────────────────┴─────────────────┴──────────────────┤
│                    Plugin Packages                     │
│  sase-github · sase-google · sase-telegram · sase-nvim │
└────────────────────────────────────────────────────────┘
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended for dependency management)
- [just](https://github.com/casey/just) (task runner)

## Quick Start

```bash
# Create and activate a virtual environment
uv venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
just install

# Run the CLI
sase
```

## CLI Commands

| Command                        | Description                                                                                                    |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `sase ace`                     | Interactive TUI for navigating and managing ChangeSpecs                                                        |
| `sase agents status`           | List running agents across all projects (pretty table or JSON)                                                 |
| `sase agents show`             | Render a full detail panel for one running agent                                                               |
| `sase agents kill`             | SIGTERM a running agent by name                                                                                |
| `sase agents tag`              | Manage the user-defined tag on an agent (`set` / `unset` / `list`)                                             |
| `sase axe chop`                | List or run individual chop scripts                                                                            |
| `sase axe lumberjack`          | List, run, or check status of lumberjacks                                                                      |
| `sase axe maintenance`         | Enter, exit, or inspect maintenance mode, which pauses lumberjack ticks                                        |
| `sase axe start`               | Start the lumberjack-based daemon (orchestrator mode)                                                          |
| `sase axe stop`                | Stop the running axe orchestrator                                                                              |
| `sase bead blocked`            | Show blocked issues                                                                                            |
| `sase bead close`              | Close one or more issues (with optional reason)                                                                |
| `sase bead create`             | Create a new issue (plan or phase)                                                                             |
| `sase bead dep add`            | Add a dependency between issues                                                                                |
| `sase bead doctor`             | Run health checks on the bead database                                                                         |
| `sase bead init`               | Initialize `sdd/beads/` in the current directory                                                               |
| `sase bead list`               | List issues (with optional status/type filters)                                                                |
| `sase bead onboard`            | Show quick-start guide                                                                                         |
| `sase bead open`               | Reopen a closed issue                                                                                          |
| `sase bead ready`              | Show issues ready to work (unblocked, open)                                                                    |
| `sase bead rm`                 | Remove an issue and all its children                                                                           |
| `sase bead show`               | Show issue details                                                                                             |
| `sase bead stats`              | Show project statistics                                                                                        |
| `sase bead sync`               | Sync bead database with git                                                                                    |
| `sase bead update`             | Update an issue (title, description, status, assignee, tier, etc.)                                             |
| `sase bead work`               | Launch agents for epic-tier plans or legend-tier epic planning                                                 |
| `sase changespec current`      | Render the ChangeSpec for the current workspace (markdown / plain / JSON)                                      |
| `sase changespec sync-deltas`  | Recompute the DELTAS field for a ChangeSpec from the live VCS state                                            |
| `sase chats list`              | List recent agent chat transcripts (pretty table or JSON)                                                      |
| `sase chats show`              | Show a chat transcript by agent name, path, or basename                                                        |
| `sase comments`                | Preview mentor comments from JSON with syntax-highlighted code context                                         |
| `sase commit`                  | Create a commit with formatted CL description and metadata                                                     |
| `sase config layers`           | Show per-layer breakdown of the configuration merge chain                                                      |
| `sase config mentor-match`     | Trace mentor profile matching for a specific ChangeSpec                                                        |
| `sase config show`             | Dump the final merged configuration as YAML (supports `--key` filtering)                                       |
| `sase core health`             | Check that the required `sase_core_rs` Rust extension is loadable and working (`-j` for JSON)                  |
| `sase file list`               | JSON file/directory candidates rooted at `--path` (used by editor `<C-t>` completion)                          |
| `sase file-history delete`     | Remove one path from the file-reference history                                                                |
| `sase file-history list`       | JSON array of recently-referenced paths (most recent first; consumed by editor plugins)                        |
| `sase init-git`                | Initialize a new bare-repo-backed git project                                                                  |
| `sase init-skills`             | Generate and deploy agent skill files from xprompt source templates                                            |
| `sase logs`                    | Collect and package agent run logs for a date range                                                            |
| `sase notify`                  | Create a notification (reads JSON from stdin or uses flags)                                                    |
| `sase notify list`             | List recent notifications (pretty table or stable JSON)                                                        |
| `sase notify show`             | Show one notification by id (markdown or JSON)                                                                 |
| `sase path`                    | Print well-known sase paths (`xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `config-schema`) |
| `sase plan`                    | Submit a plan for approval (used by `/sase_plan` skill)                                                        |
| `sase questions`               | Ask the user questions (used by `/sase_questions` skill)                                                       |
| `sase restore`                 | Restore a reverted ChangeSpec by re-applying its diff                                                          |
| `sase revert`                  | Revert a ChangeSpec by pruning its CL and archiving its diff                                                   |
| `sase run`                     | Run a workflow, execute a query, resume a conversation, or list chat history                                   |
| `sase changespec search`       | Search and filter ChangeSpecs with query expressions                                                           |
| `sase sdd init`                | Create or refresh `sdd/README.md`, tier READMEs, and the directory map asset                                   |
| `sase sdd links`               | List SDD prompt/artifact frontmatter links                                                                     |
| `sase sdd list`                | List SDD markdown artifacts by kind (`prompts`, `tales`, `epics`, `legends`, or `all`)                         |
| `sase sdd repair-links`        | Infer and optionally write missing bidirectional SDD frontmatter links                                         |
| `sase sdd validate`            | Validate SDD frontmatter links, with JSON/quiet/strict modes                                                   |
| `sase telemetry status`        | Show telemetry configuration and service reachability                                                          |
| `sase telemetry list`          | Display the metric catalog (filterable by subsystem and type)                                                  |
| `sase telemetry snapshot`      | Fetch and display current metric values (rich, JSON, or Prometheus format)                                     |
| `sase telemetry dashboard`     | Live auto-refreshing TUI dashboard with optional historical charts mode                                        |
| `sase telemetry health`        | Traffic-light health assessment (OK/WARN/CRITICAL per subsystem)                                               |
| `sase telemetry export-config` | Export bundled monitoring stack (Docker Compose + Prometheus + Grafana)                                        |
| `sase xprompt catalog`         | Render every visible xprompt to a formatted PDF catalog                                                        |
| `sase xprompt expand`          | Expand prompt templates with sase references (supports `--trace`)                                              |
| `sase xprompt explain`         | Dry-run visualization of a workflow's execution plan                                                           |
| `sase xprompt graph`           | Generate a DAG visualization of a workflow (Mermaid or text)                                                   |
| `sase xprompt list`            | List all available xprompts with metadata, inputs, tags, and preview (JSON)                                    |

## Core Concepts

### ChangeSpec

A ChangeSpec is the tracked unit of work in sase. Each ChangeSpec follows a status lifecycle (WIP → Draft → Ready →
Mailed → Submitted) and carries structured metadata such as reviewers, tags, and comments. See
[`docs/change_spec.md`](docs/change_spec.md) for the full field reference.

### Workflows

Workflows are YAML-defined multi-step pipelines that can include agent steps (LLM calls), bash steps, and python steps.
They support control flow (conditionals, loops), parallel execution, and human-in-the-loop checkpoints. See
[`docs/workflow_spec.md`](docs/workflow_spec.md) for the format specification.

### XPrompt

XPrompt is the prompt template system. Templates use YAML front matter for metadata and Jinja2 for rendering. References
like `#name(args)` are expanded from multiple discovery locations (project, user, built-in). XPrompts can be annotated
with semantic role tags (`vcs`, `crs`, `fix_hook`, `rollover`) for lookup-by-role. XPrompt powers both standalone prompt
expansion and the prompt steps within workflows. The `sase xprompt` CLI provides subcommands for expanding prompts
(`expand --trace`), listing all available xprompts (`list`), visualizing workflow execution plans (`explain`), and
generating workflow DAGs (`graph`).

### Spec-Driven Development

SDD keeps durable planning context close to the code. Prompt snapshots live under `prompts/`, ordinary approved plans
are saved as `tales/`, executable multi-phase plans live under `epics/`, broad roadmap artifacts live under `legends/`,
long-horizon context lives under `myths/`, and exploratory notes live under `research/`. `sase sdd init` creates the
project-local SDD README, directory map, and short README files for the generated content directories. Each
prompt/artifact pair is linked through frontmatter so validation and repair commands can keep the history navigable. See
[`docs/sdd.md`](docs/sdd.md) for storage modes and [`docs/beads.md`](docs/beads.md) for the issue tracker that executes
epic phases.

## Project Structure

```
src/sase/
├── main/                  # CLI entry point and argument parsing
│   ├── parser*.py         # Argument parsing (ace, bead, commit subcommands)
│   ├── *_handler.py       # Subcommand handlers (ace, axe, cl, config, etc.)
│   ├── plugin_discovery.py # Entry-point-based plugin discovery
│   └── query_handler/     # Query execution handler
├── ace/                   # Interactive TUI and ChangeSpec engine
│   ├── changespec/        # ChangeSpec data model and parsing
│   ├── query/             # Query language (boolean expressions, filters)
│   ├── tui/               # Textual-based TUI interface
│   │   ├── thinking/      # Claude thinking block parser and display
│   │   ├── keymaps/       # Keymap registry, loader, and types
│   │   ├── actions/       # Keybinding action handlers
│   │   ├── models/        # Agent, workflow, and fold-state data models
│   │   ├── modals/        # Modal dialogs (query, status, hook history, etc.)
│   │   └── widgets/       # TUI widget components
│   │       ├── file_panel/   # Agent file viewer (diff, display, trimming)
│   │       ├── prompt_panel/ # Agent prompt viewer
│   │       └── prompt_text_area.py # Multiline prompt input (vim NORMAL/INSERT modes)
│   ├── handlers/          # Event and action handlers
│   ├── hooks/             # Lifecycle hooks (execution, formatting, persistence)
│   ├── mentors/           # Mentor system integration (entries, formatting, status)
│   ├── comments/          # Comment management
│   ├── timestamps/        # Timestamp formatting and lifecycle recording
│   ├── scheduler/         # Task scheduling within ACE
│   └── workflows/         # ACE-specific workflow integrations
├── agent/                 # Agent subprocess management
│   ├── launcher.py        # Agent subprocess launcher
│   ├── multi_prompt.py    # Multi-prompt parsing (frontmatter + segment splitting)
│   ├── multi_prompt_launcher.py # Sequential multi-agent launch orchestration
│   ├── repeat_launcher.py # %repeat fan-out / iteration variable expansion
│   ├── running.py         # Live agent registry (PID + artifacts lookup)
│   ├── agent_artifacts_cache.py # Cached agent metadata reads
│   ├── dismissed_name_rewrites.py # YYmmdd-prefix dismissal/revival helpers
│   └── names/             # Auto-naming, dedup, dismissal, claim helpers
├── agents/                # `sase agents` subcommand handlers (status/show/kill/tag)
├── chats/                 # `sase chats` subcommand handlers (list/show transcripts)
├── memory/                # Dynamic-memory keyword matching (#memory injection)
├── axe/                   # Lumberjack-based daemon and agent runners
│   ├── orchestrator.py    # Multi-lumberjack supervisor
│   ├── lumberjack.py      # Single-lumberjack scheduler loop
│   ├── chop_script_runner.py # External chop script discovery and execution
│   ├── config.py          # Lumberjack and chop configuration
│   ├── runner_pool.py     # Shared concurrent runner pool
│   ├── hook_jobs.py       # Hook/mentor/workflow check jobs
│   ├── maintenance.py     # Maintenance marker used to pause lumberjack ticks
│   ├── image_attachments.py # Generated image discovery for completion notifications
│   ├── run_agent_runner.py # Agent run orchestration
│   ├── run_workflow_runner.py # Workflow run orchestration
│   ├── state.py           # Lumberjack state persistence
│   ├── process.py         # Process management utilities
│   └── cli.py             # Axe CLI argument parsing
├── config/                # Configuration loading and management
│   ├── core.py            # Config file discovery, deep-merge, and loading
│   ├── mentor.py          # Mentor profile configuration
│   └── metahook.py        # Metahook configuration
├── core/                  # Public Python facade for core APIs (Rust-backable)
│   ├── rust.py            # Strict sase_core_rs loader for ported facades
│   ├── health.py          # `sase core health` extension probe
│   ├── parser_facade.py   # parse_project_file host API + Rust-backed parse_project_bytes
│   ├── wire.py            # Stable wire record types across the Rust boundary
│   ├── wire_conversion.py # Python ChangeSpec ↔ wire record serialization
│   ├── query_facade.py    # Query parse/build/evaluate compatibility facade
│   ├── query_corpus_facade.py # Persistent Rust query corpus for cached batch filtering
│   ├── status_facade.py   # Status transition helpers facade
│   ├── agent_scan_facade.py # Rust-backed agent artifact scanner
│   ├── agent_cleanup_*.py # Agent cleanup planning/execution facade and wires
│   ├── notification_store_*.py # Rust-backed notification JSONL snapshot/mutation facade
│   ├── git_query_*.py     # Rust-backed Git output parsers
│   ├── time.py            # Time formatting and parsing
│   ├── paths.py           # Path resolution helpers
│   ├── shell.py           # Shell command utilities
│   └── changespec.py      # ChangeSpec utility functions
├── history/               # History persistence
│   ├── chat.py            # Chat history persistence
│   ├── command.py         # Command history persistence
│   ├── hook.py            # Hook history persistence
│   └── prompt.py          # Prompt history persistence and querying
├── integrations/          # Public helpers consumed by external plugins/editors
├── sdd/                   # Spec-driven development utilities
│   ├── files.py           # SDD file management (prompts, tales, epics, legends)
│   └── beads.py           # SDD bead integration
├── workflows/             # All change-lifecycle workflows
│   ├── accept/            # Change acceptance workflows
│   ├── commit/            # Commit creation and CommitWorkflow orchestration
│   ├── commit_utils/      # COMMITS entry management
│   ├── crs.py             # Code review summary (CRS) workflow
│   ├── mentor.py          # Mentor execution workflow
│   └── rewind/            # Revert and restore operations
├── xprompts/              # Built-in xprompt workflows and schema
├── xprompt/               # Prompt templates and workflow execution
│   ├── processor.py       # XPrompt expansion engine
│   ├── directives.py      # %name directive parsing (%model, %name, %wait)
│   ├── loader.py          # XPrompt discovery and loading
│   ├── explain.py         # Dry-run workflow visualization (xprompt explain)
│   ├── graph.py           # DAG visualization (xprompt graph)
│   ├── _trace.py          # Expansion trace for --trace flag
│   ├── workflow_executor*.py # Workflow execution (steps, loops, parallel)
│   ├── workflow_loader*.py   # Workflow YAML parsing and validation
│   └── workflow_validator.py # Cross-step validation (field refs, finally, artifacts)
├── llm_provider/          # Pluggable LLM abstraction (Claude, Codex, Gemini)
├── vcs_provider/          # VCS abstraction (pluggy-based plugin system)
│   ├── _hookspec.py       # Pluggy hook specifications (VCSHookSpec)
│   ├── _plugin_manager.py # Plugin manager wrapping pluggy
│   ├── _registry.py       # VCS detection and provider registry
│   ├── _base.py           # Base VCS provider class
│   ├── _command_runner.py # Shared CommandRunner mixin
│   └── plugins/           # Built-in VCS plugins
│       ├── _git_common.py # Shared git operations (GitCommon base class)
│       └── bare_git.py    # BareGitPlugin (local bare-remote git repos)
├── workspace_provider/    # Workspace abstraction (pluggy-based plugin system)
│   ├── _hookspec.py       # Pluggy hook specifications (WorkspaceHookSpec)
│   ├── _plugin_manager.py # Plugin manager wrapping pluggy
│   ├── _registry.py       # Workspace detection and metadata registry
│   └── plugins/           # Built-in workspace plugins
│       ├── bare_git_*.py  # BareGitWorkspacePlugin (ref resolution, submit, mail)
│       └── cd_workspace.py # `#cd:<path>` local-directory workflow
├── running_field/         # Workspace claim and slot management
├── bead/                  # Git-native issue tracking (plans, phases, dependencies)
├── logs/                  # Agent run log collection and packaging
├── gemini_wrapper/        # Gemini-specific integration
├── telemetry/             # Prometheus telemetry (metrics, CLI, monitoring stack)
├── notifications/         # Notification system and delivery
├── status_state_machine/  # ChangeSpec status transitions
├── artifacts.py           # Artifact path resolution and management
├── content.py             # Content extraction and text utilities
├── output.py              # Rich console output helpers
├── scripts/               # Extracted Python utility scripts
tests/                     # Test suite (mirrors src/sase/ structure)
docs/                      # Detailed documentation
```

## Configuration

All tool configuration lives in `pyproject.toml`:

- **Build**: hatchling
- **Linting**: ruff (replaces black, isort, flake8, pylint)
- **Type checking**: mypy (strict mode)
- **Testing**: pytest + coverage
- **Multi-version testing**: tox (see `tox.ini`)

User configuration is loaded from `~/.config/sase/sase.yml` as the base, with optional `sase_*.yml` overlay files that
are deep-merged on top. A project-local `./sase.yml` in the current working directory takes highest priority. See
[`docs/configuration.md`](docs/configuration.md) for the full reference.

## Development

```bash
just install       # Install with dev deps
just fmt           # Auto-format code
just lint          # Run ruff + mypy
just test          # Fast parallel test run (no coverage)
just test-cov      # Parallel test run with coverage + 50% gate
just check         # All checks (fmt-check + lint + test)
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel + sdist
```

### Required Rust Core

Ported `sase.core` operations are served by the required Rust extension [`sase_core_rs`](docs/rust_backend.md),
distributed as the `sase-core-rs` package. Normal installs pull a prebuilt wheel; source installs build from a sibling
`../sase-core` checkout when present. There is no pure-Python fallback for ported operations, so `sase core health` is
the canonical install check. See [`docs/rust_backend.md`](docs/rust_backend.md) for build instructions, dispatch
semantics, and benchmarking.

## Documentation

Start with the user-facing guides for the surface you are operating, then drop into the references for exact formats and
extension APIs:

- [`docs/ace.md`](docs/ace.md) — ACE TUI user guide
- [`docs/agent_images.md`](docs/agent_images.md) — Generated Markdown PDF and image attachments plus ACE terminal
  graphics preview notes
- [`docs/beads.md`](docs/beads.md) — Bead issue tracking system
- [`docs/axe.md`](docs/axe.md) — Axe background automation daemon
- [`docs/change_spec.md`](docs/change_spec.md) — ChangeSpec field reference
- [`docs/commit_workflows.md`](docs/commit_workflows.md) — Commit, propose, and PR workflow reference
- [`docs/configuration.md`](docs/configuration.md) — Configuration reference
- [`docs/integrations.md`](docs/integrations.md) — Public integration-facing Python helpers
- [`docs/llms.md`](docs/llms.md) — LLM provider documentation
- [`docs/mentors.md`](docs/mentors.md) — Automated code review mentor system
- [`docs/notifications.md`](docs/notifications.md) — Notification system
- [`docs/perf_runbook.md`](docs/perf_runbook.md) — `sase ace` performance runbook (`SASE_TUI_TRACE` and benchmark
  harness)
- [`docs/plugins.md`](docs/plugins.md) — Plugin system and extension guide
- [`docs/project_spec.md`](docs/project_spec.md) — ProjectSpec format
- [`docs/query_language.md`](docs/query_language.md) — Query language reference
- [`docs/rust_backend.md`](docs/rust_backend.md) — Required Rust core (`sase_core_rs`) build, dispatch, and benchmarks
- [`docs/sdd.md`](docs/sdd.md) — Spec-Driven Development (SDD)
- [`docs/vcs.md`](docs/vcs.md) — VCS provider documentation
- [`docs/workspace.md`](docs/workspace.md) — Workspace provider documentation
- [`docs/workflow_spec.md`](docs/workflow_spec.md) — YAML workflow format
- [`docs/telemetry.md`](docs/telemetry.md) — Prometheus telemetry and monitoring
- [`docs/xprompt.md`](docs/xprompt.md) — XPrompt template reference

## Acknowledgements

### Boris' Method

Before sase existed, [Boris Cherny](https://borischerny.com/) — the inventor of
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) — pioneered a practical workflow for parallel agentic
development: five git checkouts, each in its own tmux tab, each running Claude Code in plan mode. This was one of the
first demonstrations that a single developer could effectively supervise multiple agents working on different tasks
simultaneously, and it proved that the bottleneck in agentic software engineering isn't the agent — it's the
coordination layer around it.

sase builds directly on this insight. Where Boris' method relies on the developer to manually manage the parallelism —
switching between tmux tabs, keeping track of which checkout is doing what, copy-pasting prompts, and mentally tracking
the state of five concurrent workstreams — sase replaces that manual overhead with structured infrastructure:

- **Workspaces instead of manual checkouts** — sase's workspace provider system creates and manages isolated working
  copies programmatically, eliminating the need to manually set up and maintain parallel git checkouts.
- **ChangeSpecs instead of mental bookkeeping** — Each unit of work gets a tracked lifecycle with status, metadata, and
  history, replacing the cognitive load of remembering what's happening in each tmux tab.
- **XPrompts instead of ad-hoc prompts** — Reusable, composable prompt templates with YAML front matter replace the
  prompt fragments scattered across shell history and scratch files.
- **True SDD instead of plan mode** — Plan mode produces ephemeral plans that vanish when the session ends. sase
  persists prompt snapshots plus ordinary tales, executable epics, and higher-level legends under `sdd/`. The
  `sdd/research/` corpus keeps exploratory notes with that same repository-local history. For larger efforts, epic files
  carry a bead ID in their frontmatter that links them to an epic-tier bead, and each phase of the epic gets its own
  bead whose ID appears in the corresponding commit messages — creating a traceable chain from epic to phase to commit.
  For smaller tales, commit messages include a `PLAN=<path>` tag pointing back to the plan file. The result is
  spec-driven development where the full history of intent, decomposition, and execution is preserved and queryable, not
  trapped in a single agent session's context window.
- **ACE instead of tmux** — A single TUI provides unified navigation, filtering, and management across all active
  workstreams, replacing the manual tab-switching workflow.
- **AXE instead of manual supervision** — A background daemon handles scheduling, monitoring, and lifecycle management
  of agent runs, so the developer doesn't need to babysit each session.

The core idea — that one developer can multiply their output by running several agents in parallel — was right. sase
just replaces the duct tape with a proper framework.

### Beads

[Steve Yegge's](https://steve-yegge.medium.com/) [beads](https://github.com/steveyegge/beads) (`bd`) introduced a
critical insight: AI coding agents suffer from a "50 First Dates" problem — every new session starts from scratch with
no memory of prior work. His solution was a dependency-aware graph issue tracker designed specifically for agents,
backed by [Dolt](https://github.com/dolthub/dolt) (a version-controlled SQL database), with hash-based IDs for
collision-free multi-agent writes, hierarchical epics-to-subtasks via dotted IDs, atomic `--claim` operations for agent
coordination, and semantic memory compaction to keep the working set small. The key idea was that agents don't need TODO
files or markdown plans — they need a structured, persistent memory layer they can query and update across sessions, so
that multi-session and multi-agent workflows stay coherent.

The `sase bead` command is a from-scratch reimplementation that carries this idea into sase's architecture while
drastically simplifying the surface area:

- **SQLite + JSONL instead of Dolt** — sase stores issues in SQLite for fast local queries and exports to a sorted JSONL
  file for git portability. Fresh clones rebuild the database automatically from JSONL, giving version-controlled
  persistence without an external database engine.
- **Plan tiers instead of arbitrary nesting** — sase uses plan-like beads with explicit `plan`, `epic`, and `legend`
  tiers plus executable phase children, rather than deeply nested dotted-ID trees. Linked epics use
  `--type plan(<plan_file>,<legend_bead_id>) --tier epic`; legend beads store `--epic-count` and `sase bead work`
  launches one epic-planning agent per proposed epic.
- **Multi-workspace aggregation** — Because sase already manages multiple parallel workspaces, `sase bead` can read
  issues across all workspace clones through a merged in-memory view, giving every agent visibility into the full
  project state without Dolt's sync machinery.
- **No external binary** — beads ships as a ~37MB Go binary with its own daemon process; `sase bead` is installed as
  part of sase and uses the required `sase_core_rs` extension for local storage/query/mutation speed, with no separate
  daemon to run.

The philosophical debt is real: beads proved that giving agents structured issue tracking — not just chat history —
fundamentally changes what's possible in multi-session agentic workflows. `sase bead` takes the ~5% of that system that
matters for sase's orchestration model and integrates it natively.

### Research Papers

This project was heavily influenced by two research papers:

- **[Agentic Software Engineering: Foundational Pillars and a Research Roadmap](https://arxiv.org/abs/2509.06216)**
  (Hassan et al., 2025) — This paper's vision of Structured Agentic Software Engineering (SASE) inspired the project's
  name and overall direction. Its concepts of the Agent Command Environment (ACE) and Agent Execution Environment (AEE)
  directly informed the naming and design of the `ace` TUI and `axe` daemon, respectively.

  <img src="docs/images/sase_paper.png" alt="Visual overview of the SASE paper" width="800">

- **[PDL: A Declarative Prompt Programming Language](https://arxiv.org/abs/2410.19135)** (Vaziri et al., 2024) — PDL's
  approach to declarative, YAML-based prompt programming influenced the design of xprompt workflows, sase's YAML-defined
  multi-step pipelines for orchestrating LLM calls and tool execution.

  <img src="docs/images/pdl_paper.png" alt="Visual overview of the PDL paper" width="800">

<sub>Images generated with [Nano Banana](https://notebooklm.google.com/) (Google's NotebookLM) via Gemini.</sub>
