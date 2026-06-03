---
create_time: 2026-06-03 01:40:34
status: done
prompt: sdd/prompts/202606/codex_transient_retry.md
---
# Plan: Give the Codex Provider Built-In Transient-Failure Retry Coverage

## Diagnosis of Agent `0s`

Agent `0s` (CODEX / `gpt-5.5`) did **not** fail in its planning phase. The artifacts confirm the plan phase fully
succeeded: `agent_meta.json` shows `plan_submitted_at`, `plan_approved: true`, and `plan_committed: true`, and the
`0s--plan` chat transcript shows the plan for `agents_var_namespace.md` was submitted cleanly.

After the plan was approved, SASE resumed the same workflow with the **implementation** prompt (the `main` step). That
second Codex invocation died with provider transport / rate-limit errors (from `error_report.md`):

```
ERROR codex_models_manager::manager: failed to refresh available models: timeout waiting for child process to exit
ERROR codex_api::endpoint::responses_websocket: failed to connect to websocket: HTTP error: 403 Forbidden,
      url: wss://chatgpt.com/backend-api/codex/responses   (x repeated; Reconnecting 2/5 .. 5/5)
[error] exceeded retry limit, last status: 429 Too Many Requests
[turn.failed] exceeded retry limit, last status: 429 Too Many Requests
```

The Codex CLI exhausted **its own** internal 5 reconnect attempts and exited non-zero. In
`src/sase/llm_provider/codex.py`, `CodexProvider.invoke()` then raised `subprocess.CalledProcessError` (line ~356) the
instant `return_code != 0`. Its `while True` loop only re-runs on a _user interrupt_, never on a transient provider
failure, so the error propagated up as `LLMInvocationError` and the workflow step terminated.

### Root cause

SASE already has a retry subsystem (`get_retry_config()` / `find_retry_config_for_error()` / `handle_workflow_error()`)
that recovers from configured provider errors and writes `retry_state.json`. Recovery is driven by per-provider retry
config assembled from two layers:

1. **Built-in defaults** exposed through the `llm_default_retry_config` hook — e.g. `ClaudeProvider`
   (`src/sase/llm_provider/claude.py:94`) returns patterns like `"Prompt is too long"` and
   `"socket connection was closed unexpectedly"`.
2. **User / shipped defaults** under `llm_provider.retry.<provider>` in `src/sase/default_config.yml` (entries exist
   today for `gemini` and `claude`), which merge on top of the built-ins.

**The Codex provider has neither.** `grep` confirms `codex.py` does not implement `llm_default_retry_config`, and
`default_config.yml` has no `codex:` retry entry. So a Codex transient failure matches _no_ retry config,
`find_retry_config_for_error()` returns `None`, and `handle_workflow_error()` treats it as terminal — which is exactly
the absence of any `retry_state.json` in the `0s` artifacts. Claude and Gemini would have survived the same class of
blip; Codex agents fall over. This is a coverage gap, not a Codex-specific quirk, and the fix must keep all runtimes
uniform (per `memory/short/gotchas.md` — "Uniform Agent Runtimes").

> **Note on overlap:** A sibling agent (`0u`) already drafted `sdd/tales/202606/codex_provider_retry.md` for this same
> gap, and an implementation run for it was itself killed by the _same_ Codex 429 storm — underscoring how live the gap
> is. This plan is the independent diagnosis the user requested for `0s`; if `codex_provider_retry` lands first, this
> collapses into a verification/no-op. The chosen approach below is deliberately consistent with that tale so the two
> converge rather than conflict.

## Goals

- A Codex agent that hits a transient transport/rate-limit failure (the `0s` failure mode) is **retried with backoff**
  by the existing retry subsystem instead of terminating the workflow.
- Coverage ships **out of the box** (no user config required), matching how Claude already behaves.
- Behavior stays **uniform across runtimes** — reuse the existing hook + config plumbing; add no Codex-specific branch
  in the runner.
- Avoid over-matching: a genuine, persistent auth failure must not be retried forever.

## Approach

