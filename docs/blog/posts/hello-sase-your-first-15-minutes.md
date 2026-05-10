---
date: 2026-05-10
description: >-
  A hands-on tour: install SASE, launch your first agent run, find the resulting ChangeSpec in ACE, and learn the
  vocabulary of every major SASE component in about 15 minutes.
categories:
  - Agentic Software Engineering
  - Getting Started
slug: hello-sase-your-first-15-minutes
links:
  - Agentic Software Engineering Series: series/agentic-software-engineering.md
  - Why Coding Agents Need Orchestration: blog/posts/why-coding-agents-need-orchestration.md
  - ACE TUI: ace.md
  - Spec-Driven Development: sdd.md
  - View on GitHub: https://github.com/sase-org/sase
---

# Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents

SASE is a coordination layer above coding-agent CLIs. This post is the practical on-ramp: by the end you will have
installed `sase`, launched an agent, found the resulting ChangeSpec in ACE, and learned the names of every major
component so the rest of the docs read in context. Plan on about fifteen minutes at a terminal.

<!-- more -->

If you would rather read about _why_ this shape of system exists before touching it, the companion essay
[Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md) makes the argument. This post does the
opposite: it shows the system running, then names the parts.

## Step 1 — Install (≈90 seconds)

SASE needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and [`just`](https://github.com/casey/just). With those in
place:

```bash
uv venv .venv
source .venv/bin/activate
just install
sase --help
```

If `sase --help` prints the command list, you are done. The `just install` step installs the Python CLI plus the
required `sase_core_rs` Rust extension that backs ported core operations — `sase core health` is the canonical install
check if anything looks wrong, and the [development guide](../../development.md) covers troubleshooting.

**What you just did.** Installed the `sase` CLI and its Rust core extension into an editable virtualenv.

## Step 2 — Launch your first agent (≈3 minutes)

Pick a small, safe task that produces a visible diff without external dependencies. A docstring is a good first task:

```bash
sase run "add a one-line docstring to the most recently edited Python function in this repo"
```

`sase run` does not edit your working tree directly. It allocates an isolated **workspace** — a sibling clone of the
repo named `sase_<N>` — and runs the agent there. That isolation is what lets multiple agents work in parallel without
stepping on each other, and what lets a failed run be retried without losing the state of your real checkout.

The launched agent gets its own durable record on disk: prompt, reply transcript, artifacts directory, status. You will
find it in the next step.

**What you just did.** Dispatched a coding-agent run inside an ephemeral [workspace](../../workspace.md), tracked as a
SASE agent record with its own artifacts directory. The full [CLI reference](../../cli.md) lists every flag.

## Step 3 — Open ACE and find the result (≈3 minutes)

ACE is the TUI control surface. Open it:

```bash
sase ace
```

ACE has three tabs:

- **CLs** — every ChangeSpec on this project. Your agent's commit should appear here as a new ChangeSpec with a name,
  status, commits drawer, and diff. A **ChangeSpec** is SASE's durable record of a CL/PR-sized unit of work — name,
  description, parent, review identifier, status lifecycle (WIP → Draft → Ready → Mailed → Submitted), commits, hooks,
  comments, and mentor activity all live on the spec.
- **Agents** — the live and recent agent records. Find the run you just launched: prompt, reply transcript, workspace
  path, status, retry chain.
- **Axe** — the background daemon's view: scheduled jobs, hooks waiting to complete, mentor launches, error digests. ACE
  auto-starts AXE the first time it opens, so this tab is already ticking.

![ACE TUI tabs](../../images/sase_tui_tabs_infographic.png)

**What you just did.** Observed one `sase run` produce a durable [ChangeSpec](../../change_spec.md) and a persistent
agent artifact, both visible in [ACE](../../ace.md), with [AXE](../../axe.md) handling lifecycle work in the background.

## Step 4 — Reuse the prompt as an XPrompt (≈3 minutes)

A one-off prompt is fine once. The second time you want it, wrap it as an **XPrompt**. Create `xprompts/docstring.md` in
your project root:

```markdown
Add a one-line docstring to the most recently edited Python function in this repo. Keep the wording terse; do not change
behavior.
```

Now the same agent run is one tag:

```bash
sase run "#docstring"
```

That is the smallest XPrompt shape — a single Markdown file becomes a reusable prompt part. XPrompts also support YAML
files with typed inputs, multi-step workflows (prompt parts, Python, bash, parallel fan-out, approvals), and `---`
separators for multi-agent dispatch. The [XPrompts guide](../../xprompt.md) covers the full surface, and the
[workflow spec reference](../../workflow_spec.md) documents the YAML form.

**What you just did.** Turned a one-off prompt into a reusable XPrompt, the smallest unit of repeatable agent work in
SASE.

## Step 5 — Plan bigger work with SDD and Beads (≈3 minutes)

When a task is too big for one run, SASE asks you to write a plan first. **Spec-Driven Development (SDD)** stores plans
as first-class artifacts on disk: ordinary plans live as _tales_, executable multi-phase plans live as _epics_, and
longer cross-cutting plans live as _legends_. Each can be filed as a **bead** — a git-portable, issue-like work unit
that records status, dependencies, and assignee.

The smallest useful loop:

```bash
sase bead onboard         # walks through the issue-tracking quick start
sase bead ready           # lists work whose blockers are closed
sase bead show <bead-id>  # inspects one bead in detail
```

Once an epic plan exists and its phase beads are filed, `sase bead work <epic-id>` builds a dependency schedule from the
open phases, pre-claims each phase bead, launches one agent per phase in the right order, and runs a final land agent
after the phases finish. That is the path from one-shot prompts into multi-agent execution with real ordering.

**What you just did.** Stepped from one-shot prompts into [Spec-Driven Development](../../sdd.md) with
[Beads](../../beads.md) as dependency-aware work units.

## The component map (recap)

Every SASE component you should know by name after this post:

- **[ACE](../../ace.md)** — the TUI control surface for ChangeSpecs, agents, notifications, and automation.
- **[AXE](../../axe.md)** — the background automation daemon. Runs hooks, mentor launches, comment polling, dependency
  unblocking, error digests.
- **`sase run`** — the entry point that launches an agent or workflow. See the [CLI reference](../../cli.md).
- **[Workspaces](../../workspace.md)** — isolated `sase_<N>` clones of the repo so agents can work in parallel without
  touching your checkout.
- **[ChangeSpecs](../../change_spec.md)** — durable CL/PR-sized review records: status lifecycle, commits, hooks,
  comments, mentors.
- **[Beads](../../beads.md)** — dependency-aware, git-portable work units. Powers epic execution.
- **[XPrompts](../../xprompt.md)** — reusable prompt templates and YAML workflows with typed inputs and multi-agent
  fan-out. See also [workflow specs](../../workflow_spec.md).
- **[SDD](../../sdd.md)** — Spec-Driven Development. Plans, epics, and legends as first-class artifacts on disk.
- **[Plugins and providers](../../plugins.md)** — model and VCS providers behind a common boundary: Claude Code, Gemini
  CLI, Codex, Qwen Code, OpenCode for agents; bare git and GitHub for version control.

## What to read next

- [Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md) — the conceptual companion to this
  post.
- [Agentic Software Engineering series hub](../../series/agentic-software-engineering.md) — the launch arc, with linked
  guides for each planned essay.
- [CLI reference](../../cli.md) — every `sase` subcommand in one page.
- [The SASE repository](https://github.com/sase-org/sase) — source, issues, and project direction.

## Series Navigation

This is a hands-on companion to the [Agentic Software Engineering series](../../series/agentic-software-engineering.md).
Read the [launch essay](why-coding-agents-need-orchestration.md) next for the motivation behind the system you just ran.
