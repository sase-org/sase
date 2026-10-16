---
title: Prompts, macros, and workflows
description:
  How one task prompt can grow into reusable instructions and repeatable work.
search:
  boost: 2
---

# Prompts, macros, and workflows

A prompt tells an agent what to do; macros and workflows let you reuse and organize that
direction.

## The idea in one picture

```text
Prompt ──► Agent turn
   ▲
   ├── Macro: reusable prompt content
   └── Workflow: an ordered process around agent work
```

The diagram shows how a direct request can use a macro or become part of a larger
workflow.

## How it works

A prompt gives an agent the task for one turn. A macro names prompt content you can
reuse, and can take inputs to adapt the same instructions to different work. A workflow
groups steps into a repeatable process, combining prompts with actions, branches, or
approval points when the task needs them.

These forms keep the task's purpose visible while avoiding repeated instructions. Use
the smallest form that fits: a direct prompt for one task, a macro for reusable wording,
and a workflow when several steps need to run together.

## When it matters

- Write a direct prompt when the task is specific to this agent turn.
- Reuse a macro when the same direction comes up across tasks.
- Use a workflow when work needs an ordered sequence or a checkpoint.

## Do it

- [Get started with SASE](../getting_started.md) — launch a first agent with a task
  prompt.

## Look it up

- [Macros](../macros.md) — macro syntax, inputs, and expansion behavior.
- [Workflow specification](../workflow_spec.md) — workflow steps and control flow.
- [Glossary](../reference/glossary.md#macro) — macro, invocation, and workflow terms.
