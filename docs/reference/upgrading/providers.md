---
title: Provider migration notes
description: Historical compatibility notes for provider metadata and model selection.
---

# Provider migration notes

This page records provider compatibility changes that affect older projects or runs.

## Legacy Thinking Metadata

Older parser helpers can still read provider thinking/reasoning artifacts when a caller
uses them directly. For Claude extended-thinking events whose `thinking` text is empty
but whose payload contains an opaque `signature`, those helpers produce an
encrypted-thinking placeholder instead of hiding the block. When Claude also reports
`message.usage.output_tokens`, the placeholder includes an approximate output-token
count so the caller can tell that reasoning occurred even though the raw thought text is
not available. The Agents tab now uses the LLM Calls panel for provider tool activity
instead of exposing these thinking helpers as a panel.

## Model aliases

Older configs may contain model keys or aliases that are not registered now. Replace
`llm_provider.worker_models` and `@worker` with a direct size alias (`@xsmall`,
`@small`, `@medium`, `@large`, or `@xlarge`) or an explicit model. Use
`llm_provider.default_model` instead of `@other`.

The `phase_worker` bucket and `<size>_phase_worker` aliases, `@coder` and
`@<provider>_coder`, implicit role aliases (`@default`, `@epic_lander`,
`@big_epic_lander`), `<size>_worker` aliases, and capability/cost aliases (`@smart`,
`@smarter`, `@smartest`, `@cheap`, `@cheaper`, `@cheapest`) have no built-in behavior.
Use the direct size aliases with `epic_lander_model` and `big_epic_lander_model` for
those explicit routes. Custom aliases can use these names, but they do not receive
special handling. Run `sase doctor -C config.model_aliases` to find removed keys or
aliases still present in a config.

## Related

- [Providers and models](../providers/index.md) — current provider behavior.
- [Models and aliases](../providers/models.md) — current model selection.
