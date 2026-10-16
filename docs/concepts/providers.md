---
title: Providers and models
description: How SASE connects agent work to coding-agent providers and models.
search:
  boost: 2
---

# Providers and models

A provider is the coding-agent CLI that runs the model behind an agent turn.

## The idea in one picture

```text
Task and workspace ──► SASE ──► Provider CLI ──► Model
                         ▲
                    size alias
```

The diagram shows SASE routing a task to a provider and model, which a size alias can
help select.

## How it works

SASE starts supported provider CLIs through a common agent workflow. The provider
connects the task to a model and its own authentication system; SASE keeps track of the
work around that invocation.

You can select a provider and model directly, or use a size alias such as `@large` when
a prompt needs a general capability level rather than a specific model name. SASE
resolves the alias to an available provider and model, so reusable prompts can describe
the work without being tied to one vendor's catalog.

## When it matters

- Use a size alias when a task should stay portable across provider choices.
- Choose a provider and model directly when the task depends on a particular capability
  or account.
- Check provider readiness before launching work that depends on its CLI.

## Do it

- [Get started with SASE](../getting_started.md) — check provider readiness and launch a
  first agent.

## Look it up

- [Agent providers](../agent_providers.md) — install and authenticate supported
  providers.
- [LLM providers](../llms.md) — model selection and provider behavior.
- [Glossary](../reference/glossary.md#llm-calls) — provider and model terms.
- [Design decisions](../reference/design-decisions.md#size-alias-effort-ladder) — how
  size aliases route work across providers.
