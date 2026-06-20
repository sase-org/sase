---
create_time: 2026-06-19 22:37:25
status: done
prompt: sdd/prompts/202606/chezmoi_agy_xprompts.md
---
# Chezmoi Antigravity Xprompt Cleanup Plan

## Context

The chezmoi source for the global SASE config is `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`. Its
live target `~/.config/sase/sase.yml` is currently byte-identical, but not a symlink.

The current model-related xprompts still contain legacy Gemini CLI targets:

- `flash: "gemini/gemini-3.5-flash"`
- `pro: "gemini-3.1-pro-preview"`
- `gem: "#pro"`
- `%model` wrappers such as `m_flash`, `m_pro`, `m_pro_flash`, `m_swarm`, and `m_jet_pro_flash` depend on those stale
  aliases.

SASE now has a bundled Antigravity provider named `agy`. Its exact model names contain spaces and parentheses, for
example `Gemini 3.5 Flash (High)`, and SASE's provider docs warn that prompt text is sent to `agy --print` via argv with
a 120 KiB pre-spawn guard.

## Goals

1. Remove the stale Gemini CLI provider/model strings from the global xprompt aliases.
2. Add readable Antigravity-backed model aliases and xprompts for the useful `agy` models.
3. Preserve muscle-memory aliases (`#gem`, `#pro`, `#flash`, `#m_pro`, `#m_flash`, `#m_pro_flash`, `#m_swarm`) while
   making their targets current.
4. Keep the default provider (`codex`) and existing worker model policy unchanged.
5. Validate parsing and expansion without launching any real LLM provider.

## Proposed Changes

### 1. Add Antigravity model aliases

In `llm_provider.model_aliases`, keep the existing `other: claude/opus` entry and add simple alias names for Antigravity
models. These aliases avoid embedding space-and-parenthesis model names directly inside `%model(...)` fanout syntax.

Planned aliases:

- `agy_flash` -> `agy/Gemini 3.5 Flash (High)`
- `agy_flash_high` -> `agy/Gemini 3.5 Flash (High)`
- `agy_flash_mid` -> `agy/Gemini 3.5 Flash (Medium)`
- `agy_flash_low` -> `agy/Gemini 3.5 Flash (Low)`
- `agy_pro` -> `agy/Gemini 3.1 Pro (High)`
- `agy_pro_low` -> `agy/Gemini 3.1 Pro (Low)`
- `agy_sonnet` -> `agy/Claude Sonnet 4.6 (Thinking)`
- `agy_opus` -> `agy/Claude Opus 4.6 (Thinking)`
- `agy_gptoss` -> `agy/GPT-OSS 120B (Medium)`

I will not rely on provider display short aliases such as `flash35h` in the dotfile config, because configured model
aliases are the stable launch-time mechanism for `%model`.

### 2. Replace stale Gemini xprompt targets

In the `xprompts` model section, replace legacy Gemini targets with Antigravity-backed aliases:

- `flash` -> `#agy_flash`
- `pro` -> `#agy_pro`
- `gem` -> `#agy`

Add canonical Antigravity xprompt fragments:

- `agy` -> `agy_flash`
- `agy_flash` -> `agy_flash`
- `agy_flash_high` -> `agy_flash_high`
- `agy_flash_mid` -> `agy_flash_mid`
- `agy_flash_low` -> `agy_flash_low`
- `agy_pro` -> `agy_pro`
- `agy_pro_low` -> `agy_pro_low`
- `agy_sonnet` -> `agy_sonnet`
- `agy_opus` -> `agy_opus`
- `agy_gptoss` -> `agy_gptoss`

Optionally add `gemini -> #agy` as a readable compatibility alias if it fits the nearby naming style during
implementation.

### 3. Add and update `%model` helper xprompts

Add direct Antigravity `%model` wrappers:

