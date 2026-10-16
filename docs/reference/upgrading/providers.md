---
title: Provider migration notes
description:
  Historical compatibility notes for VCS commands, provider metadata, and model
  selection.
---

# Provider migration notes

This page records compatibility changes that affect older projects or runs.

## Commit Timeline

`sase stitch list` presents a day-grouped commit timeline across the primary and linked
repositories. Sidecar history is opt-in with `--sdd`; `--all` also scans registered
projects. Use `-s` / `--since` to filter by date and `-A` / `--author` to filter by
author. `--sort` is not available. `-N` / `--no-fetch` skips fetching remote refs.

## Provider Override Files

Version 1 override files use one flat object with top-level `provider` and `model`
fields. SASE migrates them on read into `overrides.default`; version 2 entries without
`effort` remain valid and are read as `effort: null`.

## Legacy Thinking Metadata

Older parser helpers can still read provider thinking/reasoning artifacts when a caller
uses them directly. For Claude extended-thinking events whose `thinking` text is empty
but whose payload contains an opaque `signature`, those helpers produce an
encrypted-thinking placeholder instead of hiding the block. When Claude also reports
`message.usage.output_tokens`, the placeholder includes an approximate output-token
count so the caller can tell that reasoning occurred even though the raw thought text is
not available. The Agents tab now uses the LLM Calls panel for provider tool activity
instead of exposing these thinking helpers as a panel.

## Model Selection Names

Older configs may contain model keys or aliases that are not registered now. Replace
`llm_provider.worker_models` and `@worker` with a direct size alias (`@xsmall`,
`@small`, `@medium`, `@large`, or `@xlarge`) or an explicit model. Use
`llm_provider.default_model` instead of `@other`.

The `phase_worker` bucket and `<size>_phase_worker` aliases, `@coder`,
`@<provider>_coder`, `@epic_creator`, implicit role aliases (`@default`, `@epic_lander`,
`@big_epic_lander`), `<size>_worker` aliases, and capability/cost aliases (`@smart`,
`@smarter`, `@smartest`, `@cheap`, `@cheaper`, `@cheapest`) are no longer built in.
Replace retired role aliases with `llm_provider.default_model`,
`llm_provider.epic_lander_model`, `llm_provider.big_epic_lander_model`, or the five size
aliases from `@xsmall` through `@xlarge`, as appropriate. Use direct size aliases with
the epic lander settings for those explicit routes. Custom aliases can use these names,
but they do not receive special handling. Run `sase doctor -C config.model_aliases` to
find removed keys and aliases; it reports the exact replacement for each stale value.

The tier values `big` and `little` map to `large` and `small`. New configs and callers
should use `large`/`small` and the `model_tier` argument. Callers that pass `model_size`
to `invoke_agent()` should switch to `model_tier`.

## Related

- [Providers and models](../providers/index.md) — current provider behavior.
- [Models and aliases](../providers/models.md) — current model selection.
