---
create_time: 2026-06-28 12:52:00
status: done
prompt: sdd/prompts/202606/agy_model_alias_routing.md
---
# Plan: Restore Antigravity model xprompt routing

## Problem

Prompts such as `#m_agy_flash` and `%model:#agy_flash` currently route to Codex on this machine instead of Antigravity.
The observed chain is:

1. `#m_agy_flash` expands to `%model:#agy_flash`.
2. `%model:#agy_flash` extracts the model directive and expands the directive argument to `agy_flash`.
3. `agy_flash` is no longer present in `llm_provider.model_aliases`.
4. `resolve_model_provider("agy_flash")` returns no provider, so SASE falls back to the configured default provider.
5. The machine overlay sets `llm_provider.provider: codex`, so the launch is recorded and run as Codex with model
   override `agy_flash`.

This is not primarily a failure to expand `#agy_flash`; it is an inconsistent config state. The Antigravity model
xprompts still point at alias tokens that were removed by the chezmoi commit `chore: Remove anti-gravity model aliases.`

## Goals

- Make the existing `#agy_*` and `#m_agy_*` xprompts route to the Antigravity provider again.
- Preserve the readable xprompt/token surface (`#agy_flash`, `#m_agy_flash`, fanouts such as `#m_pro_flash`).
- Add a regression guard so configured `%model:#xprompt` presets cannot silently degrade to the default provider when
  their expanded model token is unknown.
- Keep the change provider-neutral; do not add Codex-vs-Antigravity special cases in launch code.

## Implementation

1. Repair Bryan's SASE config source in chezmoi.
   - Restore the removed `llm_provider.model_aliases` entries in `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`:
     - `agy_flash`, `agy_flash_high` -> `agy/Gemini 3.5 Flash (High)`
     - `agy_flash_mid` -> `agy/Gemini 3.5 Flash (Medium)`
     - `agy_flash_low` -> `agy/Gemini 3.5 Flash (Low)`
     - `agy_pro` -> `agy/Gemini 3.1 Pro (High)`
     - `agy_pro_low` -> `agy/Gemini 3.1 Pro (Low)`
     - `agy_sonnet` -> `agy/Claude Sonnet 4.6 (Thinking)`
     - `agy_opus` -> `agy/Claude Opus 4.6 (Thinking)`
     - `agy_gptoss` -> `agy/GPT-OSS 120B (Medium)`
   - Apply the same config to the live generated `~/.config/sase/sase.yml` via the normal chezmoi path, not by
     hand-editing divergent live state.

2. Add SASE regression coverage for the resolved behavior.
   - Extend provider/config tests to cover an alias token that points at `agy/<exact display name>`.
   - Add a metadata-level test for `%model:#agy_flash` with a mocked config containing the restored alias and a Codex
     default provider; assert metadata records `llm_provider: agy` and the exact Antigravity display model.
   - Add a negative test showing that an unknown expanded model token still follows the existing documented fallback
     behavior, unless we choose to add stricter validation separately.

3. Add a config consistency guard.
   - Prefer a read-only doctor warning or validation helper over changing launch semantics: scan configured xprompts
     whose content is a `%model` directive or expands into one, resolve directive arguments through the
     xprompt/directive path, and warn when the final model token is neither a configured alias, an explicit
     provider/model, nor a known provider model.
   - The warning should point at the xprompt name and final unresolved token, e.g.
     `m_agy_flash -> agy_flash does not resolve to a provider; it will fall back to the default provider`.
   - Keep this generic so it catches `#m_fable`, `#m_qwen`, or plugin-provided model presets too.

4. Update documentation only if needed.
   - The docs already say provider short aliases are display-only and unknown model values fall back to the default
     provider. If the guard is added, add a short note to the config/doctor docs describing the new warning.

## Validation

- Run focused tests for model alias resolution, Antigravity metadata routing, and the new config guard.
- Run `just install` before repo checks if the ephemeral environment has not been prepared.
- Run `just check` for SASE repo changes.
- Verify live behavior with:
  - `sase xprompt expand '#m_agy_flash\nDo work'` still strips the directive from the final prompt.
  - A metadata/directive dry-run or focused test confirms `%model:#agy_flash` resolves to provider `agy`, model
    `Gemini 3.5 Flash (High)`.
  - `sase doctor -C llm.default -C <new-config-check>` no longer reports the unresolved `agy_*` model presets.

## Risks

- The live config is generated from chezmoi; editing only `~/.config/sase/sase.yml` would be temporary and likely
  overwritten.
- Making unknown model tokens hard errors would be a behavior change because the docs explicitly describe fallback to
  the default provider. The safer first step is a doctor/config warning plus tests for the intended Antigravity aliases.
- Antigravity display names contain spaces and parentheses, so the restored aliases should keep using quoted explicit
  `agy/...` targets rather than trying to place those display names directly in colon-form `%model:` directives.
