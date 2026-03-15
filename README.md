# sase — Structured Agentic Software Engineering

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

## Overview

**sase** is a Python toolkit for AI-powered software engineering workflows. It combines an interactive TUI, a scheduling
daemon, a YAML workflow engine, and pluggable LLM/VCS abstractions into a cohesive system for managing code changes at
scale.

<img src="docs/images/sase_overview.jpg" alt="Visual overview of sase" width="800">

## Supported Coding Agents

sase is designed to work with the coding agents you already use:

| Agent                                                         | Status        |
| ------------------------------------------------------------- | ------------- |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | **Supported** |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli)     | **Supported** |
| [Codex](https://github.com/openai/codex)                      | **Supported** |

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
- **XPrompt** — Typed prompt templates with reference expansion, YAML front matter, and CLI tools for expansion,
  workflow visualization, and DAG graphing
- **Workflows** — YAML-defined multi-step pipelines with agent, bash, and python steps, control flow, parallel
  execution, and human-in-the-loop support
- **ChangeSpec** — Tracked unit of work with a full status lifecycle
- **LLM Providers** — Pluggable AI abstraction (Claude, Codex, Gemini) with pre/post-processing
- **VCS Providers** — Pluggy-based version control abstraction (git bundled; GitHub and Mercurial via plugin packages)
- **Query Language** — Boolean expression language for filtering and searching ChangeSpecs

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                        sase CLI                        │
├─────────────┬────────────┬────────────┬────────────────┤
│  ace        │  axe       │  run       │ commit/amend   │
│  (TUI)      │  (daemon)  │ (workflows)│  (VCS ops)     │
├─────────────┴────────────┴────────────┴────────────────┤
│                      Core Engine                       │
│    ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│    │ ChangeSpec │  │  XPrompt   │  │  Workflows │      │
│    │  Tracking  │  │  Templates │  │   (YAML)   │      │
│    └────────────┘  └────────────┘  └────────────┘      │
├───────────────────┬─────────────────┬──────────────────┤
│   LLM Provider    │  VCS Provider   │ Workspace Prov.  │
│(Claude,Codex,Gem) │ (pluggy plugins)│ (pluggy plugins) │
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

| Command                | Description                                                                      |
| ---------------------- | -------------------------------------------------------------------------------- |
| `sase ace`             | Interactive TUI for navigating and managing ChangeSpecs                          |
| `sase axe start`       | Start the lumberjack-based daemon (orchestrator mode)                            |
| `sase axe stop`        | Stop the running axe orchestrator                                                |
| `sase axe chop`        | List or run individual chop scripts                                              |
| `sase axe lumberjack`  | List, run, or check status of lumberjacks                                        |
| `sase search`          | Search and filter ChangeSpecs with query expressions                             |
| `sase run`             | Execute workflows, resume agents by name, or run a query directly                |
| `sase xprompt expand`  | Expand prompt templates with sase references (supports `--trace`)                |
| `sase xprompt explain` | Dry-run visualization of a workflow's execution plan                             |
| `sase xprompt graph`   | Generate a DAG visualization of a workflow (Mermaid or text)                     |
| `sase commit`          | Create a commit with formatted CL description and metadata                       |
| `sase amend`           | Amend a commit with COMMITS tracking                                             |
| `sase revert`          | Revert a ChangeSpec by pruning its CL and archiving its diff                     |
| `sase restore`         | Restore a reverted ChangeSpec by re-applying its diff                            |
| `sase init-git`        | Initialize a new bare-repo-backed git project                                    |
| `sase path`            | Print well-known sase paths (`xprompts-dir`, `xprompts-schema`, `config-schema`) |
| `sase notify`          | Create a notification (reads JSON from stdin or uses flags)                      |
| `sase user-question`   | Handle user question from Claude Code hook                                       |
| `sase plan-approve`    | Handle plan approval from Claude Code hook                                       |

## Core Concepts

### ChangeSpec

A ChangeSpec is the tracked unit of work in sase. Each ChangeSpec follows a status lifecycle (WIP → Drafted → Mailed →
Submitted) and carries structured metadata such as reviewers, tags, and comments. See
[`docs/change_spec.md`](docs/change_spec.md) for the full field reference.

### Workflows

Workflows are YAML-defined multi-step pipelines that can include agent steps (LLM calls), bash steps, and python steps.
They support control flow (conditionals, loops), parallel execution, and human-in-the-loop checkpoints. See
[`docs/workflow_spec.md`](docs/workflow_spec.md) for the format specification.

### XPrompt

XPrompt is the prompt template system. Templates use YAML front matter for metadata and Jinja2 for rendering. References
like `#name(args)` are expanded from multiple discovery locations (project, user, built-in). XPrompt powers both
standalone prompt expansion and the prompt steps within workflows. The `sase xprompt` CLI provides subcommands for
expanding prompts (`expand --trace`), visualizing workflow execution plans (`explain`), and generating workflow DAGs
(`graph`).

## Project Structure

```
src/sase/
├── main/                  # CLI entry point and argument parsing
│   └── query_handler/     # Query execution handler
├── ace/                   # Interactive TUI and ChangeSpec engine
│   ├── changespec/        # ChangeSpec data model and parsing
│   ├── query/             # Query language (boolean expressions, filters)
│   ├── tui/               # Textual-based TUI interface
│   │   ├── thinking/      # Claude thinking block parser and display
│   │   ├── keymaps/       # Keymap registry, loader, and types
│   │   ├── actions/       # Keybinding action handlers
│   │   ├── modals/        # Modal dialogs (query, status, hook history, etc.)
│   │   └── widgets/       # TUI widget components
│   │       ├── file_panel/   # Agent file viewer (diff, display, trimming)
│   │       └── prompt_panel/ # Agent prompt viewer
│   ├── handlers/          # Event and action handlers
│   ├── hooks/             # Lifecycle hooks (execution, formatting, persistence)
│   ├── comments/          # Comment management
│   ├── scheduler/         # Task scheduling within ACE
│   └── workflows/         # ACE-specific workflow integrations
├── axe/                   # Lumberjack-based daemon (orchestrator, chops, runner pool)
│   ├── orchestrator.py    # Multi-lumberjack supervisor
│   ├── lumberjack.py      # Single-lumberjack scheduler loop
│   ├── chop_script_runner.py # External chop script discovery and execution
│   ├── config.py          # Lumberjack and chop configuration
│   ├── runner_pool.py     # Shared concurrent runner pool
│   ├── hook_jobs.py       # 1-second interval hook/mentor/workflow jobs
│   ├── state.py           # Lumberjack state persistence
│   ├── process.py         # Process management utilities
│   └── cli.py             # Axe CLI argument parsing
├── xprompt/               # Prompt templates and workflow execution
│   ├── processor.py       # XPrompt expansion engine
│   ├── directives.py      # %name directive parsing (%model, %name, %wait)
│   ├── loader.py          # XPrompt discovery and loading
│   ├── explain.py         # Dry-run workflow visualization (xprompt explain)
│   ├── graph.py           # DAG visualization (xprompt graph)
│   ├── _trace.py          # Expansion trace for --trace flag
│   ├── workflow_executor*.py # Workflow execution (steps, loops, parallel)
│   └── workflow_loader*.py   # Workflow YAML parsing and validation
├── llm_provider/          # Pluggable LLM abstraction (Claude, Gemini)
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
│       └── bare_git_*.py  # BareGitWorkspacePlugin (ref resolution, submit, mail)
├── plugin_discovery.py    # Entry-point-based plugin discovery (shared)
├── agent_launcher.py      # Agent subprocess launcher
├── commit_workflow/       # Commit creation workflows
├── commit_utils/          # COMMITS entry management
├── accept_workflow/       # Change acceptance workflows
├── rewind_workflow/       # Revert and restore operations
├── gemini_wrapper/        # Gemini-specific integration
├── notifications/         # Notification system and delivery
├── status_state_machine/  # ChangeSpec status transitions
├── mentor_config.py       # Mentor profile configuration loading
├── metahook_config.py     # Metahook configuration loading
├── chat_history.py        # Chat history persistence
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
just test          # Run tests with coverage
just check         # All checks (fmt-check + lint + test)
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel + sdist
```

## Documentation

- [`docs/ace.md`](docs/ace.md) — ACE TUI user guide
- [`docs/axe.md`](docs/axe.md) — Axe background automation daemon
- [`docs/change_spec.md`](docs/change_spec.md) — ChangeSpec field reference
- [`docs/configuration.md`](docs/configuration.md) — Configuration reference
- [`docs/llms.md`](docs/llms.md) — LLM provider documentation
- [`docs/plugins.md`](docs/plugins.md) — Plugin system and extension guide
- [`docs/project_spec.md`](docs/project_spec.md) — ProjectSpec format
- [`docs/query_language.md`](docs/query_language.md) — Query language reference
- [`docs/vcs.md`](docs/vcs.md) — VCS provider documentation
- [`docs/workspace.md`](docs/workspace.md) — Workspace provider documentation
- [`docs/workflow_spec.md`](docs/workflow_spec.md) — YAML workflow format
- [`docs/xprompt.md`](docs/xprompt.md) — XPrompt template reference

## Acknowledgements

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

## License

MIT
