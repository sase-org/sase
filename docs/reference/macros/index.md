---
title: Macro Template Reference
description: Reference pages for macro syntax, directives, fields, and workflows.
---

# Macro Template Reference


Macros are reusable prompt templates with optional typed inputs and Jinja2 support. They
let you define a prompt fragment once and reference it by name anywhere a prompt is
composed, keeping prompts DRY and consistent across projects. Inline prompt fragments
use `#name`; standalone workflows use `#!name` when they are launched as workflows.

Use macros when you want to:

- Share common instructions across multiple prompts (e.g., output format rules, role
  definitions).
- Parameterize prompts with typed, validated arguments.
- Compose prompts from smaller building blocks using `#name(args)` syntax.

For steps to turn a useful one-off prompt into a reusable macro, see
[Reuse a prompt with macros](../../guides/reuse-prompt-with-macros.md). This page documents
macro syntax, inputs, and expansion behavior.

![SASE macro inputs flowing through workspace dispatch, first-wins discovery, iterative expansion, and directive
extraction into runtime outcomes](../../images/macro-resolution-infographic.png)

There are two related paths to keep separate:

```text
launch setup:
  project tag validation and expansion (+sase -> #gh:gh_sase-org__sase)
  -> macro swarm fan-out check
  -> default workspace ref insertion when needed (#git:home)
  -> project name/alias canonicalization (#gh:bob -> #gh_bbugyi200__bob)
  -> workspace ref resolution (#git/#gh, plugin-provided refs, and known-project fallbacks)
  -> prompt/workflow execution

macro expansion inside a prompt or prompt_part:
  alias substitution
  -> fenced-block and disabled-region protection
  -> iterative reference expansion (parse -> lookup -> args -> render -> substitute)
  -> directive extraction at the launch or workflow-step boundary
```

The checked-in infographic prompt in
`docs/images/macro-resolution-infographic.prompt.md` tracks the intended visual version
of this model; the text model above is the authoritative current reference for resolver
order.

## Syntax and sources

- [File format and reference syntax](reference-syntax.md) — macro files, references,
  workspace targets, and project tags
- [Arguments and typed inputs](arguments.md) — argument forms, types, defaults, and
  output validation
- [Template rendering](templating.md) — Jinja2, placeholders, aliases, and expansion
- [Tags](tags.md) — available tags and lookup behavior
- [Fields](fields.md) — snippet, skill, and memory fields
- [Built-in and configured macros](built-ins.md) — definitions from SASE and config
- [Discovery](discovery.md) — lookup order and reserved namespaces

## Directives

- [Generated directive catalog](directives.md) — directive names, aliases, syntax, and
  arguments
- [Syntax and completion](directive-syntax.md) — directive forms and model or dispatch
- [Launch directives](directive-launch.md) — identity, launch settings, and admission
- [Composition and fan-out](directive-composition.md) — review, repetition, and branches

## Tools and workflows

- [Macro CLI and editor support](cli-and-editor.md)
- [Multi-agent prompts](multi-agent-prompts.md)
- [Workflow specification](../workflows.md)
- [Troubleshooting](troubleshooting.md)

## Related

- [Reuse a prompt with macros](../../guides/reuse-prompt-with-macros.md)
