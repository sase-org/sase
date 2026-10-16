---
title: Qwen Code provider
description:
  Qwen Code command construction, authentication, and provider-specific behavior.
---

# Qwen Code provider

This page describes how SASE integrates Qwen Code for agent invocations.

## Qwen Code Integration

The `QwenProvider` invokes the `qwen` CLI tool.

### Command Construction {#command-construction-3}

```
qwen --input-format text --output-format stream-json --yolo --model <model> [extra_args...]
```

The prompt is written to stdin using Qwen's text input mode. Output is streamed as JSON
events; SASE extracts assistant text from `assistant` events and falls back to the final
`result` text when no assistant text is emitted.

### Model Mapping {#model-mapping-3}

<!-- BEGIN GENERATED: model-tiers-qwen -->

| Tier    | Model               |
| ------- | ------------------- |
| `large` | `qwen3.6-plus`      |
| `small` | `qwen3-coder-flash` |

<!-- END GENERATED: model-tiers-qwen -->

### Authentication

Configure Qwen Code through its supported auth and settings flow before using it from
SASE. Qwen OAuth free tier access ended on 2026-04-15; use API keys, Alibaba Cloud
Coding Plan, OpenRouter, Fireworks, or another Qwen-supported provider instead of
relying on the discontinued OAuth free tier.

### Environment Variables {#environment-variables-3}

| Variable               | Description                                              |
| ---------------------- | -------------------------------------------------------- |
| `SASE_LLM_LARGE_ARGS`  | Extra CLI args for `large` tier (generic, preferred)     |
| `SASE_LLM_SMALL_ARGS`  | Extra CLI args for `small` tier (generic, preferred)     |
| `SASE_QWEN_PATH`       | Path to the Qwen Code CLI binary (default: `qwen`)       |
| `SASE_QWEN_LARGE_ARGS` | Extra CLI args for `large` tier (Qwen-specific fallback) |
| `SASE_QWEN_SMALL_ARGS` | Extra CLI args for `small` tier (Qwen-specific fallback) |

The generic `SASE_LLM_*_ARGS` variables take precedence over `SASE_QWEN_*_ARGS`.

Qwen Code config is left in Qwen's normal locations (`~/.qwen/settings.json` and project
`.qwen/settings.json`). SASE does not create a shadow Qwen home in the first
implementation because local Qwen was unavailable during this phase, so no normal
headless-run config mutation could be verified.

### Qwen Tool-Call Capture

SASE captures Qwen tool calls from the `qwen --output-format stream-json` event stream;
it does not install Qwen hooks. When `SASE_ARTIFACTS_DIR` is present, the stream parser
normalizes Qwen's nested `tool_use` and `tool_result` blocks into records appended to
`$SASE_ARTIFACTS_DIR/tool_calls.jsonl` for sase's TUI
[Agents Tab LLM Calls Panel](../tui/agents-deck-panels.md#agents-tab-llm-calls-panel)
with `runtime: "qwen"` and `source: "stream"`. Malformed or unsupported tool-shaped
events emit a diagnostic instead of producing a malformed record. The LLM Calls reader
collapses each start/result pair into a single row.

### Commit Finalization {#commit-finalization-1}

SASE-launched Qwen runs use the shared provider-neutral commit finalizer described
above; active SASE settings do not need repo-local or global Qwen commit-hook
configuration.

### Timer Display {#timer-display-3}

While waiting for a response, a `provider_timer("Waiting for Qwen")` spinner is shown
(unless `suppress_output` is `True`).

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model names and tier defaults.
