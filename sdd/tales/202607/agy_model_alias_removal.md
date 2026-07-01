---
create_time: 2026-07-01 07:35:23
status: done
prompt: sdd/prompts/202607/agy_model_alias_removal.md
---
# Plan: Remove the hacky `agy` / `agy_pro` model aliases in favor of quoted `%model` arguments

## Motivation

The user's chezmoi `sase.yml` (`~/.local/share/chezmoi/home/dot_config/sase/sase.yml`) carries a layered workaround for
Antigravity (`agy`) models whose exact display names contain **spaces and parentheses** (e.g.
`Gemini 3.5 Flash (High)`):

```yaml
llm_provider:
  model_aliases:
    agy: "agy/Gemini 3.5 Flash (High)"
    agy_pro: "agy/Gemini 3.1 Pro (High)"
xprompts:
  agy: "agy" # string xprompt so `#agy` -> "agy"
  agy_pro: "agy_pro" # string xprompt so `#agy_pro` -> "agy_pro"
  m_agy: "%model:@#agy" # `@#agy` == `@` + expand(`#agy`) == `@agy` -> alias `agy`
  m_agy_pro: "%model:@#agy_pro"
  m_agy_pro_flash: "%{%m:@#agy_pro | %m:@#agy}"
  m_flash: "#m_agy_flash" # DANGLING: `m_agy_flash` is not defined anywhere
  m_swarm: "%{%m:opus | %m:#codex | %m:@#agy}"
  pro: "#agy_pro" # `#pro` -> "agy_pro"
```

The `@#agy` spelling is a **double indirection**: a `model_aliases` entry, _plus_ a string xprompt that exists only to
hold the alias name, _plus_ the `@#` prefix that stitches them together. The user wants to delete this scaffolding and
reference the model directly with a quoted argument:

```
%m("agy/Gemini 3.5 Flash (High)")     # desired
%m(@#agy)                             # current hacky form
```

## Key finding: quoting already works — no directive-parser change is required

The user hypothesized that `%model` directives might not support quoted arguments and that we may need to add such
support. **They already do.** The paren form of `%model` / `%m` accepts single- or double-quoted arguments, including
spaces _and_ parentheses inside the quotes, and this survives the whole pipeline. This was verified end-to-end against
the current code:

- `parse_args()` and `find_matching_paren_for_args()` (`src/sase/xprompt/_parsing_args.py`) already treat quoted spans
  as opaque, so the inner `(High)` parens do not break paren matching, and the outer quotes are stripped from the value.
- `extract_prompt_directives()` (`src/sase/xprompt/directives.py`) turns `%m("agy/Gemini 3.5 Flash (High)")` into
  `directives.model == "agy/Gemini 3.5 Flash (High)"`.
- The `%{...}` fan-out — which is planned in the **Rust core** (`plan_agent_launch_fanout`, called via
  `src/sase/xprompt/_directive_alt.py`) — correctly splits branches that contain the quoted paren form:
  `%{%m:opus | %m:#codex | %m("agy/Gemini 3.5 Flash (High)")}` yields three variants, each resolving to the right model.
- Downstream, `resolve_model_provider("agy/Gemini 3.5 Flash (High)")` returns
  `provider="agy", model="Gemini 3.5 Flash (High)"` — identical to what the `agy` alias resolves to today.
- The read-only doctor guard `config.model_xprompts` (`src/sase/doctor/checks_config.py::_model_preset_tokens` /
  `_model_token_routes`) uses the same extract/split functions and accepts explicit `provider/model` tokens, so the
  rewritten presets stay green.

By contrast, the **colon form genuinely cannot express these names**: `%m:agy/Gemini 3.5 Flash (High)` parses
`model == "agy/Gemini"` and leaks `3.5 Flash (High)` into the prompt body (the colon-arg regex stops at the first
space). That failure is the entire reason the alias scaffolding was introduced — and the quoted paren form is the clean
replacement.

Because the capability already exists, this work is **primarily a chezmoi config refactor**, with optional (recommended)
hardening in the sase repo to lock the behavior in and fix stale docs.

## Scope

### A. Chezmoi config refactor (the core deliverable)

File: `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`

