---
title: Choose providers and models
description:
  Install a provider CLI, check authentication, and pick the model agents use.
---

# Choose providers and models

This guide gets one provider ready and selects the model your agents use. It assumes
SASE is installed; if not, start with [Install and set up SASE](../start/install.md).

## Before you start

You need one supported agent CLI installed and authenticated for production work. The
bundled `fakey` provider is for tests, not real runs.

## 1. Install and authenticate one provider

Each supported provider has an install command, an authentication command, and a link to
its vendor docs in [Agent providers](../reference/providers/agent-clis.md). SASE can
install most provider CLIs for you; the page says which one you install yourself.

## 2. Check that SASE can use it

Run the authoritative readiness check:

```bash
sase doctor -C llm.auth -v
```

The check prints the selected provider, how it was selected, and the authentication
evidence it found. If the page and the doctor ever disagree, trust the doctor output.

A provider reported as disabled is routing policy, not a missing install: a hard disable
blocks automatic routing and explicit requests until it expires or is cleared, while a
soft disable only steers preference pools away. Interactive provider windows still
launch while hard-disabled.

## 3. Pick the model

Launches without an explicit request use `llm_provider.default_model`, which is the
`@large` size alias unless changed. The five size aliases — `@xsmall`, `@small`,
`@medium`, `@large`, `@xlarge` — resolve to an available provider and model, so prompts
that use them stay portable across provider choices. One prompt can request something
else with a `%model` directive such as `%model:codex/gpt-6-luna`.

Set the default in configuration when most of your work wants a different level:

```yaml
llm_provider:
  default_model: "@medium"
```

Confirm the new default with `sase doctor -C llm.default`.

## If it goes wrong

Re-run the check from step 2 and follow its next step; provider sections in
[Agent providers](../reference/providers/agent-clis.md) match the doctor hints. For
anything else, start with [Diagnose problems with sase doctor](diagnose-with-doctor.md).

## Related

- [Agent providers](../reference/providers/agent-clis.md) — install and authentication
  per provider.
- [LLM providers](../reference/providers/models.md#per-prompt-provider-switching) —
  aliases, explicit requests, and provider behavior.
- [Providers and models](../concepts/providers.md) — why SASE routes through providers.
