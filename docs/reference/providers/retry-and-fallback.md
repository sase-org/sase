---
title: Provider retry and fallback
description:
  Retry defaults, fallback behavior, and how provider failures affect invocations.
---

# Provider retry and fallback

This page describes retries and fallback behavior during provider invocations.

## Retry and Fallback

The LLM provider layer supports per-provider retry and fallback configuration. When an
agent encounters a retryable error, it can automatically wait and retry, then optionally
fall back to an alternate model.

### Configuration {#configuration-1}

Retry behavior is configured per provider under `llm_provider.retry` in `sase.yml`:

```yaml
llm_provider:
  retry:
    claude:
      max_retries: 3
      error_patterns:
        - "API Error: 500"
      wait_times: [60, 300, 1800]
      fallback_model: "sonnet"
```

Retry configuration fields and defaults are listed in the generated
[`llm_provider.retry` reference](../config/llm-provider.md#llm_provider-retry).

### Default Configuration

Retry defaults can come from two places: configured policy under `llm_provider.retry`
and provider-supplied defaults from the `llm_default_retry_config()` hook. The bundled
`default_config.yml` already provides configured policy for Claude and Codex; user
config can replace or extend it through the normal config merge.

**Claude:**

- **max_retries**: 3
- **error_patterns**:
  `["API Error: 500", "API Error: 529", "Internal server error", "overloaded_error"]`
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **fallback_model**: `"sonnet"`

**Codex:**

- **max_retries**: 3
- **error_patterns**:
  `["exceeded retry limit", "429 Too Many Requests", "Too Many Requests", "rate limit", "failed to connect to websocket", "Selected model is at capacity"]`
  — the Codex CLI's own give-up message, terminal rate-limit and model-capacity
  statuses, and the transient websocket transport error. A bare `403 Forbidden` is
  deliberately excluded so a persistent auth failure is not retried forever.
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min) — rate limits need a real
  cool-down

**`sase`** (provider-independent process-version skew):

- **max_retries**: 1
- **error_patterns**: `["uses a format this process does not understand"]`
- **wait_times**: `[0]`
- **preserve_workspace**: `true`
- **spawn_new_agent**: `true` — the retry runs in a fresh process that inherits the
  existing workspace, so a version-skew failure late in a run does not discard the
  agent's work

SASE first checks the agent's own provider policy. When that policy does not match the
error, it checks every configured `llm_provider.retry` entry in order (then
built-in-only providers) and uses the first whose patterns match, which is how the
provider-independent `sase` entry and errors from an inner workflow step on another
provider are retried.

### Provider-Supplied Retry Defaults

Providers can also declare retry defaults through the `llm_default_retry_config()` hook.
Claude, Codex, Grok, and Muse declare a recovery entry that is merged with their
configured policy.

Claude:

- **error patterns**: `"Prompt is too long"`,
  `"socket connection was closed unexpectedly"`, `"API Error"`, and
  `"another Claude Code process is refreshing it"` — the last covers transient OAuth
  refresh-lock contention; expired or revoked logins stay terminal
- **max_retries**: 3
- **wait_times**: `[0]` — used only when no config layer supplies `wait_times`; the
  bundled Claude policy supplies `[60, 300, 1800]`, so that is the out-of-the-box
  backoff
- **continuation_prompt**: A short nudge that tells the coder to inspect `git status` /
  `git diff` before resuming, since prior edits are preserved on disk after a
  context-limit, socket-close, API-error, or OAuth refresh-contention retry
- **preserve_workspace**: `true`

Codex:

