---
title: Memory and agent instructions
description: How shared instructions and durable context guide agents across tasks.
search:
  boost: 2
---

# Memory and agent instructions

Agent instructions set shared working rules, and SASE memory holds context those
instructions and agents can reuse.

## The idea in one picture

```text
Shared instructions and memory ──► Agent turn ◄── Task prompt
          project or home                         this task
```

The diagram separates enduring context from the prompt for the current task.

## How it works

An instruction file states rules that should outlast one prompt. Memory stores durable
context that agents can share across turns, such as project conventions or reusable
reference notes. Some memory is loaded as instruction context; reference material can be
consulted when a task needs it.

The task prompt then says what the agent should work on now. Keeping shared expectations
in instructions and memory, and the immediate goal in the prompt, avoids rewriting the
same context for every task.

## When it matters

- Put stable project expectations in shared instructions so each agent starts with the
  same boundaries.
- Keep reusable knowledge in memory when it should remain available beyond one
  conversation.
- Use the prompt for the work that is specific to this turn.

## Do it

- [Get started with SASE](../start/index.md) — launch a first agent and see the shared
  context in use.

## Look it up

- [Memory](../reference/memory/memory.md) — memory types and how to inspect them.
- [Instruction bundles](../reference/memory/instruction-bundles.md) — how instructions
  are assembled and delivered.
- [Glossary](../reference/glossary.md#agent-instruction-file) — agent instructions, core
  memory, and reference memory.
- [Design decisions](../reference/design-decisions.md#instructions-per-invocation) — why
  provider adapters deliver instructions per invocation.
