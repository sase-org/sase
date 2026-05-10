---
create_time: 2026-05-09 22:30:36
status: done
prompt: sdd/prompts/202605/other_model_alias.md
---
# Plan: Configured `other` Model Alias

## Goal

Add first-class support for a configurable secondary model alias in `sase.yml`, so prompts can use `%model:other` or
`%m:other` instead of hard-coding a concrete model. This lets reusable multi-agent xprompts select the user's current
secondary model at agent launch time.

Also update the user's chezmoi-managed SASE config so `other` resolves to Claude Opus.

## Current Behavior

- `%model:<value>` is parsed into `PromptDirectives.model`.
- Invocation and metadata paths call `resolve_model_provider(<value>)`.
- `resolve_model_provider()` supports explicit `provider/model` syntax and known provider model names, then falls back
  to the default provider.
- Multi-model fan-out naming uses the same provider-resolution path for suffixes.
- The user's current chezmoi config works around aliases through xprompts such as `#m_opus_codex`, but that requires
  explicit xprompt expansion (`%model:#codex`) and does not allow `%model:other`.

## Proposed Config Shape

Add a config-backed model alias map under `llm_provider`:

```yaml
llm_provider:
  model_aliases:
    other: claude/opus
```

Rationale:

- This keeps the feature general without creating one-off `other_model` plumbing.
- The config still explicitly supports the requested `other` model.
- Values can be bare known models (`opus`), explicit provider/model strings (`claude/opus`), or nested provider model
  paths (`opencode/anthropic/claude-sonnet-4-5`).
- Future aliases such as `fast`, `review`, or `cheap` can use the same mechanism without another schema change.

## Implementation

1. Add LLM model alias resolution helpers in the provider layer.
   - Read `llm_provider.model_aliases` from merged config.
   - Normalize keys and values by stripping whitespace.
   - Ignore non-string keys/values defensively.
   - Resolve aliases recursively with cycle detection and a small depth cap.
   - Preserve current behavior for unknown aliases/models.

2. Integrate aliases into provider resolution.
   - Teach `resolve_model_provider()` to resolve configured aliases before explicit provider/model and known-model
     lookup.
   - Keep the return shape unchanged: `(provider | None, provider_local_model)`.
   - For `other: claude/opus`, `%model:other` should resolve to `("claude", "opus")`.
   - For `other: opus`, `%model:other` should resolve through known-model metadata to `("claude", "opus")`.

3. Integrate aliases into fan-out naming.
   - Update `_model_value_for_naming()` to resolve configured aliases after xprompt shorthand expansion.
   - This ensures `%m(other,gpt-5.5)` produces stable suffixes based on the concrete configured model, not the literal
     word `other`.
   - The launched prompt can still contain `%model:other`; concrete resolution happens at launch time.

4. Update schemas and docs.
   - Extend `config/sase.schema.json` with `llm_provider.model_aliases`.
   - Document the field in `docs/configuration.md` and `docs/llms.md`.
   - Note that aliases are launch-time defaults, and explicit provider/model strings remain supported in alias values.

5. Add tests.
   - Unit-test alias loading/cleanup/cycle behavior.
   - Unit-test `resolve_model_provider("other")` for explicit and bare alias values.
   - Unit-test invocation metadata path enough to prove the provider receives the resolved model override.
   - Unit-test multi-model fan-out naming for `%m(other,gpt-5.5)` with `other: claude/opus`.

6. Update the user's chezmoi config.
   - Edit `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`.
   - Add:

     ```yaml
     llm_provider:
       model_aliases:
         other: claude/opus
     ```

   - Preserve existing snippets and xprompts.

## Validation

- Run focused pytest targets for provider resolution, invocation, directive splitting, and config/schema behavior.
- Run `just install` first if the workspace environment needs it.
- Run `just check` in this SASE repo because code/docs/config files will change.
- Run `just check` in `/home/bryan/.local/share/chezmoi` because that repo will change.
- Do not run `chezmoi apply --force` unless the user asks for a commit/apply flow; the memory requires it after
  committing, not after an uncommitted edit.

## Compatibility and Risks

- Existing concrete model names keep their current semantics.
- Existing xprompt aliases continue to work because xprompt expansion still happens before directive extraction.
- Alias values that point to unknown bare models continue to run on the current default provider, matching existing
  `%model` fallback behavior.
- Cycles should not crash launches; cyclic aliases fall back to the raw input after detection.
- The schema addition is non-breaking because `model_aliases` is optional.
