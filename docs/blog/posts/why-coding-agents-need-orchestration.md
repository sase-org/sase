---
title: "[00] Why Coding Agents Need Orchestration"
date: 2026-05-08
description:
  Why coding-agent work needs durable orchestration around planning, state, review, dependencies, retries, and handoff.
categories:
  - Agentic Software Engineering
slug: why-coding-agents-need-orchestration
links:
  - SASE Blog Series: series/agentic-software-engineering.md
  - Start with ACE: ace.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [00] Why Coding Agents Need Orchestration

Coding agents are strongest when they operate inside a workflow that can preserve intent, track state, and recover from
interruptions. The model can produce a patch, but the surrounding engineering system has to remember what the work was
for, where the change lives, what it depends on, how it should be reviewed, and what happens if the run stops halfway
through.

<!-- more -->

SASE calls that surrounding system **structured agentic software engineering**: software work where agents operate
inside durable plans, work queues, review records, tests, commits, dependencies, and handoffs instead of only inside a
chat transcript.

## The Single-Agent Happy Path Is Too Small

A one-off coding-agent prompt works well when the task is small, the repository is already checked out, and the result
can be reviewed immediately. That path starts to break down when the work has any of these properties:

- The task needs planning before implementation.
- Multiple changes have real dependencies.
- A reviewer needs to understand why an agent made a change.
- A failed run needs to be retried without losing the useful workspace state.
- A later agent needs to continue from an earlier agent's output.
- The workflow should work across local git, GitHub, or another provider.

Those are not model-quality problems. They are state-management problems.

## Durable Intent Beats Chat History

Agent plans are ephemeral by default. They live in a session context window and are easy to lose, summarize badly, or
detach from the code that eventually lands. SASE's [Spec-Driven Development](../../sdd.md) flow writes the expanded
prompt and the approved plan to disk as first-class artifacts. Ordinary plans live as tales, executable multi-phase
plans live as epics, and longer coordination plans live as legends.

That gives future agents and humans a stable reference point:

```bash
sase sdd list --kind epics
sase sdd validate
```

The point is not paperwork. The point is that a plan can become an artifact with a path, frontmatter, history, and links
to the work that executed it.

## Work Needs Dependencies, Not Just Prompts

Once work is split across agents, ordering matters. Some tasks can run in parallel; others need a previous phase to
finish first. SASE uses [Beads](../../beads.md) as git-portable, issue-like work units for that coordination.

A bead can represent a plan, an executable epic, or a phase inside an epic. Phase beads can depend on other phase beads,
so `sase bead ready` can show only work whose blockers are closed:

```bash
sase bead ready
sase bead show <bead-id>
```

For an epic-tier plan, `sase bead work <epic-id>` builds a dependency schedule from open phase beads, pre-claims the
phases, launches one agent per phase, and then launches a final land agent after the phase agents complete. That is a
different control shape from "ask one model to do everything"; it lets the workflow preserve dependency ordering while
still using parallelism where the plan allows it.

## Review State Has To Survive The Run

Real code review needs more than an agent's final message. SASE's [ChangeSpec](../../change_spec.md) format records
CL/PR-sized work with fields for the name, description, parent relationship, review identifier, status, commits, hooks,
comments, mentors, and deltas. ACE, the terminal UI, uses those records as the main object of navigation.

That separation matters because the review state stays outside the chat transcript. An operator can inspect a
ChangeSpec, open the diff, run a follow-up agent, review mentor comments, or mail/submit the change through the
workspace provider that matches the project.

## Supervision Belongs Outside The Agent

Agents are not the right place to poll for background state forever. SASE's [Axe daemon](../../axe.md) runs lifecycle
jobs such as hook completion, mentor launch, workflow cleanup, comment polling, `%wait` dependency checks, and error
digests. The [ACE TUI](../../ace.md) starts Axe by default and gives operators one place to inspect ChangeSpecs, live
agents, notifications, and automation state:

```bash
sase ace
sase axe lumberjack status
```

This keeps long-running supervision in the orchestration layer. The agent can focus on the current engineering task,
while the daemon handles recurring checks and dependency unblocking.

## Provider CLIs Are Tools, Not The System

Coding-agent CLIs and hosted model APIs are valuable execution engines, but they should not own every part of the
engineering workflow. SASE puts a provider-independent layer above them:

- [XPrompts](../../xprompt.md) package reusable prompt fragments, standalone workflows, typed inputs, and multi-agent
  fan-out.
- [Workflow specs](../../workflow_spec.md) define repeatable multi-step pipelines with agent, bash, Python, prompt-part,
  parallel, and approval steps.
- [Workspace providers](../../workspace.md) resolve references such as `#cd:<path>`, `#git:<ref>`, or GitHub-backed refs
  into project workspaces and review operations.

The goal is portability. The durable objects are plans, beads, ChangeSpecs, workflow definitions, and workspace
references. Individual model providers and VCS hosts remain replaceable parts of the execution path.

## What Orchestration Buys

Orchestration is useful when it turns agent output into normal engineering work:

- A plan has a path and a history.
- A task has dependencies and a status.
- A change has review metadata and commits.
- A retry can see what already happened.
- A handoff can point to artifacts instead of asking someone to reconstruct context from chat.

That is the practical reason coding agents need orchestration. The model can write code, but the system around the model
has to make the work durable, reviewable, resumable, and transferable.

## Series Navigation

This is [00] in the [SASE Blog Series](../../series/agentic-software-engineering.md).

- Previous: none.
- Next: [\[01\] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents](hello-sase-your-first-15-minutes.md).
- Continue reading: [SASE Blog Series](../../series/agentic-software-engineering.md), [blog home](../index.md), or
  [ACE guide](../../ace.md).
