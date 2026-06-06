---
title: "[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents"
date: 2026-05-10
description: >-
  A hands-on tour: install SASE, launch your first agent run, find the resulting ChangeSpec in ACE, and pick up the
  vocabulary you'll keep bumping into — in about 15 minutes.
categories:
  - Agentic Software Engineering
  - Getting Started
slug: hello-sase-your-first-15-minutes
links:
  - SASE Blog Series: series/agentic-software-engineering.md
  - "[00] Why Coding Agents Need Orchestration": blog/posts/why-coding-agents-need-orchestration.md
  - ACE TUI: ace.md
  - Spec-Driven Development: sdd.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents

SASE (pronounced "sassy" — yes, really) is a coordination layer that sits above coding-agent CLIs like Claude Code,
Codex, or Gemini. This post is the practical on-ramp: by the end you'll have installed `sase`, launched an agent, found
the resulting ChangeSpec in ACE, and picked up the vocabulary you'll keep bumping into in the rest of the docs. Plan on
roughly fifteen minutes at a terminal, plus however long your favorite model takes to think.

<!-- more -->

This is [01] in the SASE Blog Series. If you'd rather read about _why_ a system like this exists before touching it,
[\[00\] Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md) makes that argument. The two
posts can be read in either order; this one runs first and names the parts afterward.

## Step 1 — Install (≈90 seconds)

SASE needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and [`just`](https://github.com/casey/just). With those in
place:

```bash
uv venv .venv
source .venv/bin/activate
just install
sase --help
```

If `sase --help` prints a wall of subcommands, you're in. The first install can stretch past 90 seconds when `uv` has to
fetch wheels — that's normal, not a hang. The `just install` step pulls in the Python CLI plus the Rust core extension
(`sase_core_rs`) that some of the hot paths call into. If anything looks off, `sase core health` is the canonical sanity
check and the [development guide](../../development.md) covers the usual fix-ups.

**What you just did.** Dropped the `sase` CLI and its Rust core extension into an editable virtualenv.

## Step 2 — Launch your first agent (≈3 minutes, plus model time)

Pick a tiny, safe task — anything that produces a visible diff without needing the network. A docstring is a friendly
first choice; the exact wording doesn't matter, so use whatever feels natural:

```bash
sase run "add a one-line docstring to the most recently edited Python function in this repo"
```

`sase run` doesn't touch your working tree. It allocates an isolated **workspace** — a sibling clone of the repo named
`sase_<N>` — and runs the agent in there. That isolation is what lets you fire off several agents at once without them
elbowing each other, and what lets a failed run be retried without scorching your real checkout.

The launched agent gets its own durable record on disk: prompt, reply transcript, artifacts directory, status. You'll
poke at it in the next step. (If the run takes longer than you expected, that's the model thinking, not SASE napping.)

**What you just did.** Dispatched a coding-agent run inside an ephemeral [workspace](../../workspace.md), tracked as a
SASE agent record with its own artifacts directory. The full [CLI reference](../../cli.md) lists every flag you'll ever
want.

## Step 3 — Open ACE and find the result (≈3 minutes)

ACE is the TUI control surface. Open it:

```bash
sase ace
```

ACE has three tabs:

- **CLs** — every ChangeSpec on this project. Your agent's commit should be sitting here as a new ChangeSpec, complete
  with a name, status, commits drawer, and diff. A **ChangeSpec** is SASE's durable record of one CL/PR-sized unit of
  work; think of it as the long-lived sibling of a pull request that holds the description, parent, status (WIP → Draft
  → Ready → Mailed → Submitted), commits, hooks, comments, and mentor activity all in one place. The
  [ChangeSpec guide](../../change_spec.md) goes deeper when you're curious.
- **Agents** — live and recent agent records. Find the run you just launched: prompt, reply transcript, workspace path,
  status, retry chain.
- **Axe** — the background daemon's view: scheduled jobs, hooks waiting to complete, mentor launches, error digests. ACE
  auto-starts AXE the first time it opens, so this tab is already ticking before you click it.

![ACE TUI tabs](../../images/sase_tui_tabs_infographic.png)

**What you just did.** Observed one `sase run` produce a durable [ChangeSpec](../../change_spec.md) and a persistent
agent artifact, both visible in [ACE](../../ace.md), with [AXE](../../axe.md) handling lifecycle work in the background.

## Step 4 — Reuse the prompt as an XPrompt (≈3 minutes)

A one-off prompt is fine once. The second time you find yourself reaching for it, wrap it as an **XPrompt** so you're
not retyping the same paragraph forever. Create `xprompts/docstring.md` in your project root:

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

When a task is too big to hand to a single agent and hope, SASE asks you to write a plan first. **Spec-Driven
Development (SDD)** keeps those plans as first-class artifacts on disk under three (admittedly whimsical) names:
ordinary plans are _tales_, executable multi-phase plans are _epics_, and longer cross-cutting plans are _legends_. Any
of them can be filed as a **bead** — a git-portable, issue-like work unit with status, dependencies, and an assignee.

The smallest useful loop:

```bash
sase bead onboard         # walks through the issue-tracking quick start
sase bead ready           # lists work whose blockers are closed
sase bead show <bead-id>  # inspects one bead in detail
```

Once an epic plan exists and its phase beads are filed, `sase bead work <epic-id>` builds a dependency schedule from the
open phases, pre-claims each phase bead, launches one agent per phase in the right order, and runs a final land agent
after the phases finish. That's the on-ramp from one-shot prompts to multi-agent execution with actual ordering — no
more babysitting `sase run` calls in a shell loop.

**What you just did.** Stepped from one-shot prompts into [Spec-Driven Development](../../sdd.md) with
[Beads](../../beads.md) as dependency-aware work units.

## The component map (recap)

The names you'll keep bumping into, in one place:

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

- [\[00\] Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md) — the conceptual half of the
  series, for when you want the _why_ to match the _how_.
- [SASE Blog Series](../../series/agentic-software-engineering.md) — all ten posts in one place.
- [CLI reference](../../cli.md) — every `sase` subcommand on one page.
- [The SASE repository](https://github.com/sase-org/sase) — source, issues, and project direction. If something on this
  page didn't work, an issue is the fastest way to make the next reader's first 15 minutes smoother.

## Series Navigation

This is [01] in the [SASE Blog Series](../../series/agentic-software-engineering.md).

- Previous: [\[00\] Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md).
- Next: [\[02\] XPrompts in Depth — From One File to Full Workflows](xprompts-in-depth.md).
- Continue reading: [SASE Blog Series](../../series/agentic-software-engineering.md), [blog home](../index.md), or
  [ACE guide](../../ace.md).
