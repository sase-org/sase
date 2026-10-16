---
title: "LLM provider behavior configuration"
description: "Provider selection, usage limits, retries, and execution budgets."
---

# LLM provider behavior configuration

Provider selection, usage limits, retries, and execution budgets.

<a id="llmprovider"></a>

## llm_provider

Configures which LLM backend sase uses and how size aliases map to concrete models. See
[Providers and models](../providers/index.md) for provider behavior and
[LLM invocation internals](../../contribute/llm-invocation.md) for the processing
pipeline.

```yaml
llm_provider:
  provider: claude # or "codex", "qwen", "opencode", "agy", "muse", "grok", "fakey" (default: auto-detect)
  # Scalar launch settings. Same grammar as %model; may reference a built-in
  # size alias.
  default_model: "@large" # used when a launch has no %model directive
  epic_lander_model: "@large" # epic land agents below bead.big_epic_phase_threshold
  big_epic_lander_model: "@xlarge" # epic land agents at/above that threshold
  model_alias_history_limit: 10 # runs shown per alias in Launch Control history
  # Override examples; shipped size-alias defaults are generated in the provider reference.
  model_aliases:
    builtin:
      medium: codex/gpt-6.1-sol # specialize the medium size alias
      large: claude/opus | codex/gpt-6.1-sol # custom large-phase pool
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
        bucket: writing # optional Launch Control grouping
    buckets:
      writing:
        description: Writing and editing roles.
```

[Generated reference for `llm_provider`](llm-provider.md#llm_provider)

Model aliases are resolved when an agent launches, so reusable macros can point at names
such as `%model:@medium` or `%model:@blogger` while each user's `sase.yml` controls the
concrete provider/model. Alias config keys stay bare; the `@` marker is only used in
`%model`/`%m` directive values. Alias values may reference another alias with
`@<alias>`; the reference may carry a trailing effort such as `@medium@high`, which
overrides the referenced alias's effort (chains are followed with cycle/depth
protection). Unknown non-alias model values keep the existing fallback behavior and run
on the default provider. Use `model_aliases.builtin` to override one of the five
built-in size aliases and `model_aliases.custom` for user-defined aliases with
descriptions. `A | B` round-robins across real launches, skips providers whose CLI is
unavailable, and stores its machine-global cursor in `~/.sase/llm_lb.json`; display and
preview surfaces only peek. `A || B` always selects the first installed provider CLI
that is not **hard**-disabled (a **soft**-disabled first candidate still wins) and never
reads or advances that cursor. `(A | B) || C` load-balances the parenthesized pool and
uses the `||` tail only when every pool member is unavailable (CLI missing or
**hard**-disabled); an all-**soft** pool still rotates and does not divert, and tail
selection does not consume the pool cursor. Unparenthesized mixing is still rejected.
Ordered fallback is based on CLI installation plus temporary provider-disable state, not
later model/runtime success, and preserves its first candidate for normal diagnostics
when none are available. Members may carry a trailing effort. Selectors cannot be
nested, and selectors are not accepted in `%model` directives or launch-scoped/temporary
overrides. In sase's TUI Launch Control, the pool row reports the available/total count,
selector member lists mark the current selection with `→`, and active temporary
overrides label selection suspended unless their provider is **hard**-disabled; then the
override is paused and the underlying alias resolves. A **soft** disable does not pause
the override.

