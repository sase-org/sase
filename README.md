# sase - Structured Agentic Software Engineering

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

**sase** (pronounced "sassy") orchestrates coding agents into tracked, repeatable engineering workflows. It gives agent
runs a durable operating layer: isolated workspaces, reusable prompts, scheduling, status, review state, and commit
flow.

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
- **SDD and Beads** - Spec-driven planning artifacts plus git-portable issue tracking for epics, phases, and
  dependencies.
- **Plugins** - Provider boundaries for agents, VCS operations, workspaces, notifications, and external integrations.

## Quick start

Requirements:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

```bash
uv venv .venv
source .venv/bin/activate
just install
sase
```

Useful first commands:

```bash
sase ace                  # open the interactive control surface
sase run "<prompt>"       # launch an agent or workflow
sase agents status        # inspect running agents
sase bead onboard         # see the bead issue-tracking quick start
```

## Keep reading

The full documentation lives at [sase.sh](https://sase.sh/). Start with:

- [ACE TUI](https://sase.sh/ace/) ([local](docs/ace.md))
- [AXE Automation](https://sase.sh/axe/) ([local](docs/axe.md))
- [Spec-Driven Development](https://sase.sh/sdd/) ([local](docs/sdd.md))
- [XPrompts](https://sase.sh/xprompt/) ([local](docs/xprompt.md))
- [ChangeSpecs](https://sase.sh/change_spec/) ([local](docs/change_spec.md))
- [Beads](https://sase.sh/beads/) ([local](docs/beads.md))
- [Workflows](https://sase.sh/workflow_spec/) ([local](docs/workflow_spec.md))
- [Plugins](https://sase.sh/plugins/) ([local](docs/plugins.md))
- [LLM Providers](https://sase.sh/llms/) ([local](docs/llms.md))
- [Rust Backend](https://sase.sh/rust_backend/) ([local](docs/rust_backend.md))

The `docs/` directory is a MkDocs Material site configured by [mkdocs.yml](mkdocs.yml). Run `just docs-check` for the
strict docs build and `just docs-pdf-check` for the handbook PDF validation.

## Development

```bash
just install       # Install with dev deps
just fmt           # Auto-format code
just lint          # Run ruff, mypy, pyvision, keep-sorted, and SDD validation
just test          # Fast parallel test run
just test-slow     # Slow pytest subset only
just test-cov      # Parallel test run with coverage + 50% gate
just check         # All checks: formatting, lint, SDD validation, and tests
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel + sdist
```

`just test`, `just test-slow`, and `just test-cov` size the pytest-xdist worker pool from local CPU count, capped at 16.
Set `SASE_PYTEST_WORKERS=<N>` to override that value.

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
