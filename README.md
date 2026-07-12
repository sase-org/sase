# sase - Structured Agentic Software Engineering

[![Docs](https://img.shields.io/badge/docs-sase.sh-3b82f6?logo=readthedocs&logoColor=white)](https://sase.sh/)
[![PyPI](https://img.shields.io/pypi/v/sase?logo=pypi&logoColor=white)](https://pypi.org/project/sase/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type_checker-mypy-blue.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/tests-pytest-blue.svg)](https://docs.pytest.org/)
[![tox](https://img.shields.io/badge/ci-tox-yellow.svg)](https://tox.wiki/)

**sase** (pronounced "sassy") orchestrates coding agents into tracked, repeatable engineering workflows. It gives agent
runs a durable operating layer: isolated workspaces, reusable prompts, scheduling, status, review state, and commit
flow.

**Full documentation: [sase.sh](https://sase.sh/).**

## Quick start

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- One authenticated coding-agent CLI: Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code, or OpenCode

SASE orchestrates an existing provider CLI; it does not replace that provider's install or authentication flow. Install
SASE from PyPI, then run `sase doctor` as the readiness gate before launching your first agent:

```bash
uv tool install sase
sase version
sase doctor
```

See [INSTALL.md](INSTALL.md) for the full installation guide, including system requirements, optional runtime tools,
plugin installs, and how to keep SASE up to date.

Plugins such as `sase-github` are best installed from the **Updates** tab of the SASE Admin Center (press `#` inside
`sase ace`). To install SASE together with a plugin in one command instead, add `--with`:

```bash
uv tool install sase --with sase-github
```

After `sase doctor` reports a usable provider, try a read-only run against your default workspace:

```bash
sase run "#git:home summarize what this repository does; do not change files"
sase agent list
```

If `sase doctor` reports a missing provider executable or authentication gap, install and authenticate one of the
supported CLIs, then run `sase doctor` again. See [Installing & Authenticating Agent Providers](docs/agent_providers.md)
for the per-provider install and auth commands.

For the guided beginner path, follow the [Getting Started guide](https://sase.sh/getting_started/).

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
| [Antigravity CLI (`agy`)](https://antigravity.google/)        | **Supported** |
| [Codex](https://github.com/openai/codex)                      | **Supported** |
| [Qwen Code](https://github.com/QwenLM/qwen-code)              | **Supported** |
| [OpenCode](https://opencode.ai/)                              | **Supported** |

<img src="docs/images/sase_overview.png" alt="Overview of SASE coordinating parallel coding agents, isolated workspaces, and durable workflow state" width="800">

## Core pieces

- **ACE** - The interactive TUI for ChangeSpecs, live agents, notifications, automation, comments, and review.
- **AXE** - The background automation daemon for scheduled work, chop scripts, hooks, mentors, and workflow runs.
- **XPrompt** - Prompt templates and YAML workflows with reference expansion, typed inputs, output-variable handoffs,
  and workflow visualization.
- **ChangeSpecs** - Tracked PR-sized units of work with lifecycle state, commits, comments, mentors, and metadata.
- **Memory** - Agent instruction memory with short-term notes inlined directly into a generated `AGENTS.md` (and
  provider files such as `CLAUDE.md` kept as full copies of it), keyword-triggered long-term context, audited agent
  reads, and human-reviewed write proposals.
- **SDD and Beads** - Spec-driven planning artifacts plus git-portable issue tracking for epics, phases, and
  dependencies.
- **Commit finalizer** - A provider-neutral post-invocation check that asks SASE-launched agents to commit dirty
  enforced workspaces, treats static singleton linked repos as advisory, and auto-commits exact SDD status closeouts.
- **Plugins** - Provider boundaries for agents, VCS operations, workspaces, notifications, and external integrations.
- **Editor integration** - An xprompt LSP and JSON helper bridge for completions, snippets, hover, diagnostics, and
  jump-to-definition in companion editors.

## Common commands

```bash
sase init -c             # check initialization drift without writing files
sase init --all --check  # check every active main project without writing files
sase init --all --yes    # apply all initializers; missing GitHub SDD repos still require y/yes
sase doctor -v           # readable install, config, project, provider, and state report
sase version             # inspect the exact SASE packages loaded by this environment
sase ace                  # open the interactive control surface; press # for the Admin Center (Config / Logs / Projects / Tasks / Updates / XPrompts)
sase run "<prompt>"       # launch an agent or workflow
sase agent list          # inspect running agents
sase vcs list            # inspect the available primary, linked, and SDD repository set
sase vcs log             # inspect recent primary and linked repository commits
sase vcs log --sdd       # include the current project's separate SDD history
sase vcs log --all --sdd # include repos and separate SDD histories from every project
sase plan                 # review pending proposals, approvals, and inferred rejected archive rows
sase bead onboard         # see the bead issue-tracking quick start
sase sdd path             # print the effective SDD root for this workspace
sase sdd init             # initialize managed GitHub plans/research companions
sase sdd migrate -c -d    # after init, preview importing a legacy SDD store
sase plugin list         # browse built-in/community plugins and update indicators
sase update -n           # preview a SASE core + installed-plugin update
sase workspace list       # inspect numbered workspaces for the current project
```

When asking for help, attach `sase doctor -v` for a readable report or `sase doctor -j` when a machine-readable support
artifact is easier to share.

SASE-launched agents use `sase memory read ... -r/--reason ...` and `sase memory write ...` when they need audited
long-term memory access. Those commands require agent identity in the environment, so a normal human shell should start
with `sase memory list`, `sase memory review --list`, and `sase memory log`.

## Operational model

SASE keeps durable state outside any one chat session:

- **Rust core** - Ported parsing, launch, notification, agent-scan, cleanup, and bead operations are served by the
  required `sase_core_rs` extension. Run `sase core health` before first use and after dependency changes.
- **Project lifecycle** - ProjectSpec metadata can mark a project `active` or `inactive`. Missing `PROJECT_STATE` is
  treated as `active`. Default launch pickers, ChangeSpec searches, project-local xprompt catalogs, broad mobile helper
  catalogs, and known-project VCS refs such as `#gh:sase` only use active projects. Use `sase project list --state all`,
  `sase project show <project>`, and `sase project activate <project>` when revisiting inactive work. Legacy on-disk
  `archived` and `closed` ProjectSpecs are read as inactive. In ACE, press `#` and switch to the **Projects** tab of the
  SASE Admin Center to manage lifecycle state, edit ProjectSpecs, mark projects for bulk lifecycle actions, or delete an
  obsolete SASE project directory. Deleting from that tab removes `~/.sase/projects/<project>/`, not the workspace
  checkout.
- **Update workflow** - ACE caches latest-version checks by default, shows startup and top-bar update signals when SASE
  or installed plugins are behind, and uses the Admin Center **Updates** tab for review. That tab shows SASE core/plugin
  versions, optional incoming commit previews, installable plugin rows that can be marked with `I` / `Space`, and
  dry-run confirmation modals; press `u` for full `sase update`, `U` for the highlighted plugin when that row has an
  update available, `i` to install the marked set (or the highlighted plugin when nothing is marked), or `m` to switch
  the install between managed PyPI wheels and dev (editable) checkouts (the `sase update --to dev|pypi` analog).
  Successful changed updates from ACE restart ACE and axe, and self-updates can show a one-shot post-update confirmation
  toast.
- **Numbered workspaces** - Parallel agents run in numbered project checkouts. Workspace `#0` is the primary checkout,
  `#1` through `#9` are reserved, and new claims allocate from `#10` upward.
- **Workspace roots** - By default, numbered checkouts live under the platform state directory in a project-keyed
  managed root. Set `workspace.root: adjacent` to keep the legacy `<primary>_<num>/` sibling layout, or use an absolute
  path for a custom managed-root base; `sase workspace list`, `path`, `repair`, `cleanup`, and `migrate` inspect and
  maintain that view. Normal `sase run` launches prepare their own workspaces; use
  `sase workspace open -r "<reason>" 10` when you want to prepare a specific checkout for an external shell, editor, or
  debugging session.
- **Prompt authoring surface** - ACE's prompt input combines prompt history, snippets, `Ctrl+T` completion for
  directives, xprompts, slash skills, paths, and recent file references, plus a `Ctrl+R` recursive fuzzy file finder.
  Relative path lookup is prompt-aware: registered workspace-provider refs and known-project refs such as `#git:sase` or
  `#gh:sase-org/sase` can root completion in that project checkout. Typing `+` at the absolute start of the prompt, or
  `#+` at a token boundary, opens a project/ChangeSpec picker for active launchable projects and active PR-sized
  ChangeSpecs; accepting a row inserts the canonical VCS workspace tag such as `#gh:sase`. Typing `:` after a registered
  VCS workflow tag, such as `#gh:` or `#git:`, opens token-local ref completion for that provider's projects and active
  PR-sized ChangeSpecs; VCS plugins can add namespace rows such as `sase-org/` that chain into repository completion.
  Typing `/` inside a known VCS ref such as `#gh:bbugyi200/` opens repository completion through the owning workspace
  plugin and accepts a token-local owner/repo edit. If no prompt workspace ref resolves, ACE uses the TUI process
  directory. When ACE loads a prompt with literal top-level `---` multi-agent separators, it renders a stack of prompt
  panes so each agent segment can be edited, reordered, launched individually, or submitted together in top-to-bottom
  order. In prompt NORMAL mode, use `g-` to add panes, `gj`/`gk` to focus panes, and `gJ`/`gK` to reorder them.
  Prompt-level frontmatter is edited from the Frontmatter Panel with `g=`, the active pane can be stashed with `Ctrl+S`,
  all non-empty panes can be bundled into one stash row with `gs`, the current stack can overwrite a pinned stash with
  `gS`, and the current stack can be saved as a reusable xprompt with `gx`; open the unified stashed-prompt picker with
  `Ctrl+G p` from the prompt bar or `@` from the main ACE tabs. `Ctrl+P` moves through recent workspace prefixes toward
  older entries and `Ctrl+N` toward newer entries; both pass through a no-prefix stop. Use `%wait` when one segment must
  wait for another to finish.
- **Provider retries** - The LLM provider layer can retry matching provider errors, preserve the workspace across
  retries, and fall back to another model when configured. Claude adds built-in matching for context-limit,
  socket-close, and Claude CLI API-error output; per-provider retry counts, waits, and fallback policy live under
  `llm_provider.retry`.
- **Configured linked repos** - Project and user config can expose related repositories to launched agents as
  workspace-matched directories via the `linked_repos` key (the legacy `sibling_repos` key still works as a deprecated
  alias). SASE records those paths in environment variables and agent metadata so cross-repo work uses the same numbered
  workspace as the main checkout. Numbered linked checkouts live under `<host_workspace>/sase/repos/<linked_repo>`, so
  two host projects cannot collide. `sase init workspace` adds the tracked `/sase/repos/` ignore rule; existing legacy
  `.sase/workspaces/` clones are recognized and moved on first materialization. ACE uses that metadata for live context:
  dirty linked repos can appear in a non-terminal agent's `DELTAS` section, and linked workspaces opened inside the
  agent with `sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>` appear in the `SASE CONTEXT`
  `WORKSPACES` lane and the `t` tmux chooser. In that command, `-p/--project` names the configured linked repo's backing
  project record.
- **Named-agent handoffs** - `%name` gives a producer a stable identity, and `%wait` starts consumers only after
  dependencies complete. A producer can publish small non-secret strings with `sase var set KEY=VALUE` before it exits;
  waited consumers load those values at startup as Jinja namespaces for prompt or workflow rendering, and ACE shows them
  in the producer's `OUTPUT VARIABLES` metadata panel.
- **Per-launch model routing** - `%model(opus, coder=codex/gpt-5.6-sol)` selects the current agent's model and gives its
  SASE-created plan/coder lineage a temporary `coder` alias. SASE records the map in agent metadata and passes it to
  plan/coder follow-ups and explicit `%name(parent, suffix)` attachments; an ordinary nested launch starts without it.
  The directive does not change `sase.yml` or machine-wide temporary overrides.
- **SDD storage** - Workspace providers own where prompt snapshots, tales, epics, research notes, and beads live.
  Built-in bare-git projects use in-tree `sdd/`. Newly initialized managed GitHub projects use an auto-cloned
  `<repo>--plans` companion for plans and beads plus a separate `<repo>--research` companion. Initialization prepares
  both in the current workspace; later workspaces clone research on demand. Unmigrated projects keep their legacy
  `.sase/sdd/` clone. A positive `.sase/sdd-store.json` record keeps the resolved layout usable offline. The retired
  `sdd.storage` and `sdd.version_controlled` selectors are ignored and reported by `sase doctor` for cleanup.
- **Plan approval pipeline** - Planning agents submit Markdown plans with `sase plan propose`. ACE, notifications, and
  `sase plan` all read the same pending approval state; `sase plan approve [id] -k <kind>` and `sase plan reject [id]`
  write the same response protocol as the TUI. Approval kinds decide whether the runner starts a coder without
  committing an SDD plan, commits the plan as a tale/epic before the follow-up, or records the approved plan in SDD and
  stops there. A no-feedback rejection writes the response first, then attempts to kill and dismiss the matching planner
  row when it can be found. Custom agent-family members defined in `kind: agent_family` YAML can be toggled per approval
  (TUI digit toggles or `sase plan approve --with/--without`) with sticky per-project defaults, and launches requested
  by running agents are gated behind `LaunchApproval` requests resolved in ACE or with `sase launch approve/reject`.
- **Commit finalization** - After a successful provider invocation inside a SASE-launched agent session, the
  provider-neutral finalizer checks the main workspace and configured Git linked-repo workspaces. Dirty linked clones
  are enforced like the main workspace. If the only enforced change is one tracked SDD markdown file under `sdd/plans/`
  whose leading front matter changes exactly from `status: wip` to `status: done`, SASE commits that closeout directly.
  Other dirty enforced workspaces trigger bounded follow-up invocations that tell the same agent to use the configured
  commit skill; if enforced workspaces are still dirty after the configured pass limit, the agent run fails with a clear
  artifact trail.
- **Durable artifacts** - Agent metadata, chats, notifications, prompt history, dismissed-agent bundles, saved agent
  groups, ChangeSpecs, SDD files, and beads are stored in predictable project/user directories so ACE, AXE, CLI
  commands, and external integrations can share state. Long-term memory reads and write proposals are also
  project-scoped and audited so agents can discover context without silently changing canonical memory files. ACE uses a
  persistent artifact index for its normal Agents-tab "visible inbox" - active plus recent completed, non-hidden rows -
  so startup does not scan all history. Use `sase agent index status` for a lightweight health check, `verify` to
  compare the index with source artifacts, and `gc` to rebuild the index and dismissed projection.

## Keep reading

The full documentation lives at **[sase.sh](https://sase.sh/)**. Start with:

- [ACE TUI](https://sase.sh/ace/) ([local](docs/ace.md))
- [Initialization](https://sase.sh/init/) ([local](docs/init.md))
- [Agent Providers](https://sase.sh/agent_providers/) ([local](docs/agent_providers.md))
- [Memory](https://sase.sh/memory/) ([local](docs/memory.md))
- [AXE Automation](https://sase.sh/axe/) ([local](docs/axe.md))
- [Spec-Driven Development](https://sase.sh/sdd/) ([local](docs/sdd.md))
- [SDD Storage](https://sase.sh/sdd_storage/) ([local](docs/sdd_storage.md))
- [XPrompts](https://sase.sh/xprompt/) ([local](docs/xprompt.md))
- [Prompt History](https://sase.sh/prompt/) ([local](docs/prompt.md))
- [ChangeSpecs](https://sase.sh/change_spec/) ([local](docs/change_spec.md))
- [ProjectSpec and project lifecycle](https://sase.sh/project_spec/) ([local](docs/project_spec.md))
- [Beads](https://sase.sh/beads/) ([local](docs/beads.md))
- [Workflows](https://sase.sh/workflow_spec/) ([local](docs/workflow_spec.md))
- [Agent Families](https://sase.sh/agent_families/) ([local](docs/agent_families.md))
- [Workspaces](https://sase.sh/workspace/) ([local](docs/workspace.md))
- [Mentors](https://sase.sh/mentors/) ([local](docs/mentors.md))
- [Commit Workflows](https://sase.sh/commit_workflows/) ([local](docs/commit_workflows.md))
- [Plugins](https://sase.sh/plugins/) ([local](docs/plugins.md))
- [Fakey Testing Provider](https://sase.sh/fakey/) ([local](docs/fakey.md))
- [LLM Providers](https://sase.sh/llms/) ([local](docs/llms.md))
- [VCS Providers](https://sase.sh/vcs/) ([local](docs/vcs.md))
- [Integration APIs](https://sase.sh/integrations/) ([local](docs/integrations.md))
- [Notifications](https://sase.sh/notifications/) ([local](docs/notifications.md))
- [Editor Integration](https://sase.sh/editor/) ([local](docs/editor.md))
- [Agent Attachments](https://sase.sh/agent_images/) ([local](docs/agent_images.md))
- [Mobile Gateway](https://sase.sh/mobile_gateway/) ([local](docs/mobile_gateway.md))
- [Mobile MVP Runbook](https://sase.sh/mobile_mvp_runbook/) ([local](docs/mobile_mvp_runbook.md))
- [Performance Runbook](https://sase.sh/perf_runbook/) ([local](docs/perf_runbook.md))
- [Telemetry](https://sase.sh/telemetry/) ([local](docs/telemetry.md))
- [Agent Revival Log](https://sase.sh/troubleshooting/agent-revival/) ([local](docs/troubleshooting/agent-revival.md))
- [Rust Backend](https://sase.sh/rust_backend/) ([local](docs/rust_backend.md))
- [CLI Reference](https://sase.sh/cli/) ([local](docs/cli.md))
- [Configuration](https://sase.sh/configuration/) ([local](docs/configuration.md))
- [Query Language](https://sase.sh/query_language/) ([local](docs/query_language.md))
- [Architecture](https://sase.sh/architecture/) ([local](docs/architecture.md))
- [Development](https://sase.sh/development/) ([local](docs/development.md))

The `docs/` directory is a MkDocs Material site configured by [mkdocs.yml](mkdocs.yml). Run `just docs-check` for the
strict docs build and `just docs-pdf-check` for the handbook PDF validation.

## Development

### Install from source

Requirements:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

```bash
git clone https://github.com/sase-org/sase
cd sase
uv venv .venv
source .venv/bin/activate
just install
sase core health
sase ace
```

`just install` installs SASE in editable mode with development dependencies. When a sibling `../sase-core` checkout is
present and `cargo` is available, it also builds and installs the local `sase_core_rs` extension.

### Verification

```bash
just install       # Install with dev deps
just fmt           # Auto-format code
just lint          # Run ruff, mypy, pyscripts, symvision, toobig, and keep-sorted
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

## License

sase is licensed under the MIT License. See [LICENSE](LICENSE).
