---
title: Agents, sessions, and workspaces
description:
  How SASE gives delegated agent work an isolated place to run and a durable history.
search:
  boost: 2
---

# Agents, sessions, and workspaces

Agents do delegated work in project workspaces, while sessions keep related turns
together when work needs to continue.

## The idea in one picture

```text
Prompt or macro ──► Agent ── works in ──► Workspace
                       │
                       └── results and progress ──► TUI
```

## How it works

A stand-alone agent performs one turn; a session groups related turns into a sequential
chain, so later work can continue from earlier work rather than starting as an unrelated
task.

A workspace is an isolated checkout of a project. SASE assigns each running agent its
own workspace, which lets agents work in parallel without sharing the same working
files. Their prompts, output, status, and produced files remain available after a turn
ends.

The TUI presents active and completed agents alongside their work records. It gives a
person a place to follow progress, inspect results, and decide what should happen next.

## When it matters

- Use separate workspaces when agents need to change the same project at the same time.
- Use a session when related turns need to build on one another.
- Return to the TUI when you need to find an agent's progress or review what it
  produced.

## Do it

- [Get started with SASE](../start/index.md) — run and inspect a first agent task.
- [Recover an interrupted agent](../guides/recover-interrupted-agent.md) — restart,
  resume, or revive a broken run.
- [Unstick a queued agent](../guides/unstick-queued-agent.md) — clear capacity waits and
  holds.

## Look it up

- [Agent sessions](../agent_sessions.md) — session and grouping details.
- [Workspaces](../workspace.md) — workspace behavior and provider ownership.