On top of any configured aliases, SASE ships a fixed set of **built-in size aliases**
that resolve even when unset: `@xsmall`, `@small`, `@medium`, `@large`, and `@xlarge`.
Each is a direct selector with no fallback chain to another alias — override one by
setting `model_aliases.builtin.<size>` to a concrete model, an `A | B` round-robin pool,
an `A || B` ordered fallback, or a parenthesized `(A | B) || C` last-resort. Phase and
task launches route directly to the size alias matching their size metadata; a phase or
task with no size metadata routes through `@small`. New tasks require an explicit size
after `/sase_new_task` has ruled out a semantic duplicate and a causally related
in-progress epic. See
[Built-in size aliases](../providers/models.md#implicit-role-aliases) for the full
shipped-defaults table and
[Role Aliases for Delegated Work](../providers/models.md#role-aliases-for-delegated-work)
for how delegated launches pick a model.

Three scalar `llm_provider` fields choose the model for launches that aren't driven by
phase/task/tale size routing: `default_model` (used when a launch has no explicit
`%model` directive), `epic_lander_model` (used by epic land agents below
`bead.big_epic_phase_threshold` authored phases), and `big_epic_lander_model` (used by
epic land agents at or above that threshold). Each accepts the same grammar as an alias
target — a concrete model, a provider-qualified model, an `@alias` reference (optionally
with a trailing effort such as `@large@high`), an `A | B` pool, an `A || B` fallback, or
a parenthesized `(A | B) || C` last-resort. Precedence is unchanged from before the
migration: an explicit prompt/plan/phase/task/approval-picker `%model` wins first, then
an active temporary override of the selected setting, then the config field resolves
through the normal alias/effort/selector/provider-disable machinery, and a missing or
malformed field falls back to its shipped default (`@large` / `@large` / `@xlarge`).

`model_alias_history_limit` bounds the number of prior runs requested for each alias in
Launch Control's agent-history panel. It defaults to `10`, must be at least `1`, and
falls back to `10` at runtime when a malformed value bypasses schema validation. From
that initial window, the panel's Ctrl+J / Ctrl+K keys add or subtract a fixed 10-run
step and never drop below this configured limit; they do not use `ace.page_size`.

Accepted tale follow-ups without an approval-time model validate the actual handoff plan
and choose the matching size alias directly. Tale plans without size metadata use
`@medium`. An approval-time model, a `%model` directive in a custom coder prompt, or an
outer effort suffix remains authoritative.

There is no built-in `epic_creator` model alias. `sase doctor` reports a leftover
`model_aliases.builtin.epic_creator` setting so it can be removed. See
[Provider migration notes](../upgrading/providers.md#model-aliases) for removed alias
names and current replacements.

The TUI also supports **temporary**, per-alias session-level provider/model overrides
(set from [Launch Control](../../ace.md#launch-control), `,m`) that do **not** edit this
config. They are persisted to `~/.sase/llm_override.json` and expired entries are
deleted on next read. See
[Temporary model overrides](../providers/routing.md#temporary-model-overrides) for the
resolution order, state-file format, and precedence relative to
`SASE_MODEL_TIER_OVERRIDE`.

The same panel's `p=Providers` flow manages temporary provider disables in
`~/.sase/llm_provider_disables.json`. This is runtime state, not configuration: it does
not add a `disabled_providers` key, does not edit `llm_provider.provider`, and does not
rewrite any alias. A **hard** disable is fail-closed: alias selectors skip that member,
temporary alias overrides targeting it pause until the disable clears or expires, and
direct explicit provider/model requests fail with an actionable diagnostic instead of
silently switching providers. A **soft** disable is spared in `|` pools while another
member can cover, never diverts a `||` fallback, and does not pause overrides or fail
explicit requests. See
[Temporary Provider Disables](../providers/routing.md#temporary-provider-disables).

<a id="llmproviderusagelimit"></a>

### `llm_provider.usage_limit`

Automatic usage-limit detection temporarily disables a provider when that provider's own
error output positively matches its configured usage-limit patterns. This is separate
from `llm_provider.retry`: provider-scoped usage-limit classification wins before retry
policy, while a plain transient `429` or other retryable error that does not match a
usage-limit pattern still follows retry/fallback policy.

```yaml
llm_provider:
  usage_limit:
    enabled: true
    disable_seconds: 86400
    min_disable_seconds: 60
    max_disable_seconds: 604800
    honor_reset_hint: true
    honor_usage_windows: true
    notify: true
    relaunch: true
    relaunch_limit: 20
    providers:
      claude:
        patterns:
          - "you've hit your usage limit"
        exclude_patterns:
          - "usage limit approaching"
        replace_patterns: false
        disable_seconds: null
        honor_reset_hint: null
        honor_usage_windows: null
```

[Generated reference for `llm_provider.usage_limit`](llm-provider.md#llm_provider-usage_limit)

Automatic disables are written to the same machine-wide provider-disable state used by
Launch Control, with `source: "usage_limit"`. They expire and self-clean like manual
disables, can be cleared early from Launch Control, and do not unregister or rewrite a
provider. If a fallback is available, retry/fallback may proceed only to a different
enabled provider; the disabled provider remains skipped until expiry or clearing. See
[Usage-Limit Auto-Disable](../providers/usage.md#usage-limit-auto-disable) for
reset-hint parsing, notification, and replacement details.

<a id="llmproviderusagemetrics"></a>

### `llm_provider.usage_metrics`

Subscription-capacity collection settings. This is distinct from
`llm_provider.usage_limit`, which classifies provider error text and writes temporary
routing disables. `usage_metrics` controls whether SASE probes installed provider CLIs
for included-allowance windows.

`enabled` is the durable user preference; setting it `false` stops probes, isolated
workers, passive observation writes, scheduled requests, and attention.

Claude, Codex, Grok, Muse Code, and Antigravity ship collectors. Muse's is a free local
probe against `muse serve` — no model call and no tokens — so it costs only about three
seconds of wall clock per refresh. To turn it off, set
`llm_provider.usage_metrics.providers.muse.enabled` to `false`; see
[Muse Code subscription usage](../providers/agent-clis.md#muse-subscription-usage).
Antigravity's is likewise a free local `/usage` probe (`agy >= 1.1.11`, about three to
five seconds per refresh); see
[Antigravity subscription usage](../providers/agent-clis.md#agy-subscription-usage).

Every recorded attempt carries its outcome, failure reason, and any `Retry-After` hint,
and refresh backoff follows the failure class. `sase usage list -v` shows the
per-provider retry state; JSON output passes the `collector_health` snapshot through
unchanged.

| Class        | Failure reasons                                                                                               | Retry policy                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Success      | `ok`, `not_applicable`, `unsupported` outcomes                                                                | next probe at the provider cadence                                                                                              |
| Transient    | `timeout`, `deadline_exceeded`, `probe_failed`, `parse_error`, `malformed_payload`, `account_context_changed` | cadence-based backoff up to 30 minutes                                                                                          |
| Rate-limited | `rate_limited`                                                                                                | honored `Retry-After` (clamped to 15 minutes–6 hours) when present, otherwise an escalating delay from 15 minutes up to 2 hours |
| Auth         | `unauthenticated`, `logged_out`, `api_mode` outcomes                                                          | generic backoff up to 30 minutes                                                                                                |
| Parked       | `not_installed`, `unsupported_cli_version`                                                                    | 6-hour backoff, released early when the CLI changes                                                                             |
| Vendor drift | `vendor_drift`                                                                                                | fixed 1-hour backoff                                                                                                            |

Providers in active use refresh on the hot cadence instead of the idle one. A provider
counts as hot while a recent agent launch or limit-event hint (each good for 15 minutes)
is still live, or while one of its stored un-reset windows sits at or above
`warn_percent` used. Hotness is suppressed while live stream events already keep every
stored window fresh — a window received within the active cadence of now needs no probe.
The hot interval is `max(active_refresh_seconds, floor)`, so a hot Claude still waits
for its 300 s floor while a hot Codex is due at about 120 s.

```yaml
llm_provider:
  usage_metrics:
    enabled: true
    refresh_seconds: 300
    active_refresh_seconds: 120
    warn_percent: 75
    critical_percent: 90
    indicator:
      enabled: true
      default:
        below_remaining_percent: 20
      weekly_all: always
      providers:
        muse:
          windows:
            session: never
    providers:
      claude:
        enabled: true
```

[Generated reference for `llm_provider.usage_metrics`](llm-provider.md#llm_provider-usage_metrics)

An indicator policy is exactly one of:

- `always`: display each matching observed window at any remaining percentage.
- `never`: suppress matching display entries.
- `{below_remaining_percent: N}`: display only when the unrounded remaining percentage
  is strictly less than finite `N`, where `0 <= N <= 100`.

Thresholds use percentages remaining, not percentages used. `0` selects no numeric
windows, `100` still excludes an exactly full window, and `always` is the only policy
that includes full capacity.

Display policy precedence is exact window key, provider default, `weekly_all` for a
positively classified weekly all-model window, then global `indicator.default`. Provider
and window IDs are open-ended; unmatched future provider/window keys are inert.

The bundled default adds one exact Muse override:

```yaml
llm_provider:
  usage_metrics:
    indicator:
      providers:
        muse:
          windows:
            session: never
```

Claude's observed weekly Fable window has no bundled entry, so the global
`indicator.default` threshold governs it and the header shows it only when its remaining
capacity is strictly below 20%. Set the exact key `"weekly:claude-fable-5"` to `always`
to restore the always-visible behavior, to `never` to hide it even when low, or to a
`{below_remaining_percent: N}` of its own. Missing or collection-ineligible Fable
windows are not synthesized. Because config layers merge recursively, an empty user
`indicator.providers: {}` does not erase this bundled key, while an explicit value for
the key does override it. Broader provider/global defaults have lower selection
precedence than the exact window key.

Muse reports two windows: a 5-hour `session` window and a `weekly` window. The header
shows only the weekly one by default. Muse's weekly window is classified as a weekly
all-model window, so the existing `weekly_all: always` policy selects it with no entry
of its own, and it appears at any remaining percentage once Muse is an eligible provider
(the `muse` CLI is installed and Muse is referenced by a model alias or enabled in
`llm_provider.usage_metrics.providers`). The `session: never` override deliberately
suppresses the 5-hour window even when it runs low; it stays visible in Providers ·
Usage and `sase usage list -p muse`. Restore header attention for it with:

```yaml
llm_provider:
  usage_metrics:
    indicator:
      providers:
        muse:
          windows:
            session:
              below_remaining_percent: 20
```

Antigravity reports four windows — `gemini-weekly`, `gemini-5h`, `3p-weekly`, and
`3p-5h` — and has no bundled indicator entry. Its Gemini weekly window is treated as the
provider's weekly anchor (it matches the `weekly_all` policy while keeping its
`family:gemini` scope), so `weekly_all: always` anchors it in the header unlabeled
whenever agy is an eligible provider; a `providers.agy.default` policy would take
precedence. The Gemini 5-hour window and both `3p-*` (Claude/GPT) windows fall through
to the global `indicator.default` threshold and appear only below 20% remaining. Pin or
hide them with exact keys:

```yaml
llm_provider:
  usage_metrics:
    indicator:
      providers:
        agy:
          windows:
            gemini-5h: always
            3p-weekly: never
```

Invalid indicator config is diagnosed with its config path, ignored at the smallest
invalid override, and inherited/default policy is used instead of resetting unrelated
valid usage settings. sase's TUI display settings are cached by the merged-config token,
so config changes reload on the normal usage refresh cadence even when the usage-state
file does not change.

Routing-disabled providers still refresh when collection is otherwise eligible, because
reset information remains useful for them.

The same panel's fixed `Ctrl+E` binding manages the separate machine-wide default-effort
override at `~/.sase/llm_effort_override.json`. It uses the alias override duration and
exact-time cards, but its state and precedence are independent: explicit prompt effort
and alias/member effort win, then the temporary effort override, then
`llm_provider.default_effort`, then the provider default. See
[Reasoning Effort](../providers/models.md#reasoning-effort).

Its fixed `Ctrl+R` binding manages `max_running_agents`: persistent edits target the
user-base `sase.yml` (or its chezmoi source), while temporary values live independently
in `~/.sase/max_running_agents_override.json`. This is a Launch Control binding, not an
<a id="llmprovidercontinuationbudget"></a> `ace.keymaps` option.

### `llm_provider.continuation_budget`

Byte budget for the continuation-budget preflight. Monitor successors always run it, and
so does any invocation with `SASE_CONTINUATION_BUDGET_ENFORCE=1`. The preflight measures
the final expanded prompt; when its essential content cannot fit the effective budget,
SASE records the decision and refuses before calling the provider.

```yaml
llm_provider:
  continuation_budget:
    context_limit_bytes: 800000
    estimate_uncertain: true
    instruction_reserve_bytes: 0
    tool_reserve_bytes: 0
    output_reserve_bytes: 0
    reasoning_reserve_bytes: 0
    providers:
      agy:
        transport_limit_bytes: 122880
        instruction_reserve_bytes: 512
        # models:
        #   <model-name>: { context_limit_bytes: 400000 }
```

[Generated reference for `llm_provider.continuation_budget`](llm-provider.md#llm_provider-continuation_budget)

Each field resolves independently: a matching model entry wins over its provider entry,
which wins over the shared values, and the matching `SASE_CONTINUATION_*` variable (see
[LLM Provider environment variables](../environment-variables.md#llm-provider)) outranks
all of them. A zero, negative, or non-integer value uses the built-in default instead.
The bundled `agy` entry reflects that Antigravity sends the print prompt as one argv
element; SASE keeps those `agy` transport and instruction-reserve values even without
configuration and never lets the `agy` instruction reserve drop below 512 bytes.

<a id="llmproviderretry"></a> Source:
`src/sase/llm_provider/continuation_budget_request.py`

### `llm_provider.retry`

Per-provider retry and fallback configuration. See
[Provider retry and fallback](../providers/retry-and-fallback.md#retry-and-fallback) for
the full retry flow and TUI display.

```yaml
llm_provider:
  retry:
    claude:
      max_retries: 3
      error_patterns:
        - "API Error: 500"
      wait_times: [60, 300, 1800]
      fallback_model: "sonnet"
      continuation_prompt: "Please continue from the last preserved work."
      preserve_workspace: true
      spawn_new_agent: false
```

[Generated reference for `llm_provider.retry`](llm-provider.md#llm_provider-retry)

Configured retry policy is merged with provider-supplied retry defaults when a provider
declares them. For list fields such as `error_patterns`, built-in patterns are kept and
configured patterns are appended with duplicates removed. Claude's provider hook adds
workspace-preserving matching for context-limit, socket-close, and Claude CLI API-error
output, plus a continuation nudge. Those hook defaults are merged with the bundled
Claude policy in `default_config.yml`, so the configured wait times and fallback model
still apply unless you override them.

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/llm_provider/config.py`

## Related

- [LLM provider configuration](llm-provider.md) — generated provider keys and defaults.