Add a built-in `CodexProvider.llm_default_retry_config()` that returns a `ProviderRetryConfig`, mirroring
`ClaudeProvider`. This is the canonical, runtime-uniform place — it plugs straight into `_built_in_defaults()` in
`retry_config.py` and is automatically merged with any user overrides.

Design choices for the returned config:

- **`error_patterns`** — match the _observed terminal_ and _transient transport_ wording, scoped tightly:
  - `"exceeded retry limit"` — the Codex CLI's own give-up message.
  - `"429 Too Many Requests"` / `"Too Many Requests"` — the final rate-limit status.
  - `"rate limit"` — nearby rate-limit phrasing.
  - `"failed to connect to websocket"` — the transient transport error.
  - Deliberately **not** a bare `"403 Forbidden"`, so a persistent credential/authorization failure is not turned into
    an infinite retry. (Matching is case-insensitive substring per `is_retryable_error()`.)
- **`max_retries`** — small finite count (propose `3`), consistent with Claude/Gemini.
- **`wait_times`** — backoff schedule appropriate for rate limiting; propose `[60, 300, 1800]` to match the shipped
  Gemini/Claude cadence in `default_config.yml` (rate limits need real cool-down, unlike Claude's built-in `[0]` which
  targets context-length errors). Final value to be confirmed during implementation.
- **`continuation_prompt`** — reuse `_RETRY_CONTINUATION_NUDGE` so a retried implementation turn inspects current disk
  state (`git status` / `git diff`) before continuing.
- **`preserve_workspace=True`** — never wipe edits made before the provider blip.

Decide during implementation whether to _also_ add a parallel `codex:` block to `default_config.yml` for
discoverability/symmetry with `gemini`/`claude`. Leaning **yes** for consistency, since users browse that file to learn
what is tunable; the merge logic (`_merge_with_built_in`) handles both layers coexisting cleanly. The built-in hook
remains the source of truth for zero-config coverage either way.

## Implementation Sketch

1. **`src/sase/llm_provider/codex.py`** — add `@hookimpl def llm_default_retry_config(self) -> ProviderRetryConfig`,
   importing `_RETRY_CONTINUATION_NUDGE` and `ProviderRetryConfig` from `.retry_config` (local import, as Claude does,
   to avoid import cycles). Update `CodexProvider.invoke()`'s docstring `Raises:` note if appropriate.
2. **`src/sase/default_config.yml`** (pending the decision above) — add a `codex:` entry under `llm_provider.retry:`
   mirroring the chosen patterns/waits.
3. **`tests/test_llm_provider_retry_config.py`** — add regression tests proving:
   - `get_retry_config("codex")` returns a built-in config when no user config is present.
   - The literal `0s` failure text (websocket 403 + `exceeded retry limit` + `429 Too Many Requests`) is matched by
     `is_retryable_error()` / discovered by `find_retry_config_for_error()`.
   - A persistent generic `403 Forbidden` auth string that lacks rate-limit wording does **not** match (guards against
     over-matching).
   - User config still merges with and can override the Codex built-in (same semantics as existing providers).
4. **Docs** — refresh the provider/retry references in `docs/llms.md` / `docs/plugins.md` if they enumerate which
   providers ship built-in retry coverage.

## Validation

- `pytest tests/test_llm_provider_retry_config.py`
- `just check` (required after source edits per `memory/short/build_and_run.md`; run `just install` first because this
  is an ephemeral workspace).

## Non-Goals

- Do **not** modify `0s`'s historical artifacts, chat transcripts, or memory files.
- Do **not** add a Codex-specific branch in the runner / workflow executor — recovery must flow through the existing
  uniform retry plumbing.
- Do **not** retry every `403 Forbidden`; only the explicit rate-limit status and Codex transport wording observed.
- Do **not** change the Codex CLI's own internal reconnect behavior (it lives in the upstream `codex` binary, outside
  this repo).

## Backend Boundary Note

This change is presentation/glue-adjacent provider configuration in the Python repo (retry policy for the local CLI
subprocess), not shared cross-frontend domain logic, so it stays here in `sase` rather than `../sase-core` per
`memory/short/rust_core_backend_boundary.md`. If implementation reveals the retry-matching itself lives behind the Rust
core boundary, escalate before editing core.