1. **Delete the model aliases** `llm_provider.model_aliases.agy` and `.agy_pro` (and their explanatory comment). Nothing
   outside this file references them (`tmux_ai_window`'s `agy` is the provider CLI name, a separate concept).

2. **Rewrite the model-preset xprompts** to use the direct quoted exact-name form. Because the values now contain double
   quotes, wrap each YAML scalar in **single quotes** so the inner `"` are literal:

   ```yaml
   m_agy: '%model("agy/Gemini 3.5 Flash (High)")'
   m_agy_pro: '%model("agy/Gemini 3.1 Pro (High)")'
   m_agy_pro_flash: '%{%m("agy/Gemini 3.1 Pro (High)") | %m("agy/Gemini 3.5 Flash (High)")}'
   m_swarm: '%{%m:opus | %m:#codex | %m("agy/Gemini 3.5 Flash (High)")}'
   ```

3. **Remove the now-orphaned helper xprompts** `agy`, `agy_pro`, and `pro`. Their only purpose was to feed the `@#agy`
   spelling; with the aliases gone, `#agy` / `#agy_pro` / `#pro` no longer resolve to anything useful. The user-facing
   shortcuts remain the `m_*` presets (`#m_agy`, `#m_agy_pro`, `#m_agy_pro_flash`, `#m_swarm`). _(See Decision 1.)_

4. **Resolve the dangling `m_flash`** entry. `m_flash: "#m_agy_flash"` points at an xprompt that does not exist. Repoint
   it at `#m_agy` (the flash preset) or delete it. _(See Decision 2.)_

5. **Apply and verify**: run `chezmoi apply` so the live `~/.config/sase/sase.yml` picks up the change, then confirm the
   presets still route:
   - `sase doctor -C config.model_xprompts` and `sase doctor -C config.model_aliases` report OK.
   - Spot-check expansion of `#m_agy`, `#m_agy_pro`, `#m_agy_pro_flash`, and `#m_swarm` (e.g. via the model picker /
     directive extraction) resolves to the intended `agy` provider models.

### B. Sase-repo hardening (recommended)

6. **Regression test** locking in the behavior the config now depends on: a `%model` / `%m` paren argument quoting a
   `provider/model` string that contains **both spaces and parentheses** extracts the exact model, for the
   single-directive case and the `%{...}` fan-out case. Extend the existing suites (`tests/test_directives_extract.py`
   and `tests/test_directives_split_models.py`). This prevents a future parser refactor from silently breaking the
   user's presets.

7. **Doc fix**: `docs/llms.md` (~line 301) currently tells users to reach `agy` display names via
   `%model:agy/<exact name>` — the colon form, which we have shown breaks on spaces. Correct it to recommend the quoted
   paren form, e.g. `%m("agy/Gemini 3.5 Flash (High)")`. Add a one-line note in the `%model` directive section of
   `docs/xprompt.md` that model names containing spaces or parentheses must use the quoted paren form (the colon form
   cannot express them). Keep it provider-neutral.

## Decisions (recommendations; confirm during review)

- **Decision 1 — remove vs. keep `agy` / `agy_pro` / `pro` helper xprompts.** Recommendation: **remove**. They exist
  solely to support the `@#` alias spelling being retired. If the user types `#agy` / `#pro` interactively as a habit,
  we can instead keep thin aliases that expand to the full preset (e.g. `pro: "#m_agy_pro"`), but the cleaner end state
  is removal.
- **Decision 2 — `m_flash` dangling reference.** Recommendation: repoint to `#m_agy` so `#m_flash` becomes a working
  synonym for the flash preset, or delete it if unused. Either way the current broken state should not be carried
  forward.

## Explicitly out of scope

- **No change to the `%model` argument parser.** Quoting already works; touching the tokenizer would be risk without
  benefit.
- **Fan-out auto-name cosmetics.** When two branches share a runtime (e.g. `m_agy_pro_flash`'s two `agy` branches), the
  disambiguating suffix is derived from the model name and keeps the `.` from `3.5` / `3.1` (e.g.
  `...agy_Gemini_3.5_Flash_High`). This is **pre-existing** behavior — the naming path resolves aliases to the same
  target model, so switching from `@#agy` to the quoted form does not change it. A separate, optional follow-up could
  sanitize `.` out of fan-out suffixes in `src/sase/xprompt/_directive_alt_naming.py`, but it is not part of this task.
- **Short-alias colon form.** `agy/flash35h` and friends are display-only picker filters;
  `resolve_model_provider("agy/flash35h")` passes `flash35h` verbatim rather than expanding it, so they are not a
  reliable substitute in directives. The exact quoted display name is the correct form.

## Verification checklist

- Chezmoi: `chezmoi apply` succeeds; live `~/.config/sase/sase.yml` reflects the rewritten presets.
- Doctor: `config.model_xprompts` and `config.model_aliases` are OK (no fall-back-to-default warnings, no orphaned-alias
  references).
- Presets expand and route: `#m_agy` → `agy/Gemini 3.5 Flash (High)`, `#m_agy_pro` → `agy/Gemini 3.1 Pro (High)`,
  `#m_agy_pro_flash` and `#m_swarm` fan out to the intended models.
- Sase repo (if Part B is included): `just install` then `just check` pass, with the new regression test covering
  spaces + parentheses in a quoted `%model` argument.
