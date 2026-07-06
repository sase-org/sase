---
create_time: 2026-07-06 12:52:30
status: done
prompt: sdd/prompts/202607/provider_coder_alias_fallback.md
---
# Plan: Fix provider coder aliases so they inherit @coder

## Problem

The Models panel shows unconfigured `<provider>_coder` aliases such as `agy_coder`, `opencode_coder`, and `qwen_coder`
as resolving through `@default`. They are supposed to inherit the generic `@coder` alias, so a user can configure
`llm_provider.model_aliases.builtin.coder` once and have all unconfigured provider-specific coder follow-up lanes use
that value.

## Diagnosis

The model-alias policy lives in `sase.llm_provider.config`. The relevant runtime path is:

- plan approval emits `%model:@<planner_provider>_coder` for coder follow-ups
- `resolve_model_provider()` calls `resolve_model_alias()`
- `resolve_model_alias()` handles implicit special aliases

The root cause is in the implicit provider-coder branch of `resolve_model_alias()`: when an alias is a registered
`<provider>_coder` and is not explicitly configured, the code assigns its fallback to
`_ROLE_ALIAS_FALLBACKS[CODER_MODEL_ALIAS_NAME]`. That value is `@default`. This accidentally skips the `coder` alias
itself. It works only in the trivial case where `coder` is also implicit, but it breaks as soon as `coder` is
configured.

The Models panel is accurately surfacing that current behavior, and its state label also hard-codes all implicit
non-default aliases as `implicit -> @default`. After the runtime fix, provider-coder rows should communicate their real
implicit chain as `implicit -> @coder`.

## Implementation Plan

1. Update the implicit provider-coder fallback in `resolve_model_alias()` so an unconfigured `<provider>_coder` alias
   references `@coder`, not the resolved fallback of `coder`.

2. Keep explicit alias precedence unchanged:
   - `llm_provider.model_aliases.builtin.claude_coder` or a custom alias with the same name must still shadow the
     implicit provider-coder behavior.
   - temporary overrides on the provider-coder alias must still win before any configured or implicit chain is followed.

3. Update Models panel provenance rendering so:
   - implicit `default` remains `implicit`
   - implicit fixed role aliases such as `coder`, `epic_creator`, `epic_lander`, and `phase_worker` remain
     `implicit -> @default`
   - implicit provider-coder aliases show `implicit -> @coder`
   - configured and overridden aliases keep their existing labels

4. Add focused regression coverage:
   - `resolve_model_alias("<provider>_coder")` follows a configured `coder` alias when the provider-specific alias is
     absent.
   - an explicitly configured `<provider>_coder` continues to shadow the generic `coder` alias.
   - `build_alias_views()` reports the effective provider/model for an unconfigured provider-coder alias via configured
     `coder`, matching what the Models panel displays.
   - the Models panel state tag for an implicit provider-coder alias says `implicit -> @coder`.

5. Run focused tests first:
   - `tests/llm_provider/test_config_aliases.py`
   - `tests/llm_provider/test_alias_view.py`
   - `tests/test_models_panel.py`
   - `tests/test_axe_run_agent_exec_plan_followup_model_selection.py`

6. Because this changes files in the repo, run the required repo check:
   - `just install`
   - `just check`

## Expected Outcome

With `coder` configured to a non-default model and a provider-specific coder alias left unset, both launches and the
Models panel should resolve the provider-specific alias through `@coder`. Existing configured provider-specific aliases,
temporary overrides, and the generic default model alias should keep their current behavior.
