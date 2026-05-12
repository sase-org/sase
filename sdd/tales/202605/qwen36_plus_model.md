---
create_time: 2026-05-12 15:06:53
status: done
prompt: sdd/prompts/202605/qwen36_plus_model.md
---
# Plan: Add `qwen3.6-plus` Qwen Model Routing

## Goal

Make `%model:qwen3.6-plus` automatically select the `qwen` provider, and change Qwen's default `large` tier model to
`qwen3.6-plus`.

## Scope

- Update the Qwen provider metadata so `qwen3.6-plus` is a known Qwen model.
- Update Qwen's tier-to-model mapping so `large` resolves to `qwen3.6-plus`.
- Keep the existing Qwen small tier unchanged.
- Add or adjust focused tests around Qwen default model resolution and implicit provider resolution.
- Update user-facing model documentation if it enumerates Qwen defaults or automatic provider mappings.

## Design Notes

SASE's `%model` provider inference is centralized through `sase.llm_provider.registry.resolve_model_provider()`. That
function builds its implicit model map from each registered provider plugin's `llm_known_model_names()` hook. Because
Qwen already owns a plugin-level known-model list, this change should stay inside the Qwen provider metadata rather than
adding special cases to the registry.

The provider's default concrete model for tier-based invocation is separate from provider inference. Qwen currently maps
`large` to `qwen3-coder-plus`; that map should be changed to `qwen3.6-plus`. Existing explicit `%model:qwen3-coder-plus`
behavior should continue to route to Qwen unless there is a deliberate reason to remove the older model from the known
list. There is no such reason in this request.

## Implementation Steps

1. Update `src/sase/llm_provider/qwen.py`:
   - Change `_TIER_TO_MODEL["large"]` to `qwen3.6-plus`.
   - Add `qwen3.6-plus` to `llm_known_model_names()`.
   - Add a short alias if the model-picker/fan-out naming path expects long Qwen models to have stable suffixes.

2. Update tests:
   - Adjust Qwen provider default model expectations from `qwen3-coder-plus` to `qwen3.6-plus`.
   - Add an assertion that `resolve_model_provider("qwen3.6-plus") == ("qwen", "qwen3.6-plus")`.
   - Preserve assertions that older Qwen model names still resolve when appropriate.

3. Update docs:
   - Change the Qwen model tier table's `large` entry.
   - Add `qwen3.6-plus` to the automatic provider resolution table.

4. Verify:
   - Run focused tests for Qwen and provider metadata/model resolution.
   - Because this repo's memory requires it after source changes, run `just check` before reporting completion. If the
     workspace dependencies are stale, run `just install` first as instructed by the workspace memory.
