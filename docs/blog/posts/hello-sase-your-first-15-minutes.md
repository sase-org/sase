---
title: "[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents"
date: 2026-05-10
draft: true
description: >-
  A hands-on tour: install SASE, check provider readiness, launch a safe first agent
  run, find the agent record, and pick up the vocabulary you'll keep bumping into — in
  about 15 minutes.
categories:
  - Agentic Software Engineering
  - Getting Started
slug: hello-sase-your-first-15-minutes
links:
  - "SASE: Structured Agentic Software Engineering": blog/posts/structured-agentic-software-engineering.md
  - ACE TUI: ace.md
  - Spec-Driven Development: sdd.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents

SASE (pronounced "sassy" — yes, really) is a coordination layer that sits above
coding-agent CLIs like Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code, OpenCode,
or Meta's Muse Code. This post is the practical on-ramp: by the end you'll have
installed `sase`, checked that a provider CLI is ready, launched a safe read-only agent
run, found the resulting agent record, and picked up the vocabulary you'll keep bumping
into in the rest of the docs. Plan on roughly fifteen minutes at a terminal, plus
however long your favorite model takes to think.

<!-- more -->

If you'd rather read about _why_ a system like this exists before touching it,
[SASE: Structured Agentic Software Engineering](structured-agentic-software-engineering.md)
makes that argument. The two pages can be read in either order; this one runs first and
names the parts afterward.

## Step 1 — Install SASE (≈90 seconds)

SASE needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and one authenticated
coding-agent CLI such as Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code,
OpenCode, or Meta's Muse Code. With Python and `uv` in place:

```bash
uv tool install sase
sase version
```

If `sase version` prints the SASE package plus the `sase-core-rs` package, the CLI is
installed. The first install can stretch past 90 seconds when `uv` has to fetch wheels —
that's normal, not a hang.

**What you just did.** Installed the public `sase` CLI and its Rust core extension as a
user tool, without cloning the repository or setting up a contributor environment.

## Step 2 — Check provider readiness (≈2 minutes)

SASE orchestrates a supported provider CLI and still relies on the provider's own
authentication flow. Inventory the supported CLIs, then run the read-only doctor before
the first agent launch:

```bash
sase agent-cli
sase doctor
```

If the provider check reports a missing executable or an authentication gap, install and
authenticate one provider CLI, then run `sase doctor` again. Among SASE's built-in
providers, Muse Code is the one SASE can currently install itself: use
`sase agent-cli install muse --dry-run` to inspect the downloaded script's URL, digest,
command, and target, then `sase agent-cli install muse` to confirm and run it. Other
built-in providers use the install commands in the provider guide. The
[agent provider guide](../../agent_providers.md) keeps install, authentication, and
provider/model selection options in one place so this quickstart can stay focused.

**What you just did.** Verified that SASE can find a usable coding-agent provider before
spending time on an agent run.

## Step 3 — Launch a safe first agent (≈3 minutes, plus model time)

Start with a read-only task in SASE's managed `home` project. Use one launch form: the
normal form when SASE can auto-detect an installed provider CLI, or the Muse form when
Muse Code is your provider, because `muse` is explicit-only and never auto-detected:

```bash
# Auto-detected providers:
sase run "#git:home summarize this workspace's layout; do not change files"
# Muse Code:
sase run "%model:muse/muse-spark-1.2 #git:home summarize this workspace's layout; do not change files"
# Then:
sase agent list
```

The `#git:home` prefix targets SASE's built-in `home` sandbox. On first use, SASE
bootstraps that managed project with a bare git repository, a primary checkout, and
generated SDD scaffolding, then launches the provider CLI in an isolated numbered
workspace managed by SASE. Prompts with no workspace reference are normalized to
`#git:home` automatically, so the bare form
`sase run "summarize this workspace's layout; do not change files"` is equivalent. That
isolation is what lets you fire off several agents at once without them colliding, and
what lets a failed run be retried without touching your primary checkout.

The launched agent gets its own durable record on disk: prompt, reply transcript,
artifacts directory, status, and workspace path. `sase agent list` gives you the first
visible handle for that record while the model is thinking or after it finishes.

**What you just did.** Dispatched a read-only coding-agent run inside an explicit
[workspace](../../workspace.md), then looked up the resulting SASE agent record.

## Step 4 — Open ACE and find the result (≈3 minutes)

ACE is the TUI control surface. Open it:

```bash
sase ace
```

ACE has three top-level tabs:

- **Agents** — live and recent agent records. Find the run you just launched: prompt,
  reply transcript, workspace path, status, retry chain.
- **Artifacts** — views for stitches, Patches, beads, configured document providers, and
  files. The Patches view contains every Patch on the project. A **Patch** is SASE's
  durable record of one PR-sized unit of work; think of it as the long-lived sibling of
  a pull request that holds the description, parent, status (WIP → Draft → Ready →
  Mailed → Submitted), commits, hooks, comments, and mentor activity all in one place.
  The [Patch guide](../../change_spec.md) goes deeper when you're curious. This first
  read-only run should not have created one yet; editable committed work is where
  Patches appear.
- **Axe** — the background daemon's view: scheduled jobs, hooks waiting to complete,
  mentor launches, error digests. ACE auto-starts AXE the first time it opens, so this
  tab is already ticking before you click it.

**What you just did.** Observed one `sase run` produce a persistent agent artifact
visible in [ACE](../../ace.md), with [AXE](../../axe.md) handling lifecycle work in the
background.

