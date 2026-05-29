# sase - Structured Agentic Software Engineering

[![Docs](https://img.shields.io/badge/docs-sase.sh-3b82f6?logo=readthedocs&logoColor=white)](https://sase.sh/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

**sase** (pronounced "sassy") orchestrates coding agents into tracked, repeatable engineering workflows. It gives agent
runs a durable operating layer: isolated workspaces, reusable prompts, scheduling, status, review state, and commit
flow.

**Full documentation: [sase.sh](https://sase.sh/).**

<img src="docs/images/sase_overview.png" alt="Overview of SASE coordinating parallel coding agents, isolated workspaces, and durable workflow state" width="800">

## Why sase

Coding agents are useful one run at a time. Real engineering work needs coordination:

- Schedule, monitor, resume, and archive background agent runs.
- Keep prompts and multi-step workflows reusable instead of trapped in shell history.
- Track each unit of work with status, metadata, comments, mentors, and review state.
- Allocate and manage isolated workspaces for parallel work.
- Keep commit, PR, notification, and artifact flow tied back to the original work.

The goal is not to replace coding agents. The goal is to make agent-driven software engineering dependable.

## Works with your agents

| Agent                                                         | Status        |
| ------------------------------------------------------------- | ------------- |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | **Supported** |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli)     | **Supported** |
| [Codex](https://github.com/openai/codex)                      | **Supported** |
| [Qwen Code](https://github.com/QwenLM/qwen-code)              | **Supported** |
| [OpenCode](https://opencode.ai/)                              | **Supported** |

## Core pieces

- **ACE** - The interactive TUI for ChangeSpecs, live agents, notifications, automation, comments, and review.
- **AXE** - The background automation daemon for scheduled work, chop scripts, hooks, mentors, and workflow runs.
- **XPrompt** - Prompt templates and YAML workflows with reference expansion, typed inputs, and workflow visualization.
- **ChangeSpecs** - Tracked CL/PR-sized units of work with lifecycle state, commits, comments, mentors, and metadata.
- **Memory** - Agent instruction memory loaded through `AGENTS.md`, keyword-triggered long-term context, audited agent
  reads, and human-reviewed write proposals.
- **SDD and Beads** - Spec-driven planning artifacts plus git-portable issue tracking for epics, phases, and
  dependencies.
- **Commit finalizer** - A provider-neutral post-invocation check that asks SASE-launched agents to commit dirty
  enforced workspaces, treats static singleton siblings as advisory, and auto-commits exact SDD status closeouts.
- **Plugins** - Provider boundaries for agents, VCS operations, workspaces, notifications, and external integrations.
- **Editor integration** - An xprompt LSP and JSON helper bridge for completions, snippets, hover, diagnostics, and
  jump-to-definition in companion editors.

## Quick start

Requirements:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

```bash
uv venv .venv
source .venv/bin/activate
just install
sase core health
sase ace
```

Useful first commands:

```bash
sase core health          # verify the required Rust backend before launching agents
sase memory init --no-commit  # write memory files; skip only the project commit/push
sase memory list         # inspect loaded, referenced, available, and missing memory files
sase memory review --list  # human review of pending long-term memory proposals
sase memory log          # summarize audited long-term memory reads
sase memory log --include proposals  # include memory proposal/review events
sase memory episodes build -n <agent-name>  # store a source-linked episode from completed work
sase memory episodes build -s 2026-05-01 -u 2026-05-26 --split  # backfill connected components
sase memory episodes recall -q "retry feedback"  # search stored episode evidence by topic
sase memory episodes export -s 2026-05-01 -u 2026-05-26 -b high -j  # read-only event-readiness summaries
sase init sdd             # create/refresh generated SDD guides and directory map
sase skills list          # inspect generated skill sources, targets, and drift
sase skills init --dry-run  # preview provider skill files before deploying them
sase ace                  # open the interactive control surface
sase run "<prompt>"       # launch an agent or workflow
sase agents status        # inspect running agents
sase agents index status  # check ACE's fast Agents-tab artifact index
sase bead onboard         # see the bead issue-tracking quick start
sase workspace list       # inspect the current project's numbered workspace view
sase workspace path 10    # preview where managed workspace #10 would live
sase workspace open 10    # create/refresh workspace #10, then print its path
```

SASE-launched agents use `sase memory read ... -r/--reason ...` and `sase memory write ...` when they need audited
long-term memory access. Those commands require agent identity in the environment, so a normal human shell should start
with `sase memory list`, `sase memory review --list`, and `sase memory log`.

## Operational model

SASE keeps durable state outside any one chat session:

- **Rust core** - Ported parsing, launch, notification, agent-scan, cleanup, and bead operations are served by the
  required `sase_core_rs` extension. Run `sase core health` before first use and after dependency changes.
- **Numbered workspaces** - Parallel agents run in numbered project checkouts. Workspace `#0` is the primary checkout,
  `#1` through `#9` are reserved, and new claims allocate from `#10` upward.
- **Workspace roots** - By default, numbered checkouts live under the platform state directory in a project-keyed
  managed root. Set `workspace.root: adjacent` to keep the legacy `<primary>_<num>/` sibling layout, or use an absolute
  path for a custom managed-root base; `sase workspace list`, `path`, `repair`, `cleanup`, and `migrate` inspect and
  maintain that view. Normal `sase run` launches prepare their own workspaces; use `sase workspace open 10` when you
  want to prepare a specific checkout for an external shell, editor, or debugging session.
- **Provider retries** - The LLM provider layer can retry matching provider errors, preserve the workspace across
  retries, and fall back to another model when configured. Claude adds built-in matching for context-limit,
  socket-close, and Claude CLI API-error output; per-provider retry counts, waits, and fallback policy live under
  `llm_provider.retry`.
- **Configured sibling repos** - Project and user config can expose related repositories to launched agents as
  workspace-matched directories. SASE records those paths in environment variables and agent metadata so cross-repo work
  uses the same numbered workspace as the main checkout, while singleton repos such as chezmoi can opt out with
  `workspace.strategy: none`.
- **Commit finalization** - After a successful provider invocation inside a SASE-launched agent session, the
  provider-neutral finalizer checks the main workspace and configured Git sibling workspace directories for uncommitted
  changes. Static siblings (`workspace.strategy: none`) are reported as advisory work that the agent may commit when it
  made those changes, but they do not fail the run if they remain dirty. If the only enforced change is one tracked SDD
  markdown file under `sdd/tales/`, `sdd/epics/`, `sdd/legends/`, or `sdd/myths/` whose leading front matter changes
  exactly from `status: wip` to `status: done`, SASE commits that closeout directly. Other dirty enforced workspaces
  trigger bounded follow-up invocations that tell the same agent to use the configured commit skill; if enforced
  workspaces are still dirty after the configured pass limit, the agent run fails with a clear artifact trail.
- **Durable artifacts** - Agent metadata, chats, notifications, prompt history, source-linked episode evidence,
  dismissed-agent bundles, saved agent groups, ChangeSpecs, SDD files, and beads are stored in predictable project/user
  directories so ACE, AXE, CLI commands, and external integrations can share state. Long-term memory reads and write
  proposals are also project-scoped and audited so agents can discover context without silently changing canonical
  memory files. ACE uses a persistent artifact index for its normal Agents-tab "visible inbox" - active plus recent
  completed, non-hidden rows - so startup does not scan all history. Use `sase agents index status` for a lightweight
  health check, `verify` to compare the index with source artifacts, and `gc` to rebuild the index and dismissed
  projection.

## Keep reading

The full documentation lives at **[sase.sh](https://sase.sh/)**. Start with:

- [ACE TUI](https://sase.sh/ace/) ([local](docs/ace.md))
- [Initialization](https://sase.sh/init/) ([local](docs/init.md))
- [Memory](https://sase.sh/memory/) ([local](docs/memory.md))
- [Episodes](https://sase.sh/episodes/) ([local](docs/episodes.md))
- [AXE Automation](https://sase.sh/axe/) ([local](docs/axe.md))
- [Spec-Driven Development](https://sase.sh/sdd/) ([local](docs/sdd.md))
- [XPrompts](https://sase.sh/xprompt/) ([local](docs/xprompt.md))
- [ChangeSpecs](https://sase.sh/change_spec/) ([local](docs/change_spec.md))
- [Beads](https://sase.sh/beads/) ([local](docs/beads.md))
- [Workflows](https://sase.sh/workflow_spec/) ([local](docs/workflow_spec.md))
- [Workspaces](https://sase.sh/workspace/) ([local](docs/workspace.md))
- [Mentors](https://sase.sh/mentors/) ([local](docs/mentors.md))
- [Commit Workflows](https://sase.sh/commit_workflows/) ([local](docs/commit_workflows.md))
- [Plugins](https://sase.sh/plugins/) ([local](docs/plugins.md))
- [LLM Providers](https://sase.sh/llms/) ([local](docs/llms.md))
- [VCS Providers](https://sase.sh/vcs/) ([local](docs/vcs.md))
- [Integration APIs](https://sase.sh/integrations/) ([local](docs/integrations.md))
- [Notifications](https://sase.sh/notifications/) ([local](docs/notifications.md))
- [Editor Integration](https://sase.sh/editor/) ([local](docs/editor.md))
- [Agent Attachments](https://sase.sh/agent_images/) ([local](docs/agent_images.md))
- [Mobile Gateway](https://sase.sh/mobile_gateway/) ([local](docs/mobile_gateway.md))
- [Telemetry](https://sase.sh/telemetry/) ([local](docs/telemetry.md))
- [Rust Backend](https://sase.sh/rust_backend/) ([local](docs/rust_backend.md))
- [CLI Reference](https://sase.sh/cli/) ([local](docs/cli.md))
- [Configuration](https://sase.sh/configuration/) ([local](docs/configuration.md))
- [Query Language](https://sase.sh/query_language/) ([local](docs/query_language.md))
- [Architecture](https://sase.sh/architecture/) ([local](docs/architecture.md))
- [Development](https://sase.sh/development/) ([local](docs/development.md))

The `docs/` directory is a MkDocs Material site configured by [mkdocs.yml](mkdocs.yml). Run `just docs-check` for the
strict docs build and `just docs-pdf-check` for the handbook PDF validation.

## Development

```bash
just install       # Install with dev deps
just fmt           # Auto-format code
just lint          # Run ruff, mypy, pyvision, keep-sorted, and SDD validation
just test          # Fast parallel test run, including PNG visual snapshots
just test-slow     # Slow pytest subset only
just test-visual   # ACE PNG visual regression snapshots only
just test-terminal-smoke  # Optional real-terminal ACE smoke test
just test-cov      # Parallel test run with coverage + 50% gate, including visual snapshots
just check         # All checks: formatting, lint, SDD validation, and tests
sase validate      # Validation: init --check plus sdd validate
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel + sdist
```

`just test`, `just test-slow`, `just test-visual`, and `just test-cov` size the pytest-xdist worker pool from local CPU
count, capped at 16. Set `SASE_PYTEST_WORKERS=<N>` to override that value. Default test runs exclude slow and
terminal-smoke tests but include the PNG visual snapshot suite. Use `just test-visual` for focused ACE PNG visual
regression work, and accept intentional PNG golden changes with `--sase-update-visual-snapshots` only after inspecting
`.pytest_cache/sase-visual/`.

### Required Rust core

Ported `sase.core` operations are served by the required Rust extension [`sase_core_rs`](docs/rust_backend.md),
distributed as the `sase-core-rs` package. Normal installs pull a prebuilt wheel; source installs build from a sibling
`../sase-core` checkout when present. There is no pure-Python fallback for ported operations, so `sase core health` is
the canonical install check.

## Acknowledgements

sase builds on Boris Cherny's practical demonstration of parallel agentic development with multiple checkouts and tmux
sessions. sase keeps that core insight - one developer supervising several agents - and adds structured workspaces,
ChangeSpecs, XPrompts, SDD artifacts, ACE, and AXE around it.

The expanded acknowledgements live in [docs/acknowledgements.md](docs/acknowledgements.md).

`sase bead` is influenced by Steve Yegge's [beads](https://github.com/steveyegge/beads), especially the idea that agents
need a structured, persistent, dependency-aware memory layer rather than ad hoc TODO files. sase adapts that idea with
SQLite, JSONL export, plan tiers, and multi-workspace aggregation.

The project name and direction were also influenced by
[Agentic Software Engineering: Foundational Pillars and a Research Roadmap](https://arxiv.org/abs/2509.06216), and
XPrompt workflows were influenced by [PDL: A Declarative Prompt Programming Language](https://arxiv.org/abs/2410.19135).
