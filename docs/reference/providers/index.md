---
title: Providers and models
description:
  Lookup pages for provider integrations, model selection, routing, and usage.
---

# Providers and models

Use these pages to look up how SASE connects provider CLIs and routes model requests.

This document describes the LLM provider abstraction layer in sase. The system supports
pluggable LLM backends (Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code,
OpenCode, Meta's Muse Code, and xAI's Grok Build are bundled; additional providers can
ship as external plugins) behind a shared orchestration layer that handles
preprocessing, invocation, and postprocessing.

> This page documents how SASE _integrates_ each provider. To install and authenticate a
> provider CLI in the first place, see
> [Installing & Authenticating Agent Providers](agent-clis.md).

## Provider CLIs

- [Agent CLIs](agent-clis.md) — install, authenticate, and inspect supported tools.
- [Claude Code](claude.md) · [Antigravity](agy.md) · [Codex](codex.md) · [Qwen](qwen.md)
  · [OpenCode](opencode.md) · [Muse Code](muse.md) · [Grok Build](grok.md)
- [External provider plugins](plugins.md) — extend the provider registry.

## Models and routing

- [Models and aliases](models.md) — model catalog, tiers, effort, and role aliases.
- [Provider routing](routing.md) — temporary overrides, disables, and priority.
- [Provider configuration](configuration.md) — shared settings and CLI options.
- [Provider usage](usage.md) — subscription capacity and usage-limit behavior.
- [Retry and fallback](retry-and-fallback.md) — provider failures and recovery.

## Related

- [Environment variables](../environment-variables.md) — provider and runtime variables.
