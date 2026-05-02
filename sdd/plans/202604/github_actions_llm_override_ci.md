---
create_time: 2026-04-30 01:52:07
status: done
prompt: sdd/prompts/202604/github_actions_llm_override_ci.md
---
# Diagnose and Fix Temporary LLM Override CI Drift

## Problem

GitHub Actions reports four failures in temporary LLM override tests. Every failure expects the default provider to be
`claude`, but the observed provider is `gemini`.

The affected tests cover these cases:

- Unknown bare model override should fall back to the current default provider.
- `get_default_provider_name()` should fall through to the default when there is no active override.
- Expired overrides should be ignored and fall through to the default.
- Agent metadata after clearing an override should record the default provider.

## Root Cause

`get_default_provider_name()` intentionally uses runtime auto-detection when `llm_provider.provider` is unset:

1. Active temporary override.
2. Configured `llm_provider.provider`.
3. CLI auto-detection by plugin priority: `claude` if `claude` is on `PATH`, then `codex`, then `gemini`.

The failing tests assume the test environment's auto-detected default is always `claude`. That is true on a developer
machine with the Claude CLI installed, but false in CI when `claude` is absent. Gemini is the built-in always-eligible
fallback, so CI correctly resolves `gemini` under the current production code.

This is test-environment coupling, not a feature regression in temporary override precedence.

## Fix Plan

1. Reproduce and isolate the failure mode.
   - Run the affected tests locally.
   - Add a targeted reproduction by patching provider auto-detection so `claude` is unavailable and confirming the old
     expectations drift to `gemini`.

2. Make the temporary override tests deterministic.
   - For tests that specifically need default-provider fallback to be `claude`, patch
     `sase.llm_provider.registry.get_llm_provider_config` to return `{"provider": "claude"}`.
   - Patch the same lookup in `sase.llm_provider.temporary_override` where `set_temporary_override()` imports
     `get_default_provider_name` and falls back for unknown bare models.
   - Prefer local pytest fixtures/helpers over changing production auto-detection semantics.

3. Preserve production behavior.
   - Do not change `get_default_provider_name()` precedence or Gemini fallback behavior.
   - Do not force Claude globally in `tests/conftest.py`, because registry tests explicitly cover auto-detection and
     Gemini fallback.

4. Add or adjust tests only where they assert a deterministic configured default.
   - Update comments that currently say the test environment default is `claude` via auto-detection, since that is the
     fragile assumption.
   - If useful, add a small test proving unknown bare models use a configured provider, not whichever CLI is installed.

5. Verify.
   - Run the affected temporary override tests.
   - Run the broader LLM provider tests that cover registry auto-detection.
   - Run `just check` before final response, per repo instructions.

## Expected Outcome

The temporary override tests no longer depend on CI's installed CLIs. Production default resolution remains unchanged:
without config, a machine lacking `claude` will still fall through to `codex` or `gemini` according to provider
auto-detection.
