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

## Related

- [Providers and models](../providers/index.md) — current provider behavior.
- [Models and aliases](../providers/models.md) — current model selection.
