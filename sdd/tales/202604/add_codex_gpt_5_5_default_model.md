---
create_time: 2026-04-24 16:11:59
status: done
prompt: sdd/prompts/202604/add_codex_gpt_5_5_default_model.md
---
# Plan: Add Codex `gpt-5.5` Support and Make It the Default

## Problem Statement

Sase currently pins Codex's large-tier default to `gpt-5.3-codex` in `src/sase/llm_provider/codex.py`, and tests/docs
are aligned to that value. We need to add support for OpenAI's new `gpt-5.5` model and make it the default model used by
the Codex provider.

## Goals

1. Set Codex large-tier default model to `gpt-5.5`.
2. Ensure `%model:gpt-5.5` is recognized as a Codex model for automatic provider resolution.
3. Keep existing Codex small-tier behavior unchanged (`codex-mini-latest`).
4. Update tests and docs so behavior is explicit and validated.
5. Avoid regressions in model picker/provider routing and agent metadata display.

## Non-Goals

1. Changing provider auto-detect priority (still `claude -> codex -> gemini`).
2. Changing fallback/retry defaults.
3. Reworking tier semantics (`large`/`small`) or CLI flags.
4. Refactoring the broader `llm_provider.model_tier_map` config behavior.

## Assumptions / Decision to Confirm

1. **Canonical model identifier** is assumed to be `gpt-5.5` (as requested), not `gpt-5.5-codex`.
2. If validation shows Codex CLI expects a different canonical ID, we should switch to that ID everywhere in this plan.

## Impacted Areas

1. **Codex provider defaults and known model names**

- `src/sase/llm_provider/codex.py`

2. **Provider-resolution and model-list tests**

- `tests/test_llm_provider_codex.py`
- `tests/test_llm_provider_core.py`
- `tests/test_model_picker_modal.py` (indirectly validates known-model surface)

3. **User-facing docs**

- `docs/llms.md` (Codex model mapping + known model table)
- `docs/configuration.md` (if codex default examples/reference text mentions old default)

## Implementation Plan

### Phase 1: Update Codex Default and Model Registry Surface

1. In `src/sase/llm_provider/codex.py`, change `_TIER_TO_MODEL["large"]` from `gpt-5.3-codex` to `gpt-5.5`.
2. In `llm_known_model_names()`, add `gpt-5.5` and keep existing aliases/models intact for backwards compatibility.
3. Keep small tier as `codex-mini-latest` to avoid scope creep.

### Phase 2: Update and Expand Test Coverage

1. Update `tests/test_llm_provider_codex.py` assertions to expect `gpt-5.5` as the resolved large-tier model and command
   argument.
2. Update `tests/test_llm_provider_core.py` implicit resolution test to assert
   `resolve_model_provider("gpt-5.5") == ("codex", "gpt-5.5")`.
3. Keep existing assertions for `o3`, `gpt-5.3-codex`, and other models so we preserve compatibility and avoid
   accidental removals.
4. Confirm `tests/test_model_picker_modal.py` still passes (the picker reads from `model_to_provider_map()`), ensuring
   the new model appears in selectable known models.

### Phase 3: Documentation Alignment

1. Update `docs/llms.md` Codex Model Mapping table (`large` tier now `gpt-5.5`).
2. Update `docs/llms.md` known model names table to include `gpt-5.5` under Codex.
3. Sweep `docs/configuration.md`/other docs for stale references to `gpt-5.3-codex` and update where appropriate.

### Phase 4: Validation

1. Run targeted tests first:

- `tests/test_llm_provider_codex.py`
- `tests/test_llm_provider_core.py`
- `tests/test_model_picker_modal.py`

2. Run broader provider tests:

- `tests/test_llm_provider_providers.py`
- optionally `tests/test_llm_provider_invoke.py` if touched behavior is transitively involved.

3. Run repo-required checks after file changes:

- `just check`

## Risks and Mitigations

1. **Wrong canonical model ID** (`gpt-5.5` vs provider-specific variant):

- Mitigation: verify accepted model ID during implementation; if needed, standardize on the accepted ID and document it.

2. **Breaking implicit provider resolution for legacy IDs**:

- Mitigation: add new model without removing existing known model entries.

3. **Doc/test drift**:

- Mitigation: include docs in same change and run targeted tests before full `just check`.

## Rollout / Verification Criteria

Change is complete when all of the following are true:

1. `CodexProvider.resolve_model_name("large")` returns `gpt-5.5`.
2. A default Codex invocation uses `--model gpt-5.5`.
3. `%model:gpt-5.5` resolves to provider `codex` without explicit `codex/...` prefix.
4. Updated docs reflect `gpt-5.5` as Codex large-tier default.
5. `just check` passes.
