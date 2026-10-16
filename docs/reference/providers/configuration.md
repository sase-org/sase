---
title: Provider configuration
description:
  Configuration fields and command-line options that affect provider invocation.
---

# Provider configuration

This page collects provider configuration details that apply across provider CLIs.

## Configuration

The LLM provider reads its configuration from `~/.config/sase/sase.yml` under the
`llm_provider` key.

### Config File

```yaml
llm_provider:
  provider: claude # or "codex", "qwen", "opencode", "agy", "muse", "grok", "fakey" (default: auto-detect)
  default_effort: xhigh # default reasoning effort when a prompt sets none (default: unset)
  default_model: "@large" # used when a launch has no %model directive (default: @large)
  epic_lander_model: "@large" # epic land agents below bead.big_epic_phase_threshold (default: @large)
  big_epic_lander_model: codex/gpt-6.1-sol # epic land agents at/above the threshold (default: @xlarge)
  model_alias_history_limit: 10 # runs shown per alias in Launch Control history (minimum: 1)
  # Override examples; shipped size-alias targets are generated below.
  model_aliases:
    builtin:
      xsmall: claude/haiku@minimal | codex/gpt-4.1-mini@low # custom xsmall pool
      small: claude/haiku | codex/gpt-4.1-mini # custom small pool
      medium: claude/sonnet@xhigh | codex/gpt-5.5@xhigh
      large: codex/gpt-6.1-sol@xhigh | claude/opus@xhigh
      xlarge: claude/sonnet@max # custom maximum-effort target
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
        bucket: research
    buckets:
      research:
        description: Aliases used by research agents.
  usage_limit:
    enabled: true
    disable_seconds: 86400
    notify: true
    providers:
      claude:
        patterns: ["you've hit your usage limit"]
        exclude_patterns: ["usage limit approaching"]
        replace_patterns: false
```

### Config Fields

| Field                                    | Type   | Default     | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`                  | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; real built-ins default to claude → codex → qwen → opencode → agy, with fakey last as a testing-only fallback. `muse` and `grok` declare no priority and are never auto-detected; select them explicitly.                                                                                                                                                                                                                                                                                                         |
| `llm_provider.default_effort`            | string | unset       | Default [reasoning-effort](models.md#reasoning-effort) level applied when a prompt sets no `%effort`/`@effort` and the selected alias carries no effort. One of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; unset/invalid imposes no effort.                                                                                                                                                                                                                                                                                                                                 |
| `llm_provider.model_tier_map`            | dict   | -           | Accepted by the config schema for compatibility. No runtime path currently reads it; setting `large`/`small` here has no effect. Size aliases and `default_model` / lander settings select models.                                                                                                                                                                                                                                                                                                                                                                                           |
| `llm_provider.default_model`             | string | `@large`    | Model expression used for a launch with no explicit `%model` directive. See [Implicit role aliases](models.md#implicit-role-aliases).                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `llm_provider.epic_lander_model`         | string | `@large`    | Model expression used by epic land agents whose epic has fewer authored phases than `bead.big_epic_phase_threshold`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `llm_provider.big_epic_lander_model`     | string | `@xlarge`   | Model expression used by epic land agents whose epic has `bead.big_epic_phase_threshold` or more authored phases.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `llm_provider.model_alias_history_limit` | int    | `10`        | Maximum prior runs returned per alias for the Launch Control agent-history panel. Must be at least `1`; malformed runtime values defensively fall back to `10`.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `llm_provider.model_aliases.builtin`     | dict   | -           | Builtin size-alias overrides only (`xsmall`, `small`, `medium`, `large`, `xlarge`). Values use the single-target grammar below, a `\|` round-robin pool, a `\|\|` ordered fallback, or a parenthesized `(A \| B) \|\| C` last-resort. Retired names — `default`, `epic_lander`, `big_epic_lander`, `<size>_worker`, `smart`, `smarter`, `smartest`, `cheap`, `cheaper`, `cheapest`, `coder`, `<provider>_coder`, `epic_creator`, `phase_worker`, and `<size>_phase_worker` — are no longer builtin overrides; `sase doctor -C config.model_aliases` reports them and names each replacement. |
| `llm_provider.model_aliases.custom`      | dict   | -           | User-defined aliases for `%model:@<alias>` / `%m:@<alias>`. Each value is an object with required `model` and `description` fields; `model` accepts the same single-target and selector grammar. Descriptions are shown in completions and Launch Control.                                                                                                                                                                                                                                                                                                                                   |
| `llm_provider.model_aliases.buckets`     | dict   | -           | Optional display-only sase's TUI Launch Control bucket descriptions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `llm_provider.usage_limit`               | dict   | enabled     | Usage-limit classification and automatic temporary provider-disable policy. See [Usage-Limit Auto-Disable](usage.md#usage-limit-auto-disable).                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `llm_provider.usage_metrics`             | dict   | enabled     | Subscription-capacity collection cadence and opt-out. See [Subscription usage extension](plugins.md#subscription-usage-extension).                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `llm_provider.continuation_budget`       | dict   | see below   | Byte budget for the continuation preflight that runs before monitor successor prompts reach a provider. See [Continuation Budget Preflight](#continuation-budget-preflight).                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `llm_provider.retry`                     | dict   | see below   | Per-provider retry and fallback policy. See [Retry and Fallback](retry-and-fallback.md#retry-and-fallback).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

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

## CLI Flags

### tui

| Flag                 | Values              | Description                                 |
| -------------------- | ------------------- | ------------------------------------------- |
| `-m, --model-tier`   | `large`, `small`    | Override model tier for all LLM invocations |
| `-M, --model-size`   | `big`, `little`     | Deprecated alias for `--model-tier`         |
| `-v, --vcs-provider` | `git`, `hg`, `auto` | Override VCS provider                       |

### axe

| Flag                 | Values              | Description           |
| -------------------- | ------------------- | --------------------- |
| `-v, --vcs-provider` | `git`, `hg`, `auto` | Override VCS provider |

The `sase tui` command wires `--model-tier` / `--model-size` into the
`model_tier_override` parameter of the TUI app (`AceApp`). The `--vcs-provider` flag is
wired to the `SASE_VCS_PROVIDER` environment variable for downstream resolution.

## Related

- [Providers and models](index.md) — provider integrations and model routing.
- [Environment variables](../environment-variables.md) — provider-specific variables.
