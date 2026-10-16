---
title: External provider plugins
description: How external plugins extend SASE's LLM provider registry.
---

# External provider plugins

This page describes the provider plugin extension points available to SASE
installations.

## External Provider Plugins {#external-provider-plugins-1}

Additional LLM providers are shipped as external packages that declare
`[project.entry-points."sase_llm"]` in their own `pyproject.toml`. Plugins carry all
their own metadata (model names, skill deploy path, CLI status color, auto-detect
priority, retry defaults) via pluggy `@hookimpl` methods — sase core has no
plugin-specific branching.

External provider packages own their CLI invocation details, model metadata, skill
deployment path, auto-detect priority, and retry defaults. Install the provider package
in the same environment as sase to make its `sase_llm` entry point available.

### Subscription usage extension

Subscription-capacity collection is an optional plugin capability. Provider packages
implement the same hooks; SASE core, the refresh service, CLI, and widgets do not branch
on provider name.

| Hook                       | I/O           | Cached           | Default when omitted                                 |
| -------------------------- | ------------- | ---------------- | ---------------------------------------------------- |
| `llm_usage_capabilities()` | none          | yes, as metadata | unsupported (`probe` and `passive_events` are false) |
| `llm_usage_probe(context)` | collector I/O | never            | unsupported                                          |

`llm_usage_capabilities()` is static: it must not touch the network, spawn processes, or
read credential files. The registry may cache it. Live observations from
`llm_usage_probe` must never enter that cache. Plugins may declare
`min_probe_interval_seconds` (finite, 60..=86400; out-of-range values are dropped) as
the fastest automatic re-probe cadence. Shipped floors are claude 300, muse 180, and
agy/grok/codex 120.

`llm_usage_probe(context)` receives a typed context with schema version, deadline,
resolved executable, opaque auth-context fingerprint, account generation, and operation
identity. Return a provider-usage observation mapping that matches the Rust observation
contract, or `None` if this plugin does not collect usage. Unexpected exceptions are
caught at the probe-runtime boundary and become sanitized `error` observations. Do not
put raw stdout/stderr, tokens, emails, account ids, or filesystem secrets in
diagnostics.

Probes run in isolated killable worker processes. Vendor CLIs are argv-only children of
those workers. Collectors share the bounded JSON-line transport in
`sase.llm_provider.usage.transport` and keep JSON-RPC or ACP handshakes in the collector
module. The transport never services login, token-refresh, tool, or approval requests.

Passive stream events (for example Claude `rate_limit_event`) go through
`record_passive_usage_observation`, which accepts the same fenced envelope. Persistence
is owned by the usage store.

Failed probes classify provider pushback before anything else: when the failure evidence
carries HTTP 429, `rate limit` / `rate-limited`, or `too many requests` — in a JSON-RPC
or ACP error, the exit code output, or stderr — the collector reports outcome `error`
with reason `rate_limited` instead of its usual failure reason. A `Retry-After` hint is
captured into the observation's `retry_after_seconds` field from `retry-after: N`
headers, `retry after/in N seconds|minutes` prose, or `retry_after` / `retryAfter`
fields, and honored by refresh backoff. Plugin authors implementing their own collector
should consult the shared `sase.llm_provider.usage._strategy.detect_rate_limit`
classifier on every failure path before other classification, and report a missing
executable as outcome `unsupported` with reason `not_installed`.

Existing plugins that omit these hooks keep invoking normally: `LLMProvider.invoke` and
`InvokeResult` are unchanged.

Collection is gated by the durable `llm_provider.usage_metrics.enabled` preference.
Per-provider `llm_provider.usage_metrics.providers.<name>.enabled` overrides collection
without hard-coding the initial three providers.

`submit_usage_refresh` is the shared durable refresh service for CLI, sase's TUI, the
scheduler, and limit-event triggers. It coalesces work per provider and account
generation, joins in-flight probes without dropping other requested providers, and
bounds automatic retries with cadence-based backoff. Automatic admission passes
`adaptive=True` with each provider's floor, CLI fingerprint, hot cadence
(`active_refresh_seconds`, capped at the idle cadence), and `warn_percent`; parked
providers unpark early when the CLI changes. Providers in active use — a recent agent
launch or limit-event hint (each good for 15 minutes), or a stored window at or above
`warn_percent` used — refresh at `max(active_refresh_seconds, floor)` unless live stream
events already keep their windows fresh. Limit events only mark the provider due — they
never submit an explicit probe, so the next routine tick picks the provider up subject
to its floor. The scheduler runs due work inline from the `usage_refresh` job on the
60-second `usage` routine, probing the admitted batch in-process so periodic collection
creates no proc rows. sase's TUI requests the same due work after first paint and while
open, but only when the scheduler does not own collection. A normal TUI tick never
probes inline.

## Related

- [Providers and models](index.md) — provider integrations and model routing.
- [Agent CLIs](agent-clis.md) — install and update metadata for provider CLIs.