- `m_agy` -> `%model:#agy`
- `m_agy_flash` -> `%model:#agy_flash`
- `m_agy_flash_mid` -> `%model:#agy_flash_mid`
- `m_agy_flash_low` -> `%model:#agy_flash_low`
- `m_agy_pro` -> `%model:#agy_pro`
- `m_agy_pro_low` -> `%model:#agy_pro_low`
- `m_agy_sonnet` -> `%model:#agy_sonnet`
- `m_agy_opus` -> `%model:#agy_opus`
- `m_agy_gptoss` -> `%model:#agy_gptoss`

Update existing compatibility wrappers:

- `m_flash` -> `#m_agy_flash`
- `m_pro` -> `#m_agy_pro`
- `m_pro_flash` -> `#m_agy_pro_flash`
- `m_swarm` -> `%model(opus, #codex, #agy)`

Add useful fanout helpers:

- `m_agy_pro_flash` -> `%model(#agy_pro, #agy_flash)`
- `m_jet_agy` -> `#m_jet #m_agy_pro_flash`
- `m_jet_pro_flash` -> `#m_jet_agy` for backwards compatibility

### 4. Keep unrelated Antigravity/Gemini files alone

Do not modify the generated skill directories under `dot_gemini/antigravity-cli/skills/`, `dot_gemini/skills/`, or
`dot_gemini/jetski/skills/`. The `.gemini/antigravity-cli` path is already the documented Antigravity skill deployment
path, so this task should stay scoped to global SASE config xprompt/model aliases unless validation reveals a direct
conflict.

## Implementation Steps

1. Edit only `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml` for the alias/xprompt changes above.
2. Keep the existing YAML layout and comments, but rename the stale `# models` section comment if needed so it reflects
   provider/model presets rather than Gemini specifically.
3. Run a source-vs-target preview with: `chezmoi diff ~/.config/sase/sase.yml`
4. Run a dry apply check: `chezmoi apply --dry-run --verbose ~/.config/sase/sase.yml`
5. If the dry run is clean, apply that one file so SASE's live config matches the chezmoi source:
   `chezmoi apply ~/.config/sase/sase.yml`

## Validation

After applying the config target, validate without launching an LLM:

1. `sase config show -k llm_provider`
   - Confirms the new `model_aliases` are present and default provider remains `codex`.
2. `sase xprompt list`
   - Confirms new xprompt names exist and no duplicate/collision error occurs.
3. `sase xprompt expand -t '#m_agy'`
4. `sase xprompt expand -t '#m_agy_pro_flash'`
5. `sase xprompt expand -t '#m_pro_flash'`
6. `sase xprompt expand -t '#m_swarm'`
   - Confirms compatibility aliases expand through the new Antigravity aliases.
7. Use the SASE repo venv to probe resolver behavior for representative aliases:
   `.venv/bin/python - <<'PY' ... resolve_model_provider('agy_flash') ... PY`
   - Confirms aliases resolve to provider `agy` and exact Antigravity model names.
8. `sase doctor -C llm.registry -v`
   - Confirms the LLM registry still sees the `agy` provider and known model metadata.
9. `git -C /home/bryan/.local/share/chezmoi diff --check`
   - Confirms whitespace is clean.
10. `git -C /home/bryan/.local/share/chezmoi status --short --branch`
    - Summarizes the final chezmoi repo state.

## Risks and Mitigations

- Antigravity exact model names include spaces and parentheses, which can make multi-model directives fragile if pasted
  directly. Mitigation: use `llm_provider.model_aliases` and make xprompts expand to simple alias tokens.
- Existing prompts may rely on `#gem`, `#pro`, or `#flash`. Mitigation: keep those aliases and repoint them instead of
  removing them.
- Live SASE validation reads `~/.config/sase/sase.yml`, not the chezmoi source file directly. Mitigation: use
  `chezmoi apply --dry-run` before applying only the changed SASE config target.
- `agy` has an argv prompt-size guard and no structured artifact parity yet. Mitigation: this plan only changes
  model-routing conveniences; it will not add xprompts that encourage huge prompt payloads or depend on `agy` tool-call
  or usage artifacts.
