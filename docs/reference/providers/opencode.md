---
title: OpenCode provider
description:
  OpenCode command construction, model mapping, and provider-specific behavior.
---

# OpenCode provider

This page describes how SASE integrates OpenCode for agent invocations.

## OpenCode Integration

The `OpenCodeProvider` invokes the `opencode` CLI tool.

### Command Construction {#command-construction-4}

```
opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> [extra_args...] <prompt>
```

The prompt is passed as OpenCode's `run [message..]` argument without shell
interpolation. Output is streamed as JSONL events; SASE extracts assistant text from
`text` events, captures errors from `error` events, and accumulates token counters from
`step_finish` events when OpenCode reports them.

### Model Mapping {#model-mapping-4}

OpenCode model IDs normally include an upstream provider prefix. Use
`%model:opencode/<provider/model>` to route a single SASE prompt to a concrete OpenCode
model.

<!-- BEGIN GENERATED: model-tiers-opencode -->

| Tier    | Model                         |
| ------- | ----------------------------- |
| `large` | `anthropic/claude-sonnet-4-5` |
| `small` | `openai/gpt-5-mini`           |

<!-- END GENERATED: model-tiers-opencode -->

### Authentication and Config

Configure OpenCode through its normal auth and settings flow before using it from SASE.
OpenCode stores auth under its XDG data directory and reads config from its XDG config
directory plus project `.opencode` config. Use `opencode models` to inspect the models
available in your configured OpenCode environment.

SASE deploys OpenCode skills under `~/.config/opencode/skills/`, which OpenCode scans as
part of its config directory. SASE does not create a shadow OpenCode data/config home in
this first implementation because OpenCode's normal headless run writes session/database
state under its XDG data directory while reading auth/config from the standard
locations.

### Environment Variables {#environment-variables-4}

| Variable                   | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `SASE_LLM_LARGE_ARGS`      | Extra CLI args for `large` tier (generic, preferred)         |
| `SASE_LLM_SMALL_ARGS`      | Extra CLI args for `small` tier (generic, preferred)         |
| `SASE_OPENCODE_PATH`       | Path to the OpenCode CLI binary (default: `opencode`)        |
| `SASE_OPENCODE_LARGE_ARGS` | Extra CLI args for `large` tier (OpenCode-specific fallback) |
| `SASE_OPENCODE_SMALL_ARGS` | Extra CLI args for `small` tier (OpenCode-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_OPENCODE_*_ARGS`.

### Timer Display {#timer-display-4}

While waiting for a response, a `provider_timer("Waiting for OpenCode")` spinner is
shown (unless `suppress_output` is `True`).

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model names and tier defaults.