- **error patterns**: `"exceeded retry limit"`, `"429 Too Many Requests"`,
  `"Too Many Requests"`, `"rate limit"`, `"failed to connect to websocket"`, and
  `"Selected model is at capacity"` — the transient transport, rate-limit, and
  model-capacity failure modes where the Codex CLI exhausts its own internal reconnects
  or exits non-zero — plus `"Codex turn integrity failure"`, raised by SASE's
  [turn integrity check](codex.md#turn-integrity-check) when a turn ends with no final
  answer
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` — the bundled Codex policy supplies the same backoff
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude
- **preserve_workspace**: `true`

Grok:

- **error patterns**: `"xAI API error"`, `"xAI rate limit"`, `"xAI server error"`, and
  `"xAI upstream request failed"` — kept narrow and xAI-specific so they cannot collide
  with Codex's ownership of generic `429` / `Too Many Requests` wording
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude and
  Codex
- **preserve_workspace**: `true`

Muse:

- **error patterns**: `"no data is reaching this machine from the model service"` —
  captured live from the 2026-10-01 `bob-cli-31.4` failure (Muse 1.4.2-R4684.1), Muse's
  zero-byte chain terminal printed after its own turn retry budget is exhausted;
  `"model_stream_first_event_timeout"` and `"model_stream_idle_timeout"` — the machine
  error kinds from that give-up summary's `all [...]` suffix, a second anchor in case a
  later build rewords the prose; and
  `"kept failing until the whole turn retry budget was exhausted"` — the sibling give-up
  prose for the transport, service, router, and stream-ended failure classes, from
  scanning the shipped binary, not yet observed live
- **max_retries**: 3
- **wait_times**: `[60, 300, 1800]` (1 min, 5 min, 30 min)
- **continuation_prompt**: The same `git status` / `git diff` resume nudge as Claude,
  Codex, and Grok
- **preserve_workspace**: `true`

Fakey:

- **error pattern**: `"FAKEY-RETRYABLE"`, the canonical marker emitted by retryable
  fakey scenarios
- **max_retries**: 3
- **wait_times**: `[0]`, keeping deterministic test retries fast
- **continuation_prompt**: The same resume nudge as Claude and Codex
- **preserve_workspace**: `true`

These defaults make `@flaky` and other retryable fakey scenarios exercise the retry
pipeline without user config. A commented `llm_provider.retry.fakey` example in the
default config shows how to override them.

Configured `llm_provider.retry.<provider>` values are merged on top of provider-supplied
defaults: explicit falsy values (`max_retries: 0` to opt out entirely,
`continuation_prompt: ""` to disable the nudge) override the built-in via key-presence
checks. `error_patterns` is a de-duplicated union of built-in and configured lists.

On every retry attempt the `continuation_prompt` (if non-empty) is idempotently
prepended to `state.current_prompt` before the next invocation — the prepend is gated on
a `startswith` check so repeated retries don't stack duplicate nudges. Workspaces are
preserved across Claude's built-in context-limit, socket-close, and API-error retries
(no workspace wipe), so on-disk edits remain available to the restarted session.

### Retry Flow

```
Error detected
│
├── Does error match error_patterns? (case-insensitive substring)
│   ├── No  → fail immediately
│   └── Yes → retry_count < max_retries?
│       ├── Yes → wait (wait_times[retry_count]) → retry
│       └── No  → fallback_model configured and not already using fallback?
│           ├── Yes → set fallback model override → retry once
│           └── No  → fail
```

Wait periods are interruptible — if the agent is killed during a wait, it stops
immediately.

### TUI Display

sase's TUI Agents tab reflects retry state (see
[Retry/Fallback Display](../tui/agent-workflows.md#retryfallback-display)):

- **RETRYING (Ns)** — Waiting before the next attempt (bold orange, with countdown)
- **↻N** — Retry count annotation on running agents
- **▸Model** — Fallback model annotation (e.g., `↻3▸flash`)

### Metadata Tracking

If any retries occurred or a fallback model was used, retry metadata is written to
`done.json` in the agent's artifacts directory after execution completes (runs that
succeed on the first attempt omit these fields):

```json
{
  "retry_count": 2,
  "retry_errors": ["An unexpected critical error occurred: ..."],
  "used_fallback": false
}
```

When `used_fallback` is `true`, the metadata also includes the `fallback_model` that
served the final attempt.

Source: `src/sase/llm_provider/retry_config.py`,
`src/sase/axe/run_agent_exec_finalize.py`

### Spawn-on-Retry

When `ProviderRetryConfig.spawn_new_agent=True`, a retryable error spawns a fresh
detached child agent (as if `sase run` had been invoked) instead of running the next
attempt in-process. The failing parent transfers its workspace claim to the child via
`transfer_workspace_claim()` and exits with status `FAILED (RETRIED)`. This trades the
small cost of a fresh process for two benefits:

- The workspace is preserved by design — the child skips `prepare_workspace()` and
  inherits the parent's in-progress edits via the transferred workspace claim. An
  in-process retry runs `prepare_workspace()` between attempts and can remove
  uncommitted file edits unless `preserve_workspace=True`.
- A retry boundary becomes a real process boundary, which is more robust against memory
  leaks, lingering child processes, and stale interpreter state.

**Linkage fields** (written to both `agent_meta.json` and `done.json` so retry chains
are queryable from either side):

| Field                        | Meaning                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `retry_of_timestamp`         | Backward link: the parent agent's run timestamp.                                  |
| `retried_as_timestamp`       | Forward link: the child agent's run timestamp (written on the parent at handoff). |
| `retry_chain_root_timestamp` | The root agent's timestamp — stable across the entire chain.                      |
| `retry_attempt`              | Depth in the chain (1-based).                                                     |

State is carried across the boundary by a `retry_handoff.json` file written to the
parent's artifacts directory; the child reads it before launch.

**Fallback behavior**: spawn-on-retry is opt-in (default `false`). If spawning fails
(e.g. workspace transfer fails), the in-process retry runs as a fallback so the user is
never worse off.

Source: `src/sase/axe/run_agent_retry_spawn.py`, `src/sase/llm_provider/retry_config.py`

## Related

- [Providers and models](index.md) — provider integrations and model routing.
- [Provider configuration](configuration.md) — retry settings.
