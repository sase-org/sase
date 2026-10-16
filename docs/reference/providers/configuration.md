---
title: Provider configuration
description:
  Configuration fields and command-line options that affect provider invocation.
---

# Provider configuration

This page collects provider configuration details that apply across provider CLIs.

## Configuration

The LLM provider reads `llm_provider` from `~/.config/sase/sase.yml`. The generated
[provider configuration reference](../config/llm-provider.md) lists its fields, types,
and defaults. `llm_provider.model_tier_map` is accepted by the schema but has no runtime
effect; configure size aliases, `default_model`, or lander settings instead.

### Continuation Budget Preflight

A monitor successor (the follow-up agent a [monitor](../../monitors.md) launches) can
carry a large replayed history: ancestor prompts and replies, checkpoints, and command
evidence. Before such a prompt reaches the provider, `invoke_agent()` measures the fully
expanded prompt against a provider-aware byte budget, after the execution provider and
model are resolved. The preflight runs for monitor successors
(`SASE_MONITOR_CONTINUATION=1`) and for any invocation with
`SASE_CONTINUATION_BUDGET_ENFORCE=1`; other launches skip it.

The shared `sase-core` planner returns one of three outcomes:

- **fits** — the prompt is sent unchanged.
- **compact** — SASE drops reducible spans that the prompt renderers explicitly marked
  (older raw output excerpts, selected diagnostics, and assistant transcript already
  covered by a checkpoint) and replaces each with a short note that points at the
  retained evidence. The compacted prompt is re-measured, and it is refused if it still
  does not fit.
- **refuse** — the provider is not called. The invocation fails with
  `Continuation context budget exceeded`, and the recovery guidance asks for an adequate
  checkpoint or a route with a larger context budget rather than a rerun of the
  monitored command.

Each decision is written to `continuation_budget_decision.json` in the agent's artifacts
directory, alongside the projected prompt when compaction changed it.

The budget is configured under `llm_provider.continuation_budget`. Settings layer from
the shared values, to `providers.<provider>`, to `providers.<provider>.models.<model>`,
and the `SASE_CONTINUATION_*` environment variables (see
[LLM provider environment variables](../environment-variables.md#llm-provider)) override
all of them:

```yaml
llm_provider:
  continuation_budget:
    context_limit_bytes: 800000 # total budget before reserves
    estimate_uncertain: true # byte counts are estimates, not provider accounting
    instruction_reserve_bytes: 0
    tool_reserve_bytes: 0
    output_reserve_bytes: 0
    reasoning_reserve_bytes: 0
    # checkpoint_threshold_bytes: 400000  # optional
    providers:
      agy:
        transport_limit_bytes: 122880 # agy sends the prompt as one argv element
        instruction_reserve_bytes: 512
```

`transport_limit_bytes` caps what the provider transport itself can carry, independent
of the model's context. The shipped `agy` values mirror the
[Antigravity prompt-size guard](agy.md#antigravity-agy-integration).

## Command-line options

The generated [`sase tui` reference](../cli/tui.md) and
[`sase axe` reference](../cli/axe.md) list their command-line options. The TUI maps its
model-tier options to the `model_tier_override` parameter of `AceApp` and passes
`--vcs-provider` through `SASE_VCS_PROVIDER` for downstream resolution.

## Related

- [Providers and models](index.md) — provider integrations and model routing.
- [Environment variables](../environment-variables.md) — provider-specific variables.