## Step 5 — Try one tiny edit (≈3 minutes, plus model time)

After you have seen the agent record, try a low-risk change:

```bash
sase run "#git:home create or update notes.md with one short note about SASE workspaces"
sase agent list
```

Now the agent has permission to make a visible diff in its isolated numbered workspace.
Your own repositories and the `home` primary checkout stay untouched unless you
explicitly bring changes back. When the agent commits its work, SASE's commit workflow
records a Patch that you can review in ACE's Artifacts tab, under Patches, before
landing or submitting anything.

For your own repositories, use `#git:<name>` to target a managed project or
`#git:<bare-repo-path>` to register an existing bare repository. Provider plugins add
other workspace references, such as `#gh:<owner>/<repo>` for GitHub. The
[workspace guide](../../workspace.md) has the full model.

**What you just did.** Moved from a read-only run to a small editable task after
confirming where SASE records agent state.

## Step 6 — Reuse the prompt as an XPrompt (≈3 minutes)

A one-off prompt is fine once. The second time you find yourself reaching for it, wrap
it as an **XPrompt** so you're not retyping the same paragraph forever. Create
`sase/xprompts/til.md` in the directory where you run `sase`:

```markdown
Append one Today-I-Learned entry to `til.md` about something useful in this workspace.
Keep it to two sentences. If the file does not exist, create it.
```

Now the same agent run is one tag:

```bash
sase run "#til"
```

That is the smallest XPrompt shape — a single Markdown file becomes a reusable prompt
part. Because this prompt has no workspace reference, the same `#git:home` default kicks
in at launch. XPrompts also support YAML files with typed inputs, multi-step workflows
(prompt parts, Python, bash, parallel fan-out, approvals), and `---` separators for
multi-agent dispatch. The [XPrompts guide](../../xprompt.md) covers the full surface,
and the [workflow spec reference](../../workflow_spec.md) documents the YAML form.

**What you just did.** Turned a one-off prompt into a reusable XPrompt, the smallest
unit of repeatable agent work in SASE.

## Step 7 — Plan bigger work with SDD and Beads (≈3 minutes)

When a task is too big to hand to a single agent and hope, SASE asks you to write a plan
first. **Spec-Driven Development (SDD)** keeps those plans as first-class artifacts on
disk under three (admittedly whimsical) names: ordinary plans are _tales_, and
executable multi-phase plans are _epics_. Any of them can be filed as a **bead** — a
git-portable, issue-like work unit with status, dependencies, and an assignee.

The smallest useful loop:

```bash
sase bead onboard         # walks through the issue-tracking quick start
sase bead ready           # lists ready task beads whose blockers are closed
sase bead show <bead-id>  # inspects one bead in detail
```

For a self-contained follow-up that does not need an epic, agents first run
`/sase_new_task`; when it is genuinely new, create a standalone task bead with
`sase bead create --type 'task(bug)' --title "Follow up" --size small -f location=src/foo.py -f repro='fails on retry'`,
move it to `ready` when it is ready for triage, and launch it with
`sase bead work <task-id>`. AXE also turns stored `ready` tasks into notification gates
where a reviewer can launch or close them.

Once an epic plan exists and its phase beads are filed, `sase bead work <epic-id>`
builds a dependency schedule from the open phases, checkpoints their `in_progress`
assignments, launches one agent per phase in the right order, and runs a final land
agent after every phase bead closes. That's the on-ramp from one-shot prompts to
multi-agent execution with actual ordering — no more babysitting `sase run` calls in a
shell loop.

**What you just did.** Stepped from one-shot prompts into
[Spec-Driven Development](../../sdd.md) with [Beads](../../beads.md) as dependency-aware
work units.

## The component map (recap)

The names you'll keep bumping into, in one place:

- **[ACE](../../ace.md)** — the TUI control surface for Patches, agents, notifications,
  and automation.
- **[AXE](../../axe.md)** — the background automation daemon. Runs hooks, mentor
  launches, comment polling, dependency unblocking, error digests.
- **`sase run`** — the entry point that launches an agent or workflow. See the
  [CLI reference](../../cli.md).
- **[Workspaces](../../workspace.md)** — isolated numbered clones managed by SASE so
  agents can work in parallel without touching your primary checkout.
- **[Patches](../../change_spec.md)** — durable PR-sized review records: status
  lifecycle, commits, hooks, comments, mentors.
- **[Beads](../../beads.md)** — dependency-aware, git-portable work units. Powers epic
  execution.
- **[XPrompts](../../xprompt.md)** — reusable prompt templates and YAML workflows with
  typed inputs and multi-agent fan-out. See also
  [workflow specs](../../workflow_spec.md).
- **[SDD](../../sdd.md)** — Spec-Driven Development. Plans and epics as first-class
  artifacts on disk.
- **[Plugins and providers](../../plugins.md)** — model and VCS providers behind a
  common boundary: Claude Code, Antigravity CLI (`agy`), Codex, Qwen Code, OpenCode, and
  Muse Code for agents; bare git and GitHub for version control.

## What to read next

- [SASE: Structured Agentic Software Engineering](structured-agentic-software-engineering.md)
  — the conceptual front door, for when you want the _why_ to match the _how_.
- [CLI reference](../../cli.md) — every `sase` subcommand on one page.
- [The SASE repository](https://github.com/sase-org/sase) — source, issues, and project
  direction. If something on this page didn't work, an issue is the fastest way to make
  the next reader's first 15 minutes smoother.
