---
create_time: 2026-06-03 01:32:24
status: wip
prompt: sdd/prompts/202606/codex_provider_retry.md
---
# Plan: Add Built-In Codex Retry Handling

## Problem

Agent `0s` did not fail because its plan submission was invalid. The plan step completed and wrote
`/home/bryan/.sase/plans/202606/agents_var_namespace.md`. After the plan was approved, SASE resumed the same workflow
with the implementation prompt. That Codex invocation then failed with repeated provider transport/rate-limit errors:

- `failed to connect to websocket: HTTP error: 403 Forbidden`
- `exceeded retry limit, last status: 429 Too Many Requests`
- `[turn.failed] exceeded retry limit, last status: 429 Too Many Requests`

The agent artifacts have no `retry_state.json` and no retry metadata in `done.json`, so the runner treated this as a
terminal workflow error. The root cause is that SASE's retry subsystem can recover from configured provider errors, but
the Codex provider currently has no built-in retry config. Claude has a provider-supplied default for context and
transient provider failures, and Gemini has defaults in `default_config.yml`; Codex lacks equivalent coverage for common
CLI/API transient failures.

## Approach

Add a Codex provider default retry config through the existing `llm_default_retry_config` hook instead of adding a new
runtime-specific branch in the runner. This keeps retry behavior uniform across providers and lets existing
`get_retry_config()` / `find_retry_config_for_error()` / `handle_workflow_error()` code do the work.

The Codex retry config should:

- Match the observed terminal error (`429 Too Many Requests`) and nearby rate-limit wording (`Too Many Requests`,
  `rate limit`, `exceeded retry limit`).
- Match transient Codex websocket/transport wording (`failed to connect to websocket`) without turning every generic
  authentication failure into a retry.
- Include the existing continuation nudge so a retried implementation turn checks current disk state before continuing.
- Set `preserve_workspace=True` so SASE does not wipe edits made before a provider failure.
- Use a small finite retry count and wait schedule consistent with existing SASE retry semantics.

## Implementation

1. Add `CodexProvider.llm_default_retry_config()` in `src/sase/llm_provider/codex.py`.
2. Reuse `_RETRY_CONTINUATION_NUDGE` and `ProviderRetryConfig` from `sase.llm_provider.retry_config`.
3. Add regression tests in `tests/test_llm_provider_retry_config.py` showing:
   - `get_retry_config("codex")` returns a built-in config when user config is absent.
   - The observed `0s` failure text matches Codex's default retry patterns.
   - `find_retry_config_for_error()` can discover the Codex built-in config from an arbitrary workflow error.
   - User config still merges with and can override built-in Codex values in the same way as existing providers.
4. Run targeted retry tests first, then the repository check required after source edits.

## Validation

- `pytest tests/test_llm_provider_retry_config.py`
- `just check`

## Non-Goals

- Do not modify the `0s` historical artifacts or memory files.
- Do not add runner special cases for Codex.
- Do not retry every `403 Forbidden`; only match the Codex websocket/transport wording and the explicit final rate-limit
  status observed in this failure.
